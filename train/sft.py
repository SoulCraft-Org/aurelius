"""LoRA-tune Qwen/Qwen3.5-9B on a lessons file in a Modal Volume, behind the spend guard (step 32, #76). Commands: train/README.md.
One GPU container trains, saves the adapter, its sha256 and the config to the Volume, and ends. Launch with `python -I train/sft.py run ...`."""

import argparse, hashlib, json, math, sys, time  # noqa: E401
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import modal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODEL, REVISION = "Qwen/Qwen3.5-9B", "c202236235762e1c871ad0ccb60c8ee5ba337b9a"  # Hugging Face's commit, read 2026-11-23
GPU, GPU_USD_H = "L40S", 1.95  # 48 GB; Modal's list price, $0.000542 a second, read 2026-11-23 (modal.com/pricing)
TIMEOUT_S, BOOT_S, HF, VOL = 5400, 180, "/opt/hf", "/vol"  # hard stop; cold start the ledger adds (our estimate); weights cache; Volume mount
LEDGER = ROOT / "ladder" / "spend.jsonl"
REQS = [x for x in (ROOT / "train" / "requirements-sft.txt").read_text().splitlines() if x and x[0] != "#"] if modal.is_local() else []

app = modal.App("aurelius-sft")
volume = modal.Volume.from_name("aurelius-train", create_if_missing=True)  # holds lessons/ (step 31) and adapters/<run id>/
image = (modal.Image.from_registry("nvidia/cuda:12.9.0-devel-ubuntu22.04", add_python="3.12").entrypoint([])  # the compiler Triton needs
         .uv_pip_install(*REQS).env({"HF_HOME": HF})
         .run_commands(f"python -c \"from huggingface_hub import snapshot_download as s; s('{MODEL}', revision='{REVISION}')\"")  # on CPU, at build time
         .env({"HF_HUB_OFFLINE": "1"}))


def lora_kwargs(rank, alpha_x=1):  # peft.LoraConfig values: alpha = rank or 2 x rank (the CLI allows rank 16 or 32), every linear layer of the text model
    return {"r": rank, "lora_alpha": rank * alpha_x, "target_modules": "all-linear", "lora_dropout": 0.0, "bias": "none", "task_type": "CAUSAL_LM"}


def train_kwargs(rows, epochs=1):  # trl.SFTConfig values; loss on the completion only, as TRL does for prompt-completion rows; warmup is 3% of the steps
    return {"learning_rate": 2e-4, "bf16": True, "num_train_epochs": epochs, "per_device_train_batch_size": 1, "gradient_accumulation_steps": 16,
            "gradient_checkpointing": True, "max_length": 4096, "lr_scheduler_type": "cosine", "warmup_steps": math.ceil(0.03 * math.ceil(rows / 16) * epochs), "save_strategy": "no",
            "report_to": "none", "logging_steps": 10, "seed": 0}


def no_thinking(data):  # serving turns thinking off, so every row asks the chat template for enable_thinking=False (TRL reads this column)
    return data.map(lambda _: {"chat_template_kwargs": {"enable_thinking": False}})


def record(out, cfg):  # the adapter's sha256 goes into the config, written beside the adapter
    digest = hashlib.sha256((Path(out) / "adapter_model.safetensors").read_bytes()).hexdigest()
    info = {**cfg, "adapter_sha256": digest}
    (Path(out) / "config.json").write_text(json.dumps(info, indent=2, sort_keys=True), encoding="utf-8")
    return info


@app.function(image=image, gpu=GPU, timeout=TIMEOUT_S, max_containers=1, scaledown_window=2, single_use_containers=True, volumes={VOL: volume})
def tune(lessons, run_id, rank, alpha_x, epochs):  # lessons: a path inside the Volume; rows are {"prompt": [...], "completion": [...], "tools": [...]}
    t0, out, info, error = time.monotonic(), f"{VOL}/adapters/{run_id}", {}, None
    try:  # the GPU time was spent either way: return it, so the ledger records it
        import torch
        from datasets import load_dataset
        from peft import LoraConfig
        from transformers import AutoTokenizer, Qwen3_5ForCausalLM  # the text model alone: no vision tower to adapt, no image processor
        from trl import SFTConfig, SFTTrainer
        model, data = Qwen3_5ForCausalLM.from_pretrained(MODEL, revision=REVISION, dtype=torch.bfloat16), no_thinking(load_dataset("json", data_files=f"{VOL}/{lessons}", split="train"))
        cfg = train_kwargs(len(data), epochs)
        trainer = SFTTrainer(model=model, args=SFTConfig(output_dir=out, **cfg), peft_config=LoraConfig(**lora_kwargs(rank, alpha_x)), train_dataset=data,
                             processing_class=AutoTokenizer.from_pretrained(MODEL, revision=REVISION))
        loss = trainer.train().training_loss
        trainer.save_model(out)
        try:
            info = record(out, {"run_id": run_id, "model": MODEL, "revision": REVISION, "lessons": lessons, "gpu": GPU, "train_loss": loss,
                                "lora": lora_kwargs(rank, alpha_x), "train": cfg})
        finally:  # the adapter is saved: a failure above must not lose it
            volume.commit()
    except Exception as err:  # the type only, never a body
        error = type(err).__name__
    return {"path": f"adapters/{run_id}", "info": info, "gpu_seconds": round(time.monotonic() - t0, 1), **({"error": error} if error else {})}


def _lessons_path(text):  # an argparse type: a file under lessons/dev/, where step 31 keeps its dev-seed lessons: never val or test seeds
    p = PurePosixPath(text)
    if p.parts[:2] != ("lessons", "dev") or len(p.parts) < 3 or ".." in p.parts:
        raise argparse.ArgumentTypeError(f"not a file under lessons/dev/: {text[:40]!r}")
    return str(p)


def main(argv=None):
    from ladder import spend
    from train import guard
    p = argparse.ArgumentParser(prog="python -I train/sft.py")
    r = p.add_subparsers(dest="cmd", required=True).add_parser("run")
    r.add_argument("--lessons", type=_lessons_path, required=True, help="path inside the Volume, from step 31")
    r.add_argument("--rank", type=int, choices=(16, 32), default=16)
    r.add_argument("--alpha-x", type=int, choices=(1, 2), default=1, help="alpha = rank times this; the default alpha is the rank")
    r.add_argument("--epochs", type=int, choices=(1, 2, 3), default=1)
    args = p.parse_args(argv)
    try:
        guard.ensure(guard.worst_usd(TIMEOUT_S, GPU_USD_H), LEDGER)
    except guard.Refused as err:
        sys.exit(f"refused: {err}")
    run_id, start, result = f"{datetime.now(timezone.utc):%Y-%m-%dT%H%M%SZ}-sft", time.monotonic(), None
    try:
        with modal.enable_output(), app.run():
            result = tune.remote(args.lessons, run_id, args.rank, args.alpha_x, args.epochs)
    finally:  # a failed run is charged what the clock says, capped at the timeout: never recorded as free
        secs = result["gpu_seconds"] + BOOT_S if result else min(time.monotonic() - start, TIMEOUT_S)
        spend.append(LEDGER, spend.row(run_id, guard.LANE, GPU, round(secs, 1), GPU_USD_H, round(secs / 3600 * GPU_USD_H, 4), 0))
    print(json.dumps({"path": result["path"], "adapter_sha256": result["info"].get("adapter_sha256"), "config": result["info"]}, indent=2))
    print(f"{run_id}: {secs:.0f} GPU seconds, ${secs / 3600 * GPU_USD_H:.2f} at list price, ledger row added {result.get('error', '')}", file=sys.stderr)
    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
