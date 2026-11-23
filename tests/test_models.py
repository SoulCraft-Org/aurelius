"""The model seat, with urlopen patched: no test here touches the network."""

import http.client
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
        two = {**OBS, "pending": ["k1", "k2"], "budget_left": {"credits": 20}}  # each large map fits alone, not both
        for obs, calls in ((OBS, [("map", {"children": ["k1"]})]), (OBS, []), (OBS, [("dance", {})]),
                           (OBS, [("map", {**MAP[1], "children": ["zz"]})]), (broke, [CHECK]),
                           (two, [("map", {**MAP[1], "children": ["k1"], "worker_type": "large"}),
                                  ("map", {**MAP[1], "children": ["k2"], "worker_type": "large"})])):  # 32 > 20: #54
            with self.subTest(calls=calls), reply(*calls):
                seat = ModelSeat(SPEC)
                self.assertEqual((names(seat.decide(obs)), seat.format_errors), (ENDS, 1))

    def test_a_check_on_a_key_mapped_earlier_in_the_reply_is_refused(self):  # #59: the map clears the reply, the check crashed the run
        failed = {**OBS, "pending": [], "replies": {"k0": {"status": "failed", "facts": [], "alarms": []}}}
        again = ("map", {**MAP[1], "children": ["k0"]})
        with reply(again):
            self.assertEqual(names(ModelSeat(SPEC).decide(failed)), ["map"])  # the resend alone is fine
        with reply(again, CHECK):
            seat = ModelSeat(SPEC)
            self.assertEqual((names(seat.decide(failed)), seat.format_errors), (ENDS, 1))

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
                self.assertNotIn(KEY, json.dumps(acts) + repr(vars(seat)) + json.dumps(seat.stats()))
                self.assertEqual(sum(seat.stats()["errors"].values()) >= 1, True)

    def test_score_runs_the_model_seat_end_to_end(self):
        # Regression: score() once passed the seat into run_once's budget slot and crashed before any call.
        from ladder.run import score
        with reply(("report", {"summary": "done"})):
            row = score("r10", "model", seeds=(0,))
        self.assertEqual((row["seat"], row["model"], row["workers"]), ("model", "qwen/qwen3.5-9b", "sim"))
        self.assertIn("verified_success", row["metrics"])
        self.assertEqual(sorted(row["model_stats"]), ["calls", "endpoint", "errors", "format_errors", "lock", "spent_usd"])
        self.assertGreaterEqual(row["model_stats"]["calls"], 1)

    def test_an_http_error_is_named_by_its_status(self):
        err = urllib.error.HTTPError("https://openrouter.ai", 404, f"no endpoint {KEY}", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            self.seat.decide(OBS)
        self.assertEqual(self.seat.stats()["errors"], {"TypeError": 1, "http_404": 1})
        self.assertNotIn(KEY, json.dumps(self.seat.stats()))

    def test_a_bad_cap_from_the_environment_fails_closed(self):
        for bad in ("nan", "-1"):
            with self.subTest(bad), mock.patch.dict(os.environ, {"MODEL_CAP_USD": bad}), self.assertRaises(ValueError):
                ModelSeat(SPEC)


@mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": KEY})
class TestAnyEndpoint(unittest.TestCase):  # #65: SEAT_URL, SEAT_MODEL, SEAT_KEY_ENV, SEAT_GPU_USD_H, SEAT_LOCK
    VLLM = {"SEAT_URL": "http://gpu.example:8000/v1/chat/completions", "SEAT_MODEL": "Qwen/Qwen3.5-9B"}

    def send(self, seat, obs=OBS):
        with reply(MAP) as urlopen:
            seat.decide(obs)
        req = urlopen.call_args.args[0]
        return req, json.loads(req.data)

    def test_the_override_url_and_model_are_used_and_openrouter_alone_gets_the_provider_block(self):
        with mock.patch.dict(os.environ, self.VLLM):
            seat = ModelSeat(SPEC)
            req, body = self.send(seat)
        self.assertEqual((req.full_url, body["model"], "provider" in body, "tool_choice" in body),
                         (self.VLLM["SEAT_URL"], "Qwen/Qwen3.5-9B", False, False))
        self.assertEqual((seat.stats()["endpoint"], seat.stats()["lock"]), ("custom", False))
        with mock.patch.dict(os.environ, {"SEAT_MODEL": "other/model"}):
            self.assertEqual(self.send(ModelSeat(SPEC))[1]["provider"]["allow_fallbacks"], False)  # OpenRouter keeps it

    def test_the_key_comes_from_the_named_variable_and_a_self_hosted_server_may_need_none(self):
        with mock.patch.dict(os.environ, {**self.VLLM, "SEAT_KEY_ENV": "VLLM_KEY", "VLLM_KEY": "local-secret"}):
            self.assertEqual(self.send(ModelSeat(SPEC))[0].get_header("Authorization"), "Bearer local-secret")
        with mock.patch.dict(os.environ, {**self.VLLM, "SEAT_KEY_ENV": "NO_SUCH_KEY"}):
            self.assertIsNone(self.send(ModelSeat(SPEC))[0].get_header("Authorization"))
        with mock.patch.dict(os.environ, {"SEAT_KEY_ENV": "NO_SUCH_KEY"}), self.assertRaises(RuntimeError):
            ModelSeat(SPEC).decide(OBS)  # OpenRouter without its key stays loud

    def test_the_openrouter_key_never_goes_to_another_host(self):
        with mock.patch.dict(os.environ, self.VLLM):  # OPENROUTER_API_KEY is set, SEAT_KEY_ENV is not
            seat = ModelSeat(SPEC)
            req, _ = self.send(seat)
        self.assertEqual((seat.key_var, req.get_header("Authorization")), ("", None))

    def test_the_url_scheme_is_https_or_http_for_a_server_that_is_not_openrouter(self):
        for url in ("file:///etc/passwd", "ftp://gpu.example/v1", "gpu.example/v1", "http://openrouter.ai/api/v1/chat/completions"):
            with self.subTest(url), mock.patch.dict(os.environ, {"SEAT_URL": url}), self.assertRaises(ValueError):
                ModelSeat(SPEC)
        with mock.patch.dict(os.environ, {"SEAT_URL": "https://gpu.example/v1/chat/completions"}):
            self.assertEqual(ModelSeat(SPEC).stats()["endpoint"], "custom")

    def test_an_error_nothing_catches_still_bills_in_full(self):
        with mock.patch("urllib.request.urlopen", side_effect=http.client.IncompleteRead(b"")), self.assertRaises(http.client.IncompleteRead):
            seat = ModelSeat(SPEC)
            seat.decide(OBS)
        self.assertGreater(seat.spent_usd, 1024 * 0.25 / 1e6)

    def test_the_lock_requires_a_tool_call_and_enumerates_the_keys_that_may_be_sent(self):
        obs = {**OBS, "pending": ["k1"], "checked": {"k2": False},
               "replies": {"k0": {"status": "completed"}, "k2": {"status": "completed"}, "k3": {"status": "failed"}}}
        with mock.patch.dict(os.environ, {"SEAT_LOCK": "1"}):
            seat = ModelSeat(SPEC)
            static = json.dumps(seat.tools)
            _, body = self.send(seat, obs)
        enum = {t["function"]["name"]: t["function"]["parameters"]["properties"]["children"] for t in body["tools"] if t["function"]["name"] in ("map", "check")}
        self.assertEqual(body["tool_choice"], "required")
        self.assertEqual(enum["map"]["items"]["enum"], ["k1", "k2", "k3"])  # pending plus retryable
        self.assertEqual(enum["check"]["items"]["enum"], ["k0", "k3"])  # replies not yet checked
        self.assertEqual((json.dumps(seat.tools), seat.stats()["lock"]), (static, True))  # built on a copy
        with mock.patch.dict(os.environ, {"SEAT_LOCK": "1"}):
            _, none = self.send(ModelSeat(SPEC), {**OBS, "pending": [], "replies": {}})
        self.assertFalse({"map", "check"} & {t["function"]["name"] for t in none["tools"]})  # no key, no tool

    def test_time_billing_trips_the_cap_and_the_ceiling_is_five_dollars(self):
        with mock.patch.dict(os.environ, {**self.VLLM, "SEAT_GPU_USD_H": "3600"}):  # $1 per second
            seat = ModelSeat(SPEC, cap_usd=2)
            self.assertEqual((seat.cap_usd, ModelSeat(SPEC, cap_usd=9).cap_usd), (2, 5.0))
            with reply(MAP) as urlopen, mock.patch("time.monotonic", side_effect=[10.0, 13.0]):
                seat.decide(OBS)
                self.assertEqual(names(seat.decide({**OBS, "budget_left": {"credits": 9}})), ENDS)  # 3 s x $1 >= $2
            self.assertEqual(urlopen.call_count, 1)
        self.assertAlmostEqual(seat.spent_usd, 3.0)  # tokens did not count: 1100 were reported
        self.assertEqual(ModelSeat(SPEC, cap_usd=9).cap_usd, 1.0)  # a token-billed API stays at $1

    def test_a_bad_gpu_price_fails_closed(self):
        for bad in ("nan", "-1", "inf"):
            with self.subTest(bad), mock.patch.dict(os.environ, {"SEAT_GPU_USD_H": bad}), self.assertRaises(ValueError):
                ModelSeat(SPEC)
