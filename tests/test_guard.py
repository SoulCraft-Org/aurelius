"""The Modal spend guard, with fake billing JSON and a temp ledger: no Modal, no network, no subprocess."""

import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from train import guard

MONTH, NOW = "2026-11", datetime(2026, 11, 23, tzinfo=timezone.utc)
WORST = guard.worst_usd(1800, 0.80)  # $0.40
SNAKE = {"metered_cost": "5.00", "billed_cost": "0", "adjustments": {}, "metered_cost_breakdown": {}}
TITLE = {"Metered Cost": "$5.00", "Billed Cost": "$0.00"}


def row(run_id="2026-11-20T000000Z-smoke", lane="modal", credits=1.0, billed=0):
    return {"run_id": run_id, "lane": lane, "gpu": "L4", "seconds": 1, "usd_per_hour": 0.8, "credits_usd": credits, "billed_usd": billed}


class TestGuard(unittest.TestCase):
    def ledger(self, *rows, raw=""):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "spend.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rows) + raw)
        return path

    def ensure(self, billing=SNAKE, ledger=None, env=None, worst=WORST):
        fake = mock.Mock(return_value=mock.Mock(stdout=json.dumps(billing)))
        env = {"MODAL_LIMIT_CHECKED": MONTH} if env is None else env
        return guard.ensure(worst, ledger or self.ledger(), env, NOW, fake)

    def test_a_clean_run_passes_with_either_key_style(self):
        for billing in (SNAKE, TITLE):
            with self.subTest(billing=billing):
                self.assertEqual(self.ensure(billing), MONTH)

    def test_the_dashboard_check_must_be_this_month(self):
        for env in ({}, {"MODAL_LIMIT_CHECKED": "2026-10"}, {"MODAL_LIMIT_CHECKED": "2026-11-23"}):
            with self.subTest(env=env), self.assertRaisesRegex(guard.Refused, "MODAL_LIMIT_CHECKED"):
                self.ensure(env=env)

    def test_under_three_dollars_of_credit_refuses_and_so_does_a_worst_case_that_would_get_there(self):
        with self.assertRaisesRegex(guard.Refused, "under"):
            self.ensure({**SNAKE, "metered_cost": "27.50"})
        with self.assertRaisesRegex(guard.Refused, "worst case"):
            self.ensure({**SNAKE, "metered_cost": "26.80"})  # $3.20 left, $0.40 worst case
        self.ensure({**SNAKE, "metered_cost": "26.50"})  # $3.50 left, $3.10 after

    def test_billed_money_refuses(self):
        with self.assertRaisesRegex(guard.Refused, "bills money"):
            self.ensure({**SNAKE, "billed_cost": "0.01"})

    def test_the_month_cap_counts_this_months_modal_rows_only(self):
        with self.assertRaisesRegex(guard.Refused, "cap"):
            self.ensure(ledger=self.ledger(row(credits=14.0), row(credits=0.5, billed=0.5)))  # $15.00
        with self.assertRaisesRegex(guard.Refused, "worst case"):
            self.ensure(ledger=self.ledger(row(credits=14.7)))  # $14.70 plus $0.40
        old, other = row("2026-10-30T000000Z-smoke", credits=20.0), row(lane="actions", credits=20.0)
        self.assertEqual(self.ensure(ledger=self.ledger(old, other, row(credits=2.0))), MONTH)

    def test_anything_unreadable_refuses(self):
        for name, billing in (("list", []), ("no cost", {"Metered Cost": "1"}), ("nan", {**SNAKE, "metered_cost": "nan"}),
                              ("negative", {**SNAKE, "metered_cost": "-1"}), ("text", {**SNAKE, "metered_cost": "lots"}),
                              ("bool", {**SNAKE, "billed_cost": True})):
            with self.subTest(name), self.assertRaises(guard.Refused):
                self.ensure(billing)
        for name, led in (("missing", "/nonexistent/spend.jsonl"), ("torn line", self.ledger(raw='{"lane": "modal"')),
                          ("no month", self.ledger(row("run-1"))), ("bad number", self.ledger(row(credits="x")))):
            with self.subTest(name), self.assertRaises(guard.Refused):
                self.ensure(ledger=led)

    def test_a_failed_billing_command_refuses(self):
        for err in (subprocess.CalledProcessError(1, "modal"), subprocess.TimeoutExpired("modal", 60), FileNotFoundError()):
            with self.subTest(err=type(err).__name__), self.assertRaises(guard.Refused):
                guard.ensure(WORST, self.ledger(), {"MODAL_LIMIT_CHECKED": MONTH}, NOW, mock.Mock(side_effect=err))
        junk = mock.Mock(return_value=mock.Mock(stdout="not json"))
        with self.assertRaises(guard.Refused):
            guard.ensure(WORST, self.ledger(), {"MODAL_LIMIT_CHECKED": MONTH}, NOW, junk)


if __name__ == "__main__":
    unittest.main()
