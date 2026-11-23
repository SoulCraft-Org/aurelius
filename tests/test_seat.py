"""Unit tests for the seat."""

import copy
import unittest

from lair import load_spec
from lair.seat import RuleSeat, Seat, validate_action, validate_order

SPEC = load_spec()
OK = {"status": "completed", "facts": [], "alarms": []}
BAD = {"status": "failed", "facts": [], "alarms": []}
GOOD = {"goal": "g", "done_check": "d", "scope": "s", "reply_shape": {},
        "budget": {"credits": 1, "seconds": 2}}


def obs(**kw):
    base = {"pending": [], "replies": {}, "checked": {}, "tries": {}, "types": {},
            "budget_left": {"credits": 100}}
    return {**base, **kw}


def valid(actions):
    for a in actions:
        validate_action(SPEC, a)
        if a["name"] == "map":
            validate_order(SPEC, a["order"])
    return actions


class ValidateTest(unittest.TestCase):
    def test_orders(self):
        validate_order(SPEC, {**GOOD, "budget": {"credits": 0, "seconds": 0.5, "tokens": 9}})
        bad = [{**GOOD, "more": 1}, {k: v for k, v in GOOD.items() if k != "scope"}, "x"]
        for budget in [3, {"credits": 1}, {"credits": -1, "seconds": 1},
                       {"credits": "1", "seconds": 1}, {"credits": True, "seconds": 1}]:
            bad.append({**GOOD, "budget": budget})
        for o in bad:
            with self.assertRaises(ValueError, msg=o):
                validate_order(SPEC, o)

    def test_actions(self):
        validate_action(SPEC, {"name": "wait"})
        validate_action(SPEC, {"name": "stop", "children": [], "grace_s": 5})
        for a in [{"name": "dance"}, {}, {"name": "wait", "children": []}]:
            with self.assertRaises(ValueError, msg=a):
                validate_action(SPEC, a)


class RuleSeatTest(unittest.TestCase):
    def test_is_abstract(self):
        self.assertIsInstance(RuleSeat(SPEC), Seat)
        with self.assertRaises(TypeError):
            Seat()

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
        seat = RuleSeat(SPEC)
        for n, wtype in [(1, "small"), (2, "small"), (3, "medium")]:
            [m] = seat.decide(obs(replies={"a": BAD}, types={"a": "small"}, tries={"a": n}))
            self.assertEqual((m["worker_type"], m["children"]), (wtype, ["a"]), n)
        for wtype, n in [("medium", 4), ("large", 3)]:
            [r] = valid(seat.decide(obs(replies={"a": BAD}, types={"a": wtype}, tries={"a": n})))
            self.assertEqual(r["name"], "report")
            self.assertIn("parked: a", r["summary"])
        o = obs(replies={"a": OK}, checked={"a": False}, types={"a": "small"}, tries={"a": 1})
        self.assertEqual(seat.decide(o)[0]["worker_type"], "small")

    def test_stops_when_budget_is_under_cheapest_call(self):
        o = obs(pending=["b"], types={"a": "small"}, budget_left={"credits": 0.5})
        [s] = valid(RuleSeat(SPEC).decide(o))
        self.assertEqual((s["name"], s["children"]), ("stop", ["a", "b"]))
        o = obs(pending=["b"], budget_left={"credits": 1})
        self.assertEqual(RuleSeat(SPEC).decide(o)[0]["name"], "map")

    def test_report_and_wait(self):
        seat = RuleSeat(SPEC)
        self.assertEqual(valid(seat.decide(obs()))[0]["name"], "report")
        done = obs(replies={"a": {**OK, "alarms": ["z", "y"]}}, types={"a": "small"})
        [r] = valid(seat.decide(done))
        self.assertEqual((r["name"], r["alarms"]), ("report", ["y", "z"]))
        [w] = valid(seat.decide(obs(types={"a": "small"})))
        self.assertEqual(w["name"], "wait")

    def test_same_obs_same_actions(self):
        replies = {f"k{i}": OK if i % 3 else BAD for i in range(12)}
        o = obs(pending=["p1", "p0"], replies=replies, types={k: "small" for k in replies},
                tries={k: 1 for k in replies})
        before = copy.deepcopy(o)
        first = valid(RuleSeat(SPEC).decide(o))
        self.assertEqual(first, RuleSeat(SPEC).decide(o))
        self.assertEqual(o, before)
        self.assertEqual({a["name"] for a in first}, {"map", "check"})
