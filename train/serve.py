"""Score the untrained seat (Qwen/Qwen3.5-9B, Apache-2.0) on Modal's monthly credit, behind the spend guard (step 25, #67).

One GPU container starts vLLM on its own localhost, scores each job with ladder.run, and ends. Commands: train/README.md.
Launch from the repo root with `python -I train/serve.py`: -I drops the repo from the path, so this file adds it.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODEL, REVISION = "Qwen/Qwen3.5-9B", "c202236235762e1c871ad0ccb60c8ee5ba337b9a"  # Hugging Face's commit, read 2026-11-23
GPU, GPU_USD_H = "L4", 0.80  # 24 GB; Modal's list price, $0.000222 a second, read 2026-11-23 (modal.com/pricing)
TIMEOUT_S, START_S, BOOT_S, PORT, HF = 1800, 900, 180, 8000, "/opt/hf"  # hard stop; wait for vLLM; cold start the ledger adds (our estimate)
LEDGER = ROOT / "ladder" / "spend.jsonl"
REQS = [x for x in (ROOT / "train" / "requirements.txt").read_text().splitlines() if x and x[0] != "#"] if modal.is_local() else []

app = modal.App("aurelius-serve")
image = (modal.Image.from_registry("nvidia/cuda:12.9.0-devel-ubuntu22.04", add_python="3.12").entrypoint([])
         .uv_pip_install(*REQS).env({"HF_HOME": HF})
         # the weights come in at build time, on CPU, so no GPU second pays for the download
         .run_commands(f"python -c \"from huggingface_hub import snapshot_download as s; s('{MODEL}', revision='{REVISION}')\"")
         .env({"HF_HUB_OFFLINE": "1"}).add_local_python_source("lair", "ladder").add_local_dir(ROOT / "spec", "/root/spec"))


def _wait(proc, t0):  # until vLLM answers /health; a dead server or the START_S limit is an error
    while time.monotonic() - t0 < START_S:
        if proc.poll() is not None:
            raise RuntimeError("vllm exited")
        try:
            if urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=5).status == 200:
                return
        except OSError:
            time.sleep(5)
    raise TimeoutError("vllm did not become healthy")


@app.function(image=image, gpu=GPU, timeout=TIMEOUT_S, max_containers=1, scaledown_window=2, single_use_containers=True)
def run_jobs(jobs):
    t0 = time.monotonic()
    os.environ.update(SEAT_URL=f"http://localhost:{PORT}/v1/chat/completions", SEAT_MODEL=MODEL, SEAT_GPU_USD_H=str(GPU_USD_H))
    cmd = ["vllm", "serve", MODEL, "--revision", REVISION, "--served-model-name", MODEL, "--host", "127.0.0.1", "--port", str(PORT),
           "--max-model-len", "16384", "--max-num-seqs", "4", "--gpu-memory-utilization", "0.90", "--language-model-only", "--enforce-eager",
           "--enable-auto-tool-choice", "--tool-call-parser", "qwen3_coder",  # the model card's parser
           "--default-chat-template-kwargs", '{"enable_thinking": false}']  # thinking is on by default and would eat the 1024-token reply
    proc, rows, error = None, [], None
    try:
        proc = subprocess.Popen(cmd)
        _wait(proc, t0)
        from ladder.run import score  # inside the container only: /root holds lair, ladder and spec
        for job in jobs:
            if time.monotonic() - t0 > TIMEOUT_S - 300:
                rows.append({"job": job, "error": "skipped: out of time"})
                continue
            os.environ["SEAT_LOCK"] = "1" if job["lock"] else "0"
            try:
                rows.append(score(job["rung"], "model", tuple(job["seeds"]), "table", job["split"]))
            except Exception as err:  # one job's failure must not cost the rest; the type only, never a body
                rows.append({"job": job, "error": type(err).__name__})
    except Exception as err:  # the GPU time was spent: return it, so the ledger records it
        error = type(err).__name__
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(30)
            except subprocess.TimeoutExpired:
                proc.kill()
    return {"rows": rows, "gpu_seconds": round(time.monotonic() - t0, 1), **({"error": error} if error else {})}


def _job(text):  # RUNG:SPLIT:SEEDS[:lock], SEEDS as 0,1,2 or 0-2
    rung, split, seeds, *lock = text.split(":")
    lo, _, hi = seeds.partition("-")
    nums = list(range(int(lo), int(hi) + 1)) if hi else [int(x) for x in seeds.split(",")]
    if rung not in ("r10", "r47") or lock not in ([], ["lock"]) or not 0 < len(nums) <= 10:
        raise ValueError(f"bad job {text!r}: rung r10 or r47, up to 10 seeds, optional :lock")
    return {"rung": rung, "split": split, "seeds": nums, "lock": bool(lock)}


def main(argv=None):
    from ladder import spend
    from ladder.run import check_split
    from lair import load_spec
    from train import guard
    p = argparse.ArgumentParser(prog="python -I train/serve.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("smoke", help="r10, dev seed 0, once, lock off")
    sub.add_parser("score", help="one or more jobs").add_argument("--job", action="append", required=True, help="RUNG:SPLIT:SEEDS[:lock]")
    args = p.parse_args(argv)
    jobs = [{"rung": "r10", "split": "dev", "seeds": [0], "lock": False}] if args.cmd == "smoke" else [_job(j) for j in args.job]
    for j in jobs:
        check_split(load_spec(), j["split"], j["seeds"])
    try:
        guard.ensure(guard.worst_usd(TIMEOUT_S, GPU_USD_H), LEDGER)
    except guard.Refused as err:
        sys.exit(f"refused: {err}")
    run_id, start, result = f"{datetime.now(timezone.utc):%Y-%m-%dT%H%M%SZ}-{args.cmd}", time.monotonic(), None
    try:
        with modal.enable_output(), app.run():
            result = run_jobs.remote(jobs)
    finally:  # a failed run is charged what the clock says, capped at the timeout: never recorded as free
        secs = result["gpu_seconds"] + BOOT_S if result else min(time.monotonic() - start, TIMEOUT_S)
        spend.append(LEDGER, spend.row(run_id, guard.LANE, GPU, round(secs, 1), GPU_USD_H, round(secs / 3600 * GPU_USD_H, 4), 0))
    print(json.dumps(result["rows"], indent=2))
    print(f"{run_id}: {secs:.0f} GPU seconds, ${secs / 3600 * GPU_USD_H:.2f} at list price, ledger row added {result.get('error', '')}", file=sys.stderr)


if __name__ == "__main__":
    main()
