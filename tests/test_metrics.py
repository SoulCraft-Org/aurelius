"""Unit tests for the 8 metrics."""

import unittest

from ladder.metrics import METRIC_IDS, compute
from lair import load_spec


def row(kind, **data):
    return {"t": 0.0, "kind": kind, **data}


def final(verified, steps=1):
    return row("final", task_id="t", grade=1.0, verified=verified, critical_steps=steps)


class MetricsTest(unittest.TestCase):
    def test_ids_match_spec(self):
        self.assertEqual(list(METRIC_IDS), [m["id"] for m in load_spec()["metrics"]])

    def test_compute_has_all_keys(self):
        self.assertEqual(list(compute([[final(True)]])), list(METRIC_IDS))
        self.assertEqual(list(compute([])), list(METRIC_IDS))

    def test_verified_success_and_cost(self):
        logs = [
            [row("spend", credits=3, seconds=1), final(True, 4)],
            [row("spend", credits=5, seconds=1), final(False, 8)],
            [row("spend", credits=4, seconds=1), final(True, 6)],
            [final(False, 2)],
        ]
        out = compute(logs)
        self.assertEqual(out["verified_success"], 50.0)
        self.assertEqual(out["cost_per_verified_success"], 6.0)
        self.assertEqual(out["critical_steps"], 5.0)

    def test_no_verified_runs(self):
        out = compute([[row("spend", credits=3, seconds=1), final(False)]])
        self.assertEqual(out["verified_success"], 0.0)
        self.assertIsNone(out["cost_per_verified_success"])

    def test_error_growth_new_errors_count(self):
        rep = row("report", tier=1, facts_in=10, wrong_in=0, facts_out=10, wrong_out=2)
        self.assertAlmostEqual(compute([[rep]])["error_growth_per_tier"], 3.0)

    def test_error_growth_clean_is_one(self):
        rep = row("report", tier=1, facts_in=8, wrong_in=0, facts_out=8, wrong_out=0)
        self.assertEqual(compute([[rep]])["error_growth_per_tier"], 1.0)

    def test_error_growth_pools_a_tier(self):
        a = row("report", tier=1, facts_in=4, wrong_in=1, facts_out=4, wrong_out=0)
        b = row("report", tier=1, facts_in=6, wrong_in=1, facts_out=6, wrong_out=3)
        # pooled: in 10 facts, 2 wrong; out 10 facts, 3 wrong -> (4/12) / (3/12)
        self.assertAlmostEqual(compute([[a], [b]])["error_growth_per_tier"], 4 / 3)

    def test_error_growth_means_over_tiers(self):
        a = row("report", tier=1, facts_in=10, wrong_in=0, facts_out=10, wrong_out=2)
        b = row("report", tier=2, facts_in=10, wrong_in=0, facts_out=10, wrong_out=0)
        self.assertAlmostEqual(compute([[a, b]])["error_growth_per_tier"], 2.0)

    def test_error_growth_none_without_reports(self):
        self.assertIsNone(compute([[final(True)]])["error_growth_per_tier"])
        self.assertIsNone(compute([])["error_growth_per_tier"])

    def test_alarms_reaching_top(self):
        logs = [
            [row("alarm_planted", key="a"), row("alarm_planted", key="b"), row("alarm_top", key="a")],
            [row("alarm_planted", key="a"), row("alarm_planted", key="c")],
        ]
        self.assertEqual(compute(logs)["alarms_reaching_top"], 25.0)

    def test_no_alarms(self):
        self.assertIsNone(compute([[row("alarm_top", key="a")]])["alarms_reaching_top"])

    def test_fake_split_rate(self):
        logs = [[row("split", tier=1, shortened=True), row("split", tier=2, shortened=False)],
                [row("split", tier=1, shortened=False), row("split", tier=1, shortened=False)]]
        self.assertEqual(compute(logs)["fake_split_rate"], 75.0)

    def test_no_splits(self):
        self.assertIsNone(compute([[final(True)]])["fake_split_rate"])

    def test_resume_rate(self):
        logs = [[row("kill", seat="a"), row("resume", seat="a", same=True),
                 row("kill", seat="b"), row("resume", seat="b", same=False)],
                [row("kill", seat="a"), row("resume", seat="a", same=True),
                 row("kill", seat="c"), row("resume", seat="c", same=True)]]
        self.assertEqual(compute(logs)["resume_rate"], 75.0)

    def test_no_kills(self):
        self.assertIsNone(compute([[final(True)]])["resume_rate"])

    def test_budget_overruns_counts_rows(self):
        logs = [[row("overrun", key="a"), row("overrun", key="a")], [row("overrun", key="b")]]
        self.assertEqual(compute(logs)["budget_overruns"], 3)
        self.assertEqual(compute([[final(True)]])["budget_overruns"], 0)


if __name__ == "__main__":
    unittest.main()
