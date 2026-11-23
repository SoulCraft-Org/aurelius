"""Unit tests for the sweep: the grid, the keep rule, and transcripts that never hold a val or test seed."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ladder.sweep import BARS, DEFAULT, GRID, RUNGS, SAMPLES, main, scored, seeds, sweep, transcripts
from lair import load_spec

SPEC = load_spec()
X, Y = (0.6, 0.4), (0.9, 1.0)


def run_sweep(bumps, over=()):
    """The sweep with a fake scorer: every seed grades 0.5 plus the pair's bump on that rung."""
    def fake(spec, rung, pair, split, seed_list):
        return {"metrics": {"budget_overruns": int((rung, pair) in over)}}, [0.5 + bumps.get((rung, pair), 0)] * len(seed_list)
    with mock.patch("ladder.sweep.scored", fake):
        return sweep(SPEC, 4)


class SweepTest(unittest.TestCase):
    def test_the_grid_is_bar_by_sample_and_holds_the_default(self):
        self.assertEqual((BARS, SAMPLES), ((0.5, 0.6, 0.7, 0.75, 0.8, 0.9), (0, 0.1, 0.2, 0.4, 0.7, 1.0)))
        self.assertEqual((len(GRID), len(frozenset(GRID)), DEFAULT in GRID, RUNGS), (36, 36, True, ("r10", "r47")))

    def test_a_gain_on_both_rungs_is_kept(self):
        rows, chosen, keep = run_sweep({("r10", X): 0.1, ("r47", X): 0.1})
        self.assertEqual((chosen, keep, len(rows)), (X, True, 72))
        block = rows[0]["sweep"]
        self.assertEqual((block["pair"], block["kept"]), ({"bar": 0.6, "sample": 0.4}, True))
        self.assertAlmostEqual(block["gain"], 0.1)

    def test_a_gain_on_one_rung_only_keeps_the_default(self):
        rows, chosen, keep = run_sweep({("r47", X): 0.1})
        self.assertEqual((chosen, keep, rows[0]["sweep"]["kept"]), (DEFAULT, False, False))

    def test_no_gain_keeps_the_default(self):
        self.assertEqual(run_sweep({})[1:], (DEFAULT, False))

    def test_a_pair_with_an_overrun_on_either_rung_is_not_the_best(self):
        _, chosen, keep = run_sweep({("r10", X): 0.1, ("r47", X): 0.1, ("r47", Y): 0.3}, over={("r10", Y)})
        self.assertEqual((chosen, keep), (X, True))

    def test_a_row_has_the_spec_shape(self):
        row, grades = scored(SPEC, "r10", DEFAULT, "val", seeds(SPEC, "val", 2))
        self.assertEqual(list(row)[:10], SPEC["score_row"]["fields"])
        self.assertEqual((row["seat"], row["split"], row["seed"], row["params"]), ("rule", "val", [1000, 1001], {"bar": 0.75, "sample": 0.2}))
        self.assertEqual(len(grades), 2)

    def test_transcripts_hold_dev_seeds_only_and_one_run_each(self):
        lines = [json.loads(x) for x in transcripts(SPEC, DEFAULT, 2)]
        lo, hi = SPEC["seeds"]["dev"]
        self.assertTrue(all(lo <= x["seed"] <= hi and x["seed"] < 2 and set(x) == {"rung", "seed", "split", "reward", "obs", "actions"} for x in lines))
        firsts = [(x["rung"], x["seed"]) for x in lines if not x["obs"]["replies"]]
        self.assertEqual(sorted(firsts), [(r, s) for r in RUNGS for s in (0, 1)])  # a resume copy would add a second first line

    def test_a_transcript_line_has_split_rung_seed_and_the_final_reward(self):
        lines = [json.loads(x) for x in transcripts(SPEC, DEFAULT, 1)]
        self.assertTrue(lines and all(x["split"] == "dev" and x["rung"] in RUNGS and x["seed"] == 0 and 0 <= x["reward"] <= 1 for x in lines))
        self.assertEqual(len({(x["rung"], x["reward"]) for x in lines}), len(RUNGS))  # one reward per run, the same on all its lines

    def test_the_command_writes_the_rows_and_the_transcripts(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            main(["--out", tmp, "--seeds", "1"])
            self.assertEqual(len(json.loads((Path(tmp) / "rows.json").read_text())), 72)
            self.assertTrue((Path(tmp) / "transcripts.jsonl").read_text().strip())
        self.assertIn("Kept:", out.getvalue())


if __name__ == "__main__":
    unittest.main()
