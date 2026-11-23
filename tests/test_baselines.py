"""Unit tests for the three baselines."""

import random
import unittest

from lair import load_spec
from lair.baselines import NAMES, PASS_GRADE, run_baseline
from lair.tasks import grade, make_task
from lair.workers import do_item, worker_types

SPEC = load_spec()
BIG = 10**9


def rows(log, kind):
    return [r for r in log if r["kind"] == kind]


def credits(log):
    return sum(r["credits"] for r in rows(log, "spend"))


class BaselinesTest(unittest.TestCase):
    def test_deterministic_for_a_seed(self):
        task = make_task(1, 200)
        for name in NAMES:
            a = run_baseline(name, task, SPEC, 7, BIG)
            self.assertEqual(a, run_baseline(name, task, SPEC, 7, BIG))
            self.assertTrue(all("t" in r and "kind" in r for r in a))

    def test_one_final_row_and_unknown_name(self):
        task = make_task(2, 50)
        for name in NAMES:
            self.assertEqual(len(rows(run_baseline(name, task, SPEC, 1, BIG), "final")), 1)
        with self.assertRaises(ValueError):
            run_baseline("nope", task, SPEC, 1, BIG)

    def test_spend_never_passes_the_budget(self):
        task = make_task(3, 300)
        for name in NAMES:
            for budget in (0, 15, 100, 101, 1000):
                log = run_baseline(name, task, SPEC, 4, budget)
                self.assertLessEqual(credits(log), budget)
                self.assertEqual(rows(log, "overrun"), [])
                self.assertEqual(len(rows(log, "final")), 1)

    def test_budget_cuts_the_work_and_the_grade(self):
        task = make_task(3, 300)
        full = rows(run_baseline("flat_fan_out", task, SPEC, 4, BIG), "final")[0]
        cut = run_baseline("flat_fan_out", task, SPEC, 4, 40)
        self.assertEqual(len(rows(cut, "spend")), 10)
        self.assertLess(rows(cut, "final")[0]["grade"], full["grade"])

    def test_one_agent_is_slower_than_flat_on_a_table(self):
        task = make_task(5, 100)
        one = run_baseline("one_agent", task, SPEC, 2, BIG)
        flat = run_baseline("flat_fan_out", task, SPEC, 2, BIG)
        self.assertEqual(rows(one, "split"), [])
        self.assertEqual(rows(one, "final")[0]["critical_steps"], 100)
        self.assertEqual(rows(flat, "final")[0]["critical_steps"], 1)
        self.assertGreater(one[-1]["t"], flat[-1]["t"])

    def test_flat_on_no_split_does_not_shorten(self):
        task = make_task(6, 40, kind="no_split")
        for name in ("flat_fan_out", "cheapest_that_passes"):
            log = run_baseline(name, task, SPEC, 3, BIG)
            self.assertEqual(rows(log, "split"), [{"t": 0.0, "kind": "split", "tier": 1, "shortened": False}])
            self.assertEqual(rows(log, "final")[0]["critical_steps"], 40)
        table = run_baseline("flat_fan_out", make_task(6, 40), SPEC, 3, BIG)
        self.assertTrue(rows(table, "split")[0]["shortened"])

    def test_cheapest_picks_the_cheapest_type_that_clears_the_bar(self):
        log = run_baseline("cheapest_that_passes", make_task(7, 20), SPEC, 1, BIG)
        self.assertEqual({r["credits"] for r in rows(log, "spend")}, {4})

    def test_final_grade_matches_tasks_grade(self):
        task = make_task(8, 120, fault_rate=0.2)
        types = worker_types(SPEC)
        for name, tid in (("one_agent", "large"), ("flat_fan_out", "medium")):
            rng = random.Random(9)
            answers = {}
            for it in task.items:
                reply = do_item(rng, types[tid], it)
                if reply["status"] == "completed":
                    answers[it.key] = reply["facts"][0]["value"]
            final = rows(run_baseline(name, task, SPEC, 9, BIG), "final")[0]
            self.assertEqual(final["grade"], grade(task, answers))
            self.assertEqual(final["verified"], final["grade"] >= PASS_GRADE)
            self.assertEqual(final["task_id"], task.id)

    def test_alarms_are_planted_and_some_reach_the_top(self):
        task = make_task(10, 500, alarm_rate=0.1)
        planted = {it.key for it in task.items if it.alarm}
        log = run_baseline("flat_fan_out", task, SPEC, 5, BIG)
        self.assertEqual({r["key"] for r in rows(log, "alarm_planted")}, planted)
        top = {r["key"] for r in rows(log, "alarm_top")}
        self.assertTrue(top and top <= planted)

    def test_a_full_size_task_runs(self):
        task = make_task(11, 103823)
        log = run_baseline("cheapest_that_passes", task, SPEC, 1, BIG)
        self.assertEqual(len(rows(log, "spend")), 103823)


if __name__ == "__main__":
    unittest.main()
