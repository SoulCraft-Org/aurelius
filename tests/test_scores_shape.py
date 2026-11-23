"""Every row in ladder/scores.json has one of the two documented shapes (docs/ladder.md, issue #103)."""

import json
import unittest
from pathlib import Path

from lair import load_spec

SCORES = Path(__file__).resolve().parent.parent / "ladder" / "scores.json"
OLD_COMMIT = "9d525adbd2e5f347cd18b353082217d7a5464c68"  # first scores, before #61 added split, rates and stamp
OLD_FIELDS = {"date", "commit", "rung", "seat", "workers", "seed", "metrics"}
SWEEP_EXTRA = {"params", "grade", "sweep"}


class TestScoresShape(unittest.TestCase):
    def test_every_row_has_one_of_the_two_shapes(self):
        spec = load_spec()["score_row"]
        fields = set(spec["fields"])
        for i, row in enumerate(json.loads(SCORES.read_text())):
            with self.subTest(row=i):
                keys = set(row)
                if keys == OLD_FIELDS:
                    self.assertEqual(row["commit"], OLD_COMMIT, "only the first-score rows may miss split, rates and stamp")
                else:
                    self.assertTrue(fields <= keys, f"missing {sorted(fields - keys)}")
                    self.assertTrue(keys - fields <= SWEEP_EXTRA, f"unknown {sorted(keys - fields - SWEEP_EXTRA)}")
                    self.assertEqual(sorted(row["stamp"]), sorted(spec["stamp"]))
                self.assertIn(row["workers"], spec["workers"])

    def test_the_old_shape_is_only_the_first_scores(self):
        old = [r for r in json.loads(SCORES.read_text()) if set(r) == OLD_FIELDS]
        self.assertEqual(len(old), 16)


if __name__ == "__main__":
    unittest.main()
