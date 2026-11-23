"""The credit ledger: validation, one line per row, and the unbilled check. No network."""

import json
import os
import tempfile
import unittest

from ladder import spend

ARGS = ("run-1", "actions", "H100", 120.5, 2.99, 1.0, 0)


class TestSpend(unittest.TestCase):
    def test_a_row_has_every_field(self):
        self.assertEqual(spend.row(*ARGS), {"run_id": "run-1", "lane": "actions", "gpu": "H100", "seconds": 120.5,
                                            "usd_per_hour": 2.99, "credits_usd": 1.0, "billed_usd": 0})

    def test_a_bad_value_is_refused(self):
        for i, bad in ((3, -1), (4, -0.01), (5, -5), (6, -1), (3, float("nan")), (4, float("inf")), (3, True), (3, "9"), (0, ""), (1, None)):
            args = list(ARGS)
            args[i] = bad
            with self.subTest(i=i, bad=bad), self.assertRaises(ValueError):
                spend.row(*args)

    def test_append_writes_one_json_line_per_row_and_refuses_a_partial_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "spend.jsonl")
            spend.append(path, spend.row(*ARGS))
            spend.append(path, spend.row(*ARGS))
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
            self.assertEqual([json.loads(x) for x in lines], [spend.row(*ARGS)] * 2)
            with self.assertRaises(TypeError):
                spend.append(path, {"run_id": "x"})  # a field short: nothing is written
            with open(path, encoding="utf-8") as f:
                self.assertEqual(len(f.read().splitlines()), 2)

    def test_unbilled_catches_a_billed_row(self):
        free, paid = spend.row(*ARGS), spend.row(*ARGS[:6], 0.01)
        self.assertEqual((spend.unbilled([free, free]), spend.unbilled([free, paid]), spend.unbilled([paid])), (True, False, False))
        self.assertFalse(spend.unbilled([]))  # an empty ledger proves nothing
