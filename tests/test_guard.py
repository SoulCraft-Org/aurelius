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
REAL = {"metered_cost": "69.60802096", "billed_cost": "0E-8", "adjustments": {"credits": "-14.46000000"}}  # the shape modal prints
SNAKE = {**REAL, "adjustments": {"credits": "-5.00"}}
TITLE = {"Metered Cost": "$69.60", "Billed Cost": "$0.00", "Adjustments": {"Credits": "-$5.00"}}


used = lambda x: {**SNAKE, "adjustments": {"credits": x}}


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
        fake = self.fake = mock.Mock(return_value=mock.Mock(stdout=json.dumps(billing)))
        env = {"MODAL_LIMIT_CHECKED": MONTH} if env is None else env
        return guard.ensure(worst, ledger or self.ledger(), env, NOW, fake)

    def test_a_clean_run_passes_with_either_key_style_and_the_real_shape(self):
        for billing in (SNAKE, TITLE, REAL):
            with self.subTest(billing=billing):
                self.assertEqual(self.ensure(billing), MONTH)
        self.assertEqual(guard.credit_left(REAL), 30 - 14.46)  # gross metered_cost is not read
        self.assertEqual(self.fake.call_args.args[0][-3:], ["--for", MONTH, "--json"])  # the ledger's month

    def test_a_bad_worst_case_refuses(self):
        for bad in (float("nan"), float("inf"), -0.4, 0, None, True, "0.4"):
            with self.subTest(bad=bad), self.assertRaisesRegex(guard.Refused, "worst case"):
                self.ensure(worst=bad)

    def test_the_dashboard_check_must_be_this_month(self):
        for env in ({}, {"MODAL_LIMIT_CHECKED": "2026-10"}, {"MODAL_LIMIT_CHECKED": "2026-11-23"}):
            with self.subTest(env=env), self.assertRaisesRegex(guard.Refused, "MODAL_LIMIT_CHECKED"):
                self.ensure(env=env)

    def test_under_three_dollars_of_credit_refuses_and_so_does_a_worst_case_that_would_get_there(self):
        with self.assertRaisesRegex(guard.Refused, "under"):
            self.ensure(used("-27.50"))
        with self.assertRaisesRegex(guard.Refused, "worst case"):
            self.ensure(used("-26.80"))  # $3.20 left, $0.40 worst case
        self.ensure(used("-26.50"))  # $3.50 left, $3.10 after

    def test_billed_money_refuses(self):
        for billed in ("0.01", "$0.01", 0.01):
            with self.subTest(billed=billed), self.assertRaisesRegex(guard.Refused, "bills money"):
                self.ensure({**SNAKE, "billed_cost": billed})

    def test_the_month_cap_counts_this_months_modal_rows_only(self):
        with self.assertRaisesRegex(guard.Refused, "cap"):
            self.ensure(ledger=self.ledger(row(credits=14.0), row(credits=0.5, billed=0.5)))  # $15.00
        with self.assertRaisesRegex(guard.Refused, "worst case"):
            self.ensure(ledger=self.ledger(row(credits=14.7)))  # $14.70 plus $0.40
        old, other = row("2026-10-30T000000Z-smoke", credits=20.0), row(lane="actions", credits=20.0)
        self.assertEqual(self.ensure(ledger=self.ledger(old, other, row(credits=2.0))), MONTH)

    def test_anything_unreadable_refuses(self):
        for name, billing in (("list", []), ("no billed", {"adjustments": {"credits": "-1"}}), ("no adjustments", {"billed_cost": "0"}),
                              ("no credits", {**SNAKE, "adjustments": {}}), ("adjustments text", {**SNAKE, "adjustments": "x"}),
                              ("nan", used("nan")), ("inf", used("-Infinity")), ("text", used("lots")), ("bool", used(True)),
                              ("billed bool", {**SNAKE, "billed_cost": True}), ("billed text", {**SNAKE, "billed_cost": "lots"})):
            with self.subTest(name), self.assertRaises(guard.Refused):
                self.ensure(billing)
        for name, led in (("missing", "/nonexistent/spend.jsonl"), ("torn line", self.ledger(raw='{"lane": "modal"')),
                          ("no month", self.ledger(row("run-1"))), ("bad number", self.ledger(row(credits="x")))):
            with self.subTest(name), self.assertRaises(guard.Refused):
                self.ensure(ledger=led)

    def test_a_failed_billing_command_refuses(self):
        errors = (subprocess.CalledProcessError(1, "modal"), subprocess.TimeoutExpired("modal", 60), FileNotFoundError())
        for run in (*(mock.Mock(side_effect=e) for e in errors), mock.Mock(return_value=mock.Mock(stdout="not json"))):
            with self.assertRaises(guard.Refused):
                guard.ensure(WORST, self.ledger(), {"MODAL_LIMIT_CHECKED": MONTH}, NOW, run)

