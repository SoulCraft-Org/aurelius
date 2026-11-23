"""Unit tests for the stand-in workers."""

import random
import unittest
from collections import namedtuple

from lair import load_spec
from lair.workers import CHECK_COST, check, do_item, worker_types

Item = namedtuple("Item", "key answer fault alarm after")
SPEC = load_spec()
TYPES = worker_types(SPEC)
N = 4000


def item(fault=False, alarm=False):
    return Item("k1", "42", fault, alarm, None)


def is_right(reply):
    return reply["status"] == "completed" and reply["facts"][0]["value"] == "42"


class WorkersTest(unittest.TestCase):
    def test_worker_types_read_the_spec(self):
        self.assertEqual(set(TYPES), {"small", "medium", "large"})
        self.assertEqual(TYPES["medium"], {"credits_per_call": 4, "skill": 0.8, "seconds": 4})
        self.assertEqual(CHECK_COST, TYPES["small"]["credits_per_call"])

    def test_fixed_rng_is_deterministic(self):
        rng1, rng2 = random.Random(7), random.Random(7)
        r1 = [do_item(rng1, TYPES["small"], item(alarm=True)) for _ in range(50)]
        r2 = [do_item(rng2, TYPES["small"], item(alarm=True)) for _ in range(50)]
        self.assertEqual(r1, r2)

    def test_correct_rate_near_skill(self):
        for name, t in TYPES.items():
            rng = random.Random(1)
            hits = sum(is_right(do_item(rng, t, item(), crash_rate=0)) for _ in range(N))
            self.assertAlmostEqual(hits / N, t["skill"], delta=0.03, msg=name)

    def test_fault_halves_the_skill(self):
        t = TYPES["large"]
        rng = random.Random(2)
        hits = sum(is_right(do_item(rng, t, item(fault=True), crash_rate=0)) for _ in range(N))
        self.assertAlmostEqual(hits / N, t["skill"] / 2, delta=0.03)

    def test_crash_fails_and_still_spends(self):
        reply = do_item(random.Random(3), TYPES["medium"], item(alarm=True), crash_rate=1.0)
        self.assertEqual(reply["status"], "failed")
        self.assertEqual((reply["facts"], reply["alarms"]), ([], []))
        self.assertEqual(reply["spent"], {"credits": 4, "seconds": 4})

    def test_reply_keys_match_the_spec(self):
        want = {f["field"] for f in SPEC["reply"]}
        rng = random.Random(4)
        for _ in range(20):
            reply = do_item(rng, TYPES["small"], item())
            self.assertEqual(set(reply), want)
            self.assertIn(reply["status"], SPEC["task_states"])
            for fact in reply["facts"]:
                self.assertEqual(set(fact), {"claim", "value", "tag", "source"})
                self.assertIn(fact["tag"], SPEC["fact_tags"])

    def test_wrong_value_and_tags(self):
        rng = random.Random(5)
        tags = []
        for _ in range(200):
            fact = do_item(rng, TYPES["small"], item(), crash_rate=0)["facts"][0]
            if fact["value"] == "42":
                self.assertEqual(fact["tag"], "seen")
            else:
                self.assertEqual(fact["value"], "42?")
                tags.append(fact["tag"])
        self.assertEqual(sorted(set(tags)), ["inferred", "seen"])

    def test_alarm_noticed_at_skill(self):
        t = TYPES["medium"]
        rng = random.Random(6)
        seen = sum(bool(do_item(rng, t, item(alarm=True), crash_rate=0)["alarms"]) for _ in range(N))
        self.assertAlmostEqual(seen / N, t["skill"], delta=0.03)
        self.assertEqual(do_item(rng, t, item(), crash_rate=0)["alarms"], [])

    def test_check_error_rates_near_spec(self):
        rng = random.Random(8)
        sure = {"credits_per_call": 1, "skill": 1.0, "seconds": 1}
        right = do_item(random.Random(0), sure, item(), crash_rate=0)
        wrong = dict(right, facts=[dict(right["facts"][0], value="42?")])
        failed = dict(right, status="failed", facts=[])
        false_fail = sum(not check(rng, right, item(), SPEC) for _ in range(N)) / N
        false_pass = sum(check(rng, wrong, item(), SPEC) for _ in range(N)) / N
        crash_pass = sum(check(rng, failed, item(), SPEC) for _ in range(N)) / N
        want = SPEC["check"]
        self.assertAlmostEqual(false_fail, want["false_fail"], delta=0.02)
        self.assertAlmostEqual(false_pass, want["false_pass"], delta=0.02)
        self.assertAlmostEqual(crash_pass, want["false_pass"], delta=0.02)

    def test_no_global_random(self):
        random.seed(99)
        before = random.getstate()
        rng = random.Random(9)
        reply = do_item(rng, TYPES["large"], item(alarm=True))
        check(rng, reply, item(), SPEC)
        self.assertEqual(random.getstate(), before)


if __name__ == "__main__":
    unittest.main()
