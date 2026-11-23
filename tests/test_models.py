"""The model seat, with urlopen patched: no test here touches the network."""

import json
import os
import unittest
import urllib.error
from unittest import mock

from ladder.models import ModelSeat
from ladder.run import run_once
from lair import load_spec
from lair.seat import validate_action

SPEC, KEY = load_spec(), "sk-or-v1-NOT-A-REAL-KEY"
DONE = {"status": "completed", "facts": [], "alarms": []}
OBS = {"pending": ["k1"], "replies": {"k0": DONE}, "checked": {}, "tries": {}, "types": {"k0": "medium"}, "budget_left": {"credits": 50}}
ORDER = {"goal": "g", "done_check": "d", "scope": "s", "reply_shape": {}, "budget": {"credits": 4, "seconds": 4}}
MAP = ("map", {"order": ORDER, "children": ["k1"], "worker_type": "medium"})
CHECK = ("check", {"children": ["k0"], "sample": 0.5})
ENDS = ["stop", "report"]


def reply(*calls):
    """Patch urlopen to answer once with these tool calls, so no request leaves the machine."""
    msg = {"tool_calls": [{"function": {"name": n, "arguments": json.dumps(a)}} for n, a in calls]}
    body = json.dumps({"choices": [{"message": msg}], "usage": {"prompt_tokens": 1000, "completion_tokens": 100}})
    resp = mock.MagicMock(**{"__enter__.return_value.read.return_value": body.encode()})
    return mock.patch("urllib.request.urlopen", return_value=resp)


def names(acts):
    return [a["name"] for a in acts]


@mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": KEY})
class TestModelSeat(unittest.TestCase):
    def setUp(self):
        self.seat = ModelSeat(SPEC)

    def test_provider_is_pinned_exactly(self):
        with reply(MAP) as urlopen:
            self.seat.decide(OBS)
        req = urlopen.call_args.args[0]
        body = json.loads(req.data)
        self.assertEqual(body["provider"], {"only": ["deepinfra", "together", "primeintellect"],
                                            "allow_fallbacks": False, "data_collection": "deny"})
        self.assertEqual((req.full_url, body["model"], body["temperature"]),
                         ("https://openrouter.ai/api/v1/chat/completions", "qwen/qwen3.5-9b", 0))
        self.assertEqual(len(body["tools"]), 5)

    def test_tool_calls_become_valid_actions(self):
        with reply(MAP, CHECK, ("report", {"summary": "ok"})):
            acts = self.seat.decide(OBS)
        self.assertEqual((names(acts), self.seat.format_errors), (["map", "check", "report"], 0))
        for a in acts:
            validate_action(SPEC, a)

    def test_invalid_or_missing_tool_call_is_counted_and_ends(self):
        for calls in ([("map", {"children": ["k1"]})], [], [("dance", {})], [("map", {**MAP[1], "children": ["zz"]})]):
            with self.subTest(calls=calls), reply(*calls):
                seat = ModelSeat(SPEC)
                self.assertEqual((names(seat.decide(OBS)), seat.format_errors), (ENDS, 1))

    def test_cache_makes_the_second_identical_request_free(self):
        with reply(MAP) as urlopen:
            first, second = self.seat.decide(OBS), self.seat.decide(json.loads(json.dumps(OBS)))
        self.assertEqual((first, urlopen.call_count, self.seat.calls), (second, 1, 1))

    def test_caps_stop_the_calls(self):
        for name, seat in {"cap_usd": ModelSeat(SPEC, cap_usd=0.0001), "max_calls": ModelSeat(SPEC, max_calls=1)}.items():
            with self.subTest(name), reply(MAP) as urlopen:
                seat.decide(OBS)
                self.assertEqual(names(seat.decide({**OBS, "budget_left": {"credits": 9}})), ENDS)  # not cached
                self.assertEqual(urlopen.call_count, 1)
                self.assertAlmostEqual(seat.spent_usd, (1000 * 0.15 + 100 * 0.25) / 1e6)

    def test_the_key_never_shows_in_an_error_or_a_row(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError(f"no host for {KEY}")):
            acts = self.seat.decide(OBS)
        self.assertEqual((names(acts), self.seat.format_errors), (ENDS, 1))
        self.assertNotIn(KEY, json.dumps(acts) + repr(vars(self.seat)))
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}), self.assertRaises(ValueError) as cm:
            self.seat.decide({**OBS, "pending": ["k9"]})
        self.assertNotIn(KEY, str(cm.exception))

    def test_only_rungs_r10_and_r47(self):
        with self.assertRaises(ValueError):
            run_once("r2209", "model", SPEC, 0)


if __name__ == "__main__":
    unittest.main()
