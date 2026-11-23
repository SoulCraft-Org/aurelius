import argparse, contextlib, hashlib, importlib, io, json, os, pathlib, sys, tempfile, types, unittest  # noqa: E401
from unittest import mock

from train import guard


class TestSftConfig(unittest.TestCase):
    def setUp(self):
        fake = mock.patch.dict(sys.modules, {"modal": mock.MagicMock()})
        fake.start()
        self.addCleanup(fake.stop)
        self.addCleanup(sys.modules.pop, "train.sft", None)  # it ran against the fake: never reuse it
        self.sft = importlib.import_module("train.sft")
        self.dir, self.calls = self.enterContext(tempfile.TemporaryDirectory()), []
        self.sft.LEDGER = os.path.join(self.dir, "spend.jsonl")
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        self.sft.tune.remote.side_effect = lambda *a: self.calls.append(("remote", a)) or {"path": "adapters/x", "info": {}, "gpu_seconds": 10.0}

    def test_lora_values(self):
        k = self.sft.lora_kwargs(16)
        self.assertEqual((k["r"], k["lora_alpha"], k["target_modules"], k["lora_dropout"], k["task_type"]), (16, 16, "all-linear", 0.0, "CAUSAL_LM"))
        self.assertEqual(self.sft.lora_kwargs(32, 2)["lora_alpha"], 64)
        t = self.sft.train_kwargs(1000)
        self.assertEqual((t["learning_rate"], t["bf16"], t["num_train_epochs"], t["warmup_steps"]), (2e-4, True, 1, 2))  # ceil(0.03 x 63 steps)

    def test_every_row_turns_thinking_off(self):
        rows = [{"prompt": 1}, {"prompt": 2}]
        out = self.sft.no_thinking(types.SimpleNamespace(map=lambda f: [{**r, **f(r)} for r in rows]))
        self.assertEqual([r["chat_template_kwargs"] for r in out], [{"enable_thinking": False}] * 2)

    def test_only_lessons_under_dev_are_read_and_a_bad_path_exits_before_the_guard(self):
        self.assertEqual(self.sft._lessons_path("lessons/dev/v1.jsonl"), "lessons/dev/v1.jsonl")
        for bad in ("/etc/passwd", "lessons/val/v1.jsonl", "lessons/dev", "lessons/dev/../val/x", "dev/lessons/x", ""):
            with self.subTest(bad), self.assertRaises(argparse.ArgumentTypeError):
                self.sft._lessons_path(bad)
        with mock.patch.object(guard, "ensure") as ensure, self.assertRaises(SystemExit):
            self.sft.main(["run", "--lessons", "lessons/test/x.jsonl"])
        ensure.assert_not_called()

    def test_a_refusal_stops_before_any_remote_call_or_ledger_row(self):
        with mock.patch.object(guard, "ensure", side_effect=guard.Refused("no credit")), self.assertRaisesRegex(SystemExit, "refused: no credit"):
            self.sft.main(["run", "--lessons", "lessons/dev/v1.jsonl"])
        self.sft.tune.remote.assert_not_called()
        self.sft.app.run.assert_not_called()
        self.assertFalse(os.path.exists(self.sft.LEDGER))

    def test_a_pass_runs_the_guard_first_with_the_worst_case_then_records_the_run(self):
        ensure = mock.Mock(side_effect=lambda *a: self.calls.append("ensure"))
        with mock.patch.object(guard, "ensure", ensure):
            self.sft.main(["run", "--lessons", "lessons/dev/v1.jsonl", "--rank", "32", "--alpha-x", "2"])
        self.assertEqual(ensure.call_args.args, (guard.worst_usd(self.sft.TIMEOUT_S, self.sft.GPU_USD_H), self.sft.LEDGER))
        self.assertEqual((self.calls[0], self.calls[1][1][0], self.calls[1][1][2:]), ("ensure", "lessons/dev/v1.jsonl", (32, 2, 1)))
        with open(self.sft.LEDGER, encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read())["seconds"], 10.0 + self.sft.BOOT_S)

    def test_a_failure_still_adds_a_ledger_row_and_an_error_from_tune_exits_non_zero_after_it(self):
        for effect, seconds in ((RuntimeError("boom"), None), (lambda *a: {"path": "p", "info": {}, "gpu_seconds": 5.0, "error": "OSError"}, 5.0 + self.sft.BOOT_S)):
            self.sft.tune.remote.side_effect = effect
            with self.subTest(effect), mock.patch.object(guard, "ensure"), self.assertRaises((RuntimeError, SystemExit)):
                self.sft.main(["run", "--lessons", "lessons/dev/v1.jsonl"])
            with open(self.sft.LEDGER, encoding="utf-8") as f:
                row = json.loads(f.read().splitlines()[-1])
            self.assertEqual((row["gpu"], seconds in (None, row["seconds"])), (self.sft.GPU, True))

    def test_the_adapter_hash_is_recorded_beside_the_adapter(self):
        data = b"adapter bytes"
        pathlib.Path(self.dir, "adapter_model.safetensors").write_bytes(data)
        info = self.sft.record(self.dir, {"run_id": "r"})
        self.assertEqual(info["adapter_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(json.loads(pathlib.Path(self.dir, "config.json").read_text()), info)
