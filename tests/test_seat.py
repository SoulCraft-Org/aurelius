"""Unit tests for the seat."""

import unittest

from lair import load_spec
from lair.seat import RuleSeat, Seat, validate_action, validate_order

SPEC = load_spec()
OK = {"status": "completed", "facts": [], "alarms": []}
BAD = {"status": "failed", "facts": [], "alarms": []}
ORDER = {"goal": "g", "done_check": "d", "scope": "s", "reply_shape": {}, "budget": {"credits": 1, "seconds": 2}}
MAP = {"name": "map", "order": ORDER, "children": ["a"], "worker_type": "small"}


def obs(**kw):
    return {"pending": [], "replies": {}, "checked": {}, "tries": {}, "types": {},
            "budget_left": {"credits": 100}, **kw}


def valid(actions):
    for a in actions:
        validate_action(SPEC, a)
    return actions


class ValidateTest(unittest.TestCase):
    def rejects(self, fn, cases):
        for c in cases:
            with self.assertRaises(ValueError, msg=c):
                fn(SPEC, c)

    def test_orders(self):
        self.assertRaises(TypeError, Seat)
        validate_order(SPEC, {**ORDER, "budget": {"credits": 0, "seconds": 0.5, "tokens": 9}})
        bad = [3, {"credits": 1}, {"credits": -1, "seconds": 1}, {"credits": "1", "seconds": 1}]
        self.rejects(validate_order, [{**ORDER, "budget": b} for b in bad] + [{**ORDER, "x": 1}, "x"])

    def test_actions(self):
        for a in [MAP, {"name": "wait"}, {"name": "stop", "children": [], "grace_s": 5},
                  {"name": "check", "children": ["a"], "sample": 0.2}, {"name": "report", "summary": "s"}]:
            validate_action(SPEC, a)
        self.rejects(validate_action, [
            "x", None, {}, {"name": 5}, {"name": "dance"}, {"name": "wait", "children": []},
            {"name": "map", "children": ["a"], "worker_type": "small"},
            {**MAP, "children": "a"}, {**MAP, "order": "x"}, {**MAP, "worker_type": "huge"},
            {**MAP, "worker_type": []}, {"name": "check"}, {"name": "report"},
            {"name": "stop", "children": [], "grace_s": "5"}, {"name": "check", "children": [], "sample": -1}])


class RuleSeatTest(unittest.TestCase):
    def test_cheapest_type_that_clears_the_bar(self):
        for bar, wtype in [(0.5, "small"), (0.75, "medium"), (0.9, "large"), (0.99, "large")]:
            [m] = valid(RuleSeat(SPEC, bar=bar).decide(obs(pending=["b", "a"])))
            self.assertEqual((m["worker_type"], m["children"]), (wtype, ["a", "b"]))

    def test_check_sample_is_deterministic(self):
        replies = {f"k{i}": OK for i in range(10)}
        o = obs(replies=replies, types={k: "medium" for k in replies})
        [c] = valid(RuleSeat(SPEC).decide(o))
        self.assertEqual((c["name"], c["children"], c["sample"]), ("check", ["k4", "k9"], 0.2))
        [c] = RuleSeat(SPEC).decide({**o, "checked": {"k4": True}})
        self.assertEqual(c["children"], ["k9"])

    def test_fix_loop(self):
        for reply, n, wtype in [(BAD, 1, "small"), (BAD, 2, "small"), (BAD, 3, "medium"), (OK, 1, "small")]:
            o = obs(replies={"a": reply}, checked={"a": False}, types={"a": "small"}, tries={"a": n})
            [m] = valid(RuleSeat(SPEC).decide(o))
            self.assertEqual((m["worker_type"], m["children"]), (wtype, ["a"]), n)
        for wtype, n in [("medium", 4), ("large", 3)]:
            o = obs(replies={"a": BAD}, types={"a": wtype}, tries={"a": n})
            [r] = valid(RuleSeat(SPEC).decide(o))
            self.assertEqual((r["name"], "parked: a" in r["summary"]), ("report", True))

    def test_budget(self):
        o = obs(pending=["b"], types={"a": "small"}, budget_left={"credits": 0.5})
        [s] = valid(RuleSeat(SPEC).decide(o))
        self.assertEqual((s["name"], s["children"]), ("stop", ["a", "b"]))
        for credits, sent in [(1, []), (4, ["a"]), (9, ["a", "b"]), (99, ["a", "b", "c"])]:
            acts = valid(RuleSeat(SPEC).decide(obs(pending=["c", "b", "a"], budget_left={"credits": credits})))
            self.assertEqual(sum((a["children"] for a in acts if a["name"] == "map"), []), sent)
        self.assertEqual(acts[0]["order"]["budget"]["credits"], 12)

    def test_report_and_wait(self):
        seat = RuleSeat(SPEC)
        self.assertEqual(valid(seat.decide(obs()))[0]["name"], "report")
        [r] = valid(seat.decide(obs(replies={"a": {**OK, "alarms": ["z", "y"]}}, types={"a": "small"})))
        self.assertEqual(r["alarms"], ["y", "z"])
        self.assertEqual(valid(seat.decide(obs(types={"a": "small"})))[0]["name"], "wait")

    def test_same_obs_same_actions(self):
        replies = {f"k{i}": OK if i % 3 else BAD for i in range(12)}
        o = obs(pending=["p1", "p0"], replies=replies, types={k: "small" for k in replies})
        first = valid(RuleSeat(SPEC).decide(o))
        self.assertEqual(first, RuleSeat(SPEC).decide(o))
        self.assertEqual(({a["name"] for a in first}, isinstance(RuleSeat(SPEC), Seat)), ({"map", "check"}, True))
