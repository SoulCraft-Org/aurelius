"""Replay: rungs r10 and r47 rerun to the metrics committed in ladder/scores.json."""

import json
import unittest
from pathlib import Path

from ladder.run import score

SCORES = Path(__file__).resolve().parent.parent / "ladder" / "scores.json"
REPLAYED = ("r10", "r47")


def rows():
    # a "model" row needs the network and a key, so the replay skips it
    return [r for r in json.loads(SCORES.read_text()) if r["rung"] in REPLAYED and r["seat"] != "model"]


class TestReplay(unittest.TestCase):
    def test_both_rungs_have_all_four_seats(self):
        found = {(r["rung"], r["seat"]) for r in rows()}
        self.assertEqual(len(found), 8)
        self.assertEqual({rung for rung, _ in found}, set(REPLAYED))

    def test_metrics_match_the_committed_scores(self):
        for row in rows():
            with self.subTest(rung=row["rung"], seat=row["seat"]):
                got = score(row["rung"], row["seat"], seeds=tuple(row["seed"]))["metrics"]
                self.assertEqual(set(got), set(row["metrics"]))
                for name, want in row["metrics"].items():
                    if want is None:
                        self.assertIsNone(got[name], name)
                    else:
                        self.assertAlmostEqual(got[name], want, places=9, msg=name)


if __name__ == "__main__":
    unittest.main()
