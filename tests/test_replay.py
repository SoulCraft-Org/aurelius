"""Replay: rungs r10 and r47 rerun to the metrics committed in ladder/scores.json."""

import json
import unittest
from pathlib import Path

from ladder.run import score
from ladder.sweep import GRID, RUNGS, scored
from lair import load_spec

SCORES = Path(__file__).resolve().parent.parent / "ladder" / "scores.json"
REPLAYED = ("r10", "r47")


def all_rows():
    return [r for r in json.loads(SCORES.read_text()) if r["rung"] in REPLAYED and r["seat"] != "model"]  # model rows need the network


def rows():
    return [r for r in all_rows() if "params" not in r]


def swept():
    return [r for r in all_rows() if "params" in r]


class TestReplay(unittest.TestCase):
    def match(self, got, want):
        self.assertEqual(set(got), set(want))
        for name, value in want.items():
            if value is None:
                self.assertIsNone(got[name], name)
            else:
                self.assertAlmostEqual(got[name], value, places=9, msg=name)

    def test_both_rungs_have_all_four_seats(self):
        found = {(r["rung"], r["seat"]) for r in rows()}
        self.assertEqual(len(found), 8)
        self.assertEqual({rung for rung, _ in found}, set(REPLAYED))

    def test_metrics_match_the_committed_scores(self):
        for row in rows():
            with self.subTest(rung=row["rung"], seat=row["seat"]):
                self.match(score(row["rung"], row["seat"], seeds=tuple(row["seed"]))["metrics"], row["metrics"])

    def test_sweep_rows_cover_the_grid_on_both_rungs(self):
        self.assertEqual(sorted((r["rung"], r["params"]["bar"], r["params"]["sample"]) for r in swept()),
                         sorted((rung, *pair) for rung in RUNGS for pair in GRID))

    def test_sweep_rows_replay_on_their_own_split_and_seeds(self):
        spec = load_spec()
        for row in swept():
            with self.subTest(rung=row["rung"], params=row["params"]):
                got, _ = scored(spec, row["rung"], (row["params"]["bar"], row["params"]["sample"]), row["split"], tuple(row["seed"]))
                self.assertEqual((row["split"], row["seat"]), ("val", "rule"))
                self.match({**got["metrics"], "grade": got["grade"]}, {**row["metrics"], "grade": row["grade"]})


if __name__ == "__main__":
    unittest.main()
