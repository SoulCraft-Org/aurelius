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
        self.serve.run_jobs.remote.side_effect = lambda jobs: self.calls.append("remote") or {"rows": [{"ok": 1}], "gpu_seconds": 10.0}

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
        self.assertEqual(self.calls, ["ensure", "remote"])
        self.assertEqual(ensure.call_args.args, (guard.worst_usd(self.serve.TIMEOUT_S, self.serve.GPU_USD_H), self.serve.LEDGER))
        with open(self.serve.LEDGER, encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read())["seconds"], 10.0 + self.serve.BOOT_S)
