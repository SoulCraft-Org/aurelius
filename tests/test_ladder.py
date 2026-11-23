"""Unit tests for the Ladder runner. Rungs r10 and r47 run; r2209 is built, and run once."""

import contextlib
import io
import json
import unittest
from functools import partial
from types import SimpleNamespace
from unittest import mock

from ladder.metrics import METRIC_IDS
from ladder.run import _Leaf, _kill_and_resume, _lift, main, parse_args, run_once, score, tree
from lair import load_spec
from lair.baselines import NAMES
from lair.sim import Sim
from lair.tasks import make_task

SPEC = load_spec()
SEATS = ("rule", *NAMES)


def rows(log, kind):
    return [r for r in log if r["kind"] == kind]


class RunTest(unittest.TestCase):
    def test_the_tree_matches_the_spec_seats(self):
        self.assertEqual(sum(tree(SPEC, "r2209")), 48)
        self.assertEqual([sum(tree(SPEC, r["id"])) for r in SPEC["rungs"]], [r["seats"] for r in SPEC["rungs"]])

    def test_every_seat_scores_the_same_twice_inside_its_budget(self):
        for rung in ("r10", "r47"):
            for seat in SEATS:
                a, b = score(rung, seat, (1,)), score(rung, seat, (1,))
                self.assertEqual(a["metrics"], b["metrics"])
                self.assertEqual((tuple(a["metrics"]), a["metrics"]["budget_overruns"]), (METRIC_IDS, 0))
                self.assertEqual((list(a), a["workers"]), (SPEC["score_row"]["fields"], "sim"))

    def test_the_rule_seat_resumes_a_killed_leaf_and_a_tier_checks_up(self):
        log = run_once("r2209", "rule", SPEC, 0)
        self.assertEqual([r["same"] for r in rows(log, "resume")], [True])
        self.assertTrue([r for r in rows(log, "check") if r["tier"] == 2])

    def test_the_rule_seat_and_a_baseline_get_the_same_budget(self):
        with mock.patch("ladder.run.run_baseline") as base, mock.patch("ladder.run._rule") as rule:
            run_once("r10", "one_agent", SPEC, 1), run_once("r10", "rule", SPEC, 1)
        self.assertEqual((base.call_args.args[4], rule.call_args.args[4]), (50, 50))

    def test_a_leaf_is_killed_part_way_and_resume_matches_the_full_run(self):
        task = make_task(1, 47)
        make = partial(_Leaf, SPEC, task, task.items, 1, 5 * 47)
        full = make()
        full.sim.run()
        saved, resumed = _kill_and_resume(make, full)
        self.assertTrue(0 < len(saved.entries) < len(full.led.entries))
        self.assertEqual(resumed.entries, full.led.entries)
        self.assertEqual([r["same"] for r in rows(run_once("r47", "rule", SPEC, 1), "resume")], [True])

    def test_an_alarm_goes_up_only_with_a_kept_fact(self):
        item, fact = SimpleNamespace(answer="x"), {"claim": "a", "value": "x"}
        leaf = _Leaf.__new__(_Leaf)  # only report() runs, on replies set by hand
        leaf.sim, leaf.items, leaf.checked = Sim(0), {"a": item, "b": item}, {"b": False}
        leaf.replies = {k: {"status": "completed", "facts": [fact], "alarms": [k]} for k in "ab"}
        leaf.report()
        self.assertEqual(leaf.alarms, ["a"])
        kids, task = [({"a": fact}, ["a"])], SimpleNamespace(can_split=True)
        for verdict, up in ((False, []), (True, ["a"])):
            with mock.patch("ladder.run.check", return_value=verdict):
                self.assertEqual(_lift(Sim(0), task, SPEC, {"a": item}, 2, kids, [100])[1], up)

    def test_no_split_takes_every_step_and_no_split_row_is_shortened(self):
        log = run_once("r10", "rule", SPEC, 1, "no_split")
        self.assertEqual(rows(log, "final")[0]["critical_steps"], 10)
        self.assertTrue(rows(log, "split"))
        self.assertFalse([r for r in rows(log, "split") if r["shortened"]])

    def test_every_seat_spends_at_most_5_credits_per_agent(self):
        for rung in ("r10", "r47"):
            agents = next(r["agents"] for r in SPEC["rungs"] if r["id"] == rung)
            for seat in SEATS:
                spent = sum(r["credits"] for r in rows(run_once(rung, seat, SPEC, 1), "spend"))
                self.assertLessEqual(spent, 5 * agents, (rung, seat))

    def test_the_command_line_prints_the_score_row(self):
        args = parse_args(["--rung", "r47", "--seat", "rule", "--seeds", "3"])
        self.assertEqual((args.rung, args.seat, args.seeds), ("r47", "rule", 3))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["--rung", "r10", "--seat", "flat_fan_out", "--seeds", "2"])
        self.assertEqual(json.loads(out.getvalue()), score("r10", "flat_fan_out", (0, 1)))
