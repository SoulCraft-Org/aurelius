"""The GEPA adapter, with no gepa and no Modal: the seat is the rule seat and Modal is faked."""

import importlib
import json
import os
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

from ladder.models import ModelSeat
from lair import load_spec
from lair.seat import RuleSeat
from train import guard

SPEC = load_spec()


class FakeSeat(RuleSeat):  # plays the rules, with the prompt attributes of ModelSeat
    def __init__(self, spec, max_calls=0):
        super().__init__(spec)
        self.system = ""


class TestGepaAdapter(unittest.TestCase):
    def setUp(self):
        fake = mock.patch.dict(sys.modules, {"modal": mock.MagicMock()})
        fake.start()
        self.addCleanup(fake.stop)
        for name in ("train.serve", "train.gepa_seat"):
            self.addCleanup(sys.modules.pop, name, None)  # they ran against the fake: never reuse them
        self.g, self.calls = importlib.import_module("train.gepa_seat"), []
        self.g.serve.LEDGER = os.path.join(self.enterContext(tempfile.TemporaryDirectory()), "spend.jsonl")
        self.g.run_gepa.remote.side_effect = lambda prompt: self.calls.append("remote") or {"best": "p", "rows": [], "gpu_seconds": 10.0}
        self.ad = self.g.SeatAdapter(SPEC, time.monotonic() + 600)

    def test_a_candidate_goes_in_and_a_reward_comes_out_with_no_truth_in_the_reflection_data(self):
        with mock.patch.object(self.g, "ModelSeat", FakeSeat):
            got = self.ad.evaluate(self.g.PARETO, {"prompt": "Go. {dial}"}, capture_traces=True)
            self.ad.evaluate(self.g.PARETO, {"prompt": "Stop."})
            self.ad.evaluate([0, 1], {"prompt": "Seen on two seeds only."})
        self.assertTrue(len(got.scores) == 8 and all(0 <= s <= 1 for s in got.scores))
        rows = self.ad.rows()  # the third candidate did not run on every PARETO seed, so it is no generation
        self.assertEqual([(r["generation"], r["seed"]) for r in rows], [(0, self.g.PARETO), (1, self.g.PARETO)])
        self.assertNotEqual(rows[0]["stamp"]["prompt"], rows[1]["stamp"]["prompt"])  # the stamp hashes the candidate
        text = json.dumps(self.ad.make_reflective_dataset({}, got, ["prompt"]))
        self.assertTrue("reward" in text and "pending" in text)
        for name in ("answer", "wrong_in", "wrong_out"):
            self.assertNotIn(f'"{name}"', text)

    def test_no_val_or_test_seed_is_reachable(self):
        for seed in (1000, 2000):
            with self.assertRaises(ValueError):
                self.ad.evaluate([0, seed], {"prompt": "x"})
        self.assertTrue(max(self.g.TRAIN + self.g.PARETO) <= SPEC["seeds"]["dev"][1])

    def test_a_refusal_stops_before_any_remote_call_and_a_pass_runs_the_guard_first_then_records_the_run(self):
        with mock.patch.object(guard, "ensure", side_effect=guard.Refused("no credit")), self.assertRaisesRegex(SystemExit, "refused: no credit"):
            self.g.main()
        self.g.run_gepa.remote.assert_not_called()
        self.assertFalse(os.path.exists(self.g.serve.LEDGER))
        with mock.patch.object(guard, "ensure", side_effect=lambda *a: self.calls.append("ensure")) as ensure:
            self.g.main()
        self.assertEqual(self.calls, ["ensure", "remote"])
        self.assertEqual(ensure.call_args.args, (guard.worst_usd(1500 + self.g.serve.BOOT_S, self.g.serve.GPU_USD_H), self.g.serve.LEDGER))
        with open(self.g.serve.LEDGER, encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read())["seconds"], 10.0 + self.g.serve.BOOT_S)

    def test_the_seed_file_is_todays_prompt_and_a_prompt_file_replaces_it(self):
        default = ModelSeat(SPEC)
        with mock.patch.dict(os.environ, {"SEAT_PROMPT_FILE": str(self.g.PROMPT)}):
            self.assertEqual((ModelSeat(SPEC).system, ModelSeat(SPEC).prompt), (default.system,) * 2)

    def test_the_reflection_input_and_the_candidate_are_capped_and_an_empty_reply_keeps_the_parent(self):
        runs = [{"seed": k, "reward": 0.5, "steps": [{"obs": "x" * 900, "actions": []}] * 50} for k in range(3)]
        got = self.ad.make_reflective_dataset({}, types.SimpleNamespace(trajectories=runs), ["prompt"])["prompt"]
        self.assertTrue(all(len(r["Generated Outputs"]) <= self.g.MAX_STEPS for r in got))
        self.assertLessEqual(len(json.dumps(got)), self.g.REFLECT_CHARS + 1000)
        for reply, want in (("", "P"), (" \n ", "P"), ("```\n \n```", "P"), ("y" * (self.g.MAX_PROMPT + 1), "P"), ("```text\nBetter {dial}\n```", "Better {dial}"), ("Plain", "Plain")):
            ad = self.g.SeatAdapter(SPEC, 0, lambda ask, reply=reply: reply)
            self.assertEqual(ad.propose_new_texts({"prompt": "P"}, {"prompt": got}, ["prompt"]), {"prompt": want})

    def test_when_optimize_raises_the_finished_generations_are_kept(self):
        def optimize(**kw):
            with mock.patch.object(self.g, "ModelSeat", FakeSeat):
                kw["adapter"].evaluate(self.g.PARETO, kw["seed_candidate"])
            raise RuntimeError("boom")
        out = self.g.evolve("Seed {dial}", self.ad, 0, optimize)
        self.assertEqual((out["best"], len(out["rows"]), out["error"]), ("Seed {dial}", 1, "RuntimeError"))
