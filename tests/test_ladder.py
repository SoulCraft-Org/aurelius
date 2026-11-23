"""Unit tests for the Ladder runner. Rungs r10 and r47 run; r2209 is built, and run once."""

import unittest

from ladder.metrics import METRIC_IDS
from ladder.run import run_once, score, tree
from lair import load_spec
from lair.baselines import NAMES

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
                log = run_once(rung, seat, SPEC, 1, "no_split")
                self.assertEqual(rows(log, "final")[0]["critical_steps"], int(rung[1:]))

    def test_the_rule_seat_resumes_a_killed_leaf_and_a_tier_checks_up(self):
        log = run_once("r2209", "rule", SPEC, 0, budget=6 * 2209)
        self.assertEqual([r["same"] for r in rows(log, "resume")], [True])
        self.assertEqual(sorted({r["tier"] for r in rows(log, "report")}), [1, 2])
        self.assertTrue([r for r in rows(log, "check") if r["tier"] == 2])
        self.assertEqual(rows(log, "overrun"), [])
