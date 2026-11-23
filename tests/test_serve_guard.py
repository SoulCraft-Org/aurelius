"""serve.main() runs the guard before any remote call and stops when it refuses. Modal is faked: nothing leaves the machine."""

import contextlib
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from train import guard


class TestServeGuard(unittest.TestCase):
    def setUp(self):
        fake = mock.patch.dict(sys.modules, {"modal": mock.MagicMock()})
        fake.start()
        self.addCleanup(fake.stop)
        self.addCleanup(sys.modules.pop, "train.serve", None)  # it ran against the fake: never reuse it
        self.serve = importlib.import_module("train.serve")
        self.serve.LEDGER, self.calls = os.path.join(self.enterContext(tempfile.TemporaryDirectory()), "spend.jsonl"), []
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        self.serve.run_jobs.remote.side_effect = lambda jobs, model=None: self.calls.append(("remote", model)) or {"rows": [{"ok": 1}], "gpu_seconds": 10.0}

    def test_a_refusal_stops_before_any_remote_call_or_ledger_row(self):
        with mock.patch.object(guard, "ensure", side_effect=guard.Refused("no credit")), self.assertRaisesRegex(SystemExit, "refused: no credit"):
            self.serve.main(["smoke"])
        self.serve.run_jobs.remote.assert_not_called()
        self.serve.app.run.assert_not_called()
        self.assertFalse(os.path.exists(self.serve.LEDGER))

    def test_a_pass_runs_the_guard_first_with_the_worst_case_then_records_the_run(self):
        ensure = mock.Mock(side_effect=lambda *a: self.calls.append("ensure"))
        with mock.patch.object(guard, "ensure", ensure):
            self.serve.main(["smoke"])
        self.assertEqual(self.calls, ["ensure", ("remote", self.serve.MODEL)])
        self.assertEqual(ensure.call_args.args, (guard.worst_usd(self.serve.TIMEOUT_S, self.serve.GPU_USD_H), self.serve.LEDGER))
        with open(self.serve.LEDGER, encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read())["seconds"], 10.0 + self.serve.BOOT_S)

    def test_workers_serve_the_models_of_their_kind_guard_first_and_record_the_run(self):
        ensure = mock.Mock(side_effect=lambda *a: self.calls.append("ensure"))
        with mock.patch.object(guard, "ensure", ensure):
            self.serve.main(["workers", "--kind", "small", "--seed", "0"])
        self.assertEqual(self.calls, ["ensure", ("remote", "Qwen/Qwen3.5-2B")])
        job = self.serve.run_jobs.remote.call_args.args[0][0]
        self.assertEqual((job["kind"], job["seed"], job["size"]), ("small", 0, 20))
        with open(self.serve.LEDGER, encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read())["seconds"], 10.0 + self.serve.BOOT_S)
        with self.assertRaises(ValueError):  # a seed outside the dev split is refused before the guard
            self.serve.main(["workers", "--kind", "small", "--seed", "1000"])

    def test_workers_knobs_outside_their_bounds_exit_before_the_guard(self):
        with mock.patch.object(guard, "ensure") as ensure:
            for flag, bad in (("--distractors", "11"), ("--noise", "5.5"), ("--conflicts", "1.5"), ("--noise", "nan"), ("--distractors", "-1")):
                with self.subTest(flag, bad=bad), self.assertRaises(SystemExit):
                    self.serve.main(["workers", "--kind", "small", "--seed", "0", flag, bad])
        ensure.assert_not_called()
        self.serve.run_jobs.remote.assert_not_called()

    def test_the_deadline_returns_the_replies_so_far_and_each_call_fits_the_margin(self):
        clock, made = {"t": 0.0}, {}

        class Fake:  # each item takes 500 s of a fake clock; the deadline is TIMEOUT_S - 300 = 1500
            def __init__(self, *args, **kw):
                made.update(kw)

            def __call__(self, item):
                clock["t"] += 500
                return {"status": "completed", "facts": [], "alarms": [], "spent": {}}

        job = {"kind": "small", "seed": 0, "size": 5, "library": {"distractors": 0, "conflicts": 0.0, "noise": 0.0}}
        with mock.patch("lair.real_workers.RealWorker", Fake), mock.patch.object(self.serve.time, "monotonic", lambda: clock["t"]):
            out = self.serve._workers(job, "http://localhost:8000/v1", "m", 0.0)
        self.assertEqual((sorted(out["replies"]), out["skipped"]), (["k0", "k1", "k2"], ["k3", "k4"]))  # k3 ended at 2000, past 1500: dropped
        self.assertLessEqual(5 * made["timeout"], 300)
        self.assertEqual(made["deadline"], self.serve.TIMEOUT_S - 300)
