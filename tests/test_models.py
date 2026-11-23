"""The model seat, with urlopen patched: no test here touches the network."""

import json
import os
import unittest
import urllib.error
from unittest import mock

from ladder.models import ModelSeat
from lair import load_spec

SPEC, KEY = load_spec(), "sk-or-v1-NOT-A-REAL-KEY"
OBS = {"pending": ["k1"], "replies": {"k0": {"status": "completed", "facts": [], "alarms": []}}, "checked": {}, "tries": {},
       "types": {"k0": "medium"}, "budget_left": {"credits": 50}}
MAP = ("map", {"children": ["k1"], "worker_type": "medium",
                "order": {"goal": "g", "done_check": "d", "scope": "s", "reply_shape": {}, "budget": {"credits": 4, "seconds": 4}}})
CHECK = ("check", {"children": ["k0"], "sample": 0.5})
ENDS = ["stop", "report"]


def reply(*calls, raw=None):  # urlopen answers with these tool calls (or raw bytes), so no request leaves the machine
    msg = {"tool_calls": [{"function": {"name": n, "arguments": json.dumps(a)}} for n, a in calls]}
    body = {"choices": [{"message": msg}], "usage": {"prompt_tokens": 1000, "completion_tokens": 100}}
    resp = mock.MagicMock(**{"__enter__.return_value.read.return_value": raw or json.dumps(body).encode()})
    return mock.patch("urllib.request.urlopen", return_value=resp)


names = lambda acts: [a["name"] for a in acts]


@mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": KEY})
class TestModelSeat(unittest.TestCase):
    def setUp(self):
        self.seat = ModelSeat(SPEC)

    def test_provider_is_pinned_exactly(self):
        with reply(MAP, CHECK) as urlopen:
            acts = self.seat.decide(OBS)
        req = urlopen.call_args.args[0]
        body = json.loads(req.data)
        self.assertEqual(body["provider"], {"only": ["deepinfra", "together", "primeintellect"],
                                            "allow_fallbacks": False, "data_collection": "deny"})
        self.assertEqual((req.full_url, body["model"], body["temperature"], body["max_tokens"]),
                         ("https://openrouter.ai/api/v1/chat/completions", "qwen/qwen3.5-9b", 0, 1024))
        self.assertEqual(acts, [{"name": n, **a} for n, a in (MAP, CHECK)])

    def test_invalid_or_missing_tool_call_is_counted_and_ends(self):
        broke = {**OBS, "budget_left": {"credits": 0}}  # a check it cannot pay for would never advance
        for obs, calls in ((OBS, [("map", {"children": ["k1"]})]), (OBS, []), (OBS, [("dance", {})]),
                           (OBS, [("map", {**MAP[1], "children": ["zz"]})]), (broke, [CHECK])):
            with self.subTest(calls=calls), reply(*calls):
                seat = ModelSeat(SPEC)
                self.assertEqual((names(seat.decide(obs)), seat.format_errors), (ENDS, 1))

    def test_the_cache_is_free_and_a_looping_seat_ends(self):
        seat = ModelSeat(SPEC, max_calls=1)
        with reply(MAP) as urlopen:  # the same request is answered free; the asks limit (5 x max_calls) cuts a loop
            got = [seat.decide(OBS) for _ in range(7)]
        self.assertEqual((got[0] == got[4], names(got[0]), names(got[5]), names(got[6])), (True, ["map"], ENDS, ENDS))
        self.assertEqual((urlopen.call_count, seat.calls), (1, 1))

    def test_caps_stop_the_calls(self):
        for name, seat in {"cap_usd": ModelSeat(SPEC, cap_usd=0.0001), "max_calls": ModelSeat(SPEC, max_calls=1)}.items():
            with self.subTest(name), reply(MAP) as urlopen:
                seat.decide(OBS)
                self.assertEqual(names(seat.decide({**OBS, "budget_left": {"credits": 9}})), ENDS)  # not cached
                self.assertEqual(urlopen.call_count, 1)
                self.assertAlmostEqual(seat.spent_usd, (1000 * 0.15 + 100 * 0.25) / 1e6)

    def test_a_failed_call_is_billed_and_leaks_no_key(self):
        boom = mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError(f"no host for {KEY}"))
        for patch in (boom, reply(raw=b"<html>not json</html>"), reply(raw=b'{"usage": null}')):
            with self.subTest(patch=patch), patch:
                seat = ModelSeat(SPEC)
                acts = seat.decide(OBS)
                self.assertEqual((names(acts), seat.format_errors), (ENDS, 1))
                self.assertGreater(seat.spent_usd, 1024 * 0.25 / 1e6)  # at least a full answer: unknown is never zero
                self.assertNotIn(KEY, json.dumps(acts) + repr(vars(seat)))

    def test_score_runs_the_model_seat_end_to_end(self):
        # Regression: score() once passed the seat into run_once's budget slot and crashed before any call.
        from ladder.run import score
        with reply(("report", {"summary": "done"})):
            row = score("r10", "model", seeds=(0,))
        self.assertEqual((row["seat"], row["model"], row["workers"]), ("model", "qwen/qwen3.5-9b", "sim"))
        self.assertIn("verified_success", row["metrics"])

    def test_a_bad_cap_from_the_environment_fails_closed(self):
        for bad in ("nan", "-1"):
            with self.subTest(bad), mock.patch.dict(os.environ, {"MODEL_CAP_USD": bad}), self.assertRaises(ValueError):
                ModelSeat(SPEC)
