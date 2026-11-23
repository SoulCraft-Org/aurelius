"""Score the untrained seat (Qwen/Qwen3.5-9B, Apache-2.0, or MiMo-9B, MIT) or run real workers on Modal's monthly credit, behind the spend guard (steps 25, 26 and 29, #67, #68, #71).

One GPU container serves one model with vLLM on its own localhost, scores a job's seeds concurrently, runs each job, and ends. Commands: train/README.md.
Launch from the repo root with `python -I train/serve.py`: -I drops the repo from the path, so this file adds it.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lair.real_workers import BRIEFS, REAL_WORKERS  # noqa: E402  (stdlib only; needs the path line above)

MODEL, REVISION = "Qwen/Qwen3.5-9B", "c202236235762e1c871ad0ccb60c8ee5ba337b9a"  # Hugging Face's commit, read 2026-11-23
MIMO, MIMO_REVISION = "XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B", "1f09ddcc1a0ea45751ae0dfe2af20d533168c46f"  # MIT; Hugging Face's commit, read 2026-11-23. Same Qwen3.5 build, chat template and tool format as MODEL
CHOICES = {"qwen3.5-9b": MODEL, "mimo-9b": MIMO}  # --model: the scored seat
GPU, GPU_USD_H = "L4", 0.80  # 24 GB; Modal's list price, $0.000222 a second, read 2026-11-23 (modal.com/pricing)
TIMEOUT_S, START_S, BOOT_S, PORT, HF = 7200, 900, 180, 8000, "/opt/hf"  # hard stop, 2 hours: up to 100 seeds a job, several jobs a boot; wait for vLLM; cold start the ledger adds (our estimate)
WEIGHTS = {MODEL: REVISION, MIMO: MIMO_REVISION, **{w["model"]: w["revision"] for w in REAL_WORKERS.values()}}  # every model a container may serve
THREADS, MAX_SEEDS = 16, 100  # seeds scored at once, and so the sequences vLLM batches; seeds a job may carry
MAX_ITEMS, CALL_S = 200, 50  # items per workers job; seconds a model call may take: 5 calls (4 tool rounds and the answer) fit the 300 s margin
LEDGER = ROOT / "ladder" / "spend.jsonl"
REQS = [x for x in (ROOT / "train" / "requirements.txt").read_text().splitlines() if x and x[0] != "#"] if modal.is_local() else []

app = modal.App("aurelius-serve")
image = (modal.Image.from_registry("nvidia/cuda:12.9.0-devel-ubuntu22.04", add_python="3.12").entrypoint([])
         .uv_pip_install(*REQS).env({"HF_HOME": HF})
         # the weights come in at build time, on CPU, so no GPU second pays for the download
         .run_commands(*[f"python -c \"from huggingface_hub import snapshot_download as s; s('{m}', revision='{r}')\"" for m, r in WEIGHTS.items()])
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
def run_jobs(jobs, model=MODEL, threads=THREADS):  # model: one of WEIGHTS; the container serves only it
    t0, url = time.monotonic(), f"http://localhost:{PORT}/v1/chat/completions"
    os.environ.update(SEAT_URL=url, SEAT_MODEL=model, SEAT_GPU_USD_H=str(GPU_USD_H))
    cmd = ["vllm", "serve", model, "--revision", WEIGHTS[model], "--served-model-name", model, "--host", "127.0.0.1", "--port", str(PORT),
           "--max-model-len", "16384", "--max-num-seqs", str(max(4, threads)), "--gpu-memory-utilization", "0.90", "--language-model-only", "--enforce-eager",
           "--enable-auto-tool-choice", "--tool-call-parser", "qwen3_coder",  # the model card's parser
           "--default-chat-template-kwargs", '{"enable_thinking": false}']  # thinking is on by default and would eat the 1024-token reply
    proc, rows, error = None, [], None
    try:
        proc = subprocess.Popen(cmd)
        _wait(proc, t0)
        for job in jobs:
            if time.monotonic() - t0 > TIMEOUT_S - 300:
                rows.append({"job": job, "error": "skipped: out of time"})
                continue
            os.environ["SEAT_LOCK"] = "1" if job.get("lock") else "0"
            try:
                if "kind" in job:
                    rows.append(_workers(job, url, model, t0))
                else:
                    rows.extend(_score(job, threads, t0))
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


def _score(job, threads, t0):  # one row per seed, in seed order; a seed has its own seat and cap, so 100 seeds do not share one cap
    from ladder.run import score  # inside the container only: /root holds lair, ladder and spec
    deadline = t0 + TIMEOUT_S - 300  # the wait ends here: Modal's hard stop would discard every row, and a seed in flight has no clock of its own

    def one(seed):
        try:
            return score(job["rung"], "model", (seed,), "table", job["split"])
        except Exception as err:  # one seed's failure must not cost the rest; the type only, never a body
            return {"job": job, "seed": [seed], "error": type(err).__name__}
    pool = ThreadPoolExecutor(max(1, min(threads, len(job["seeds"]))))
    futures = [pool.submit(one, seed) for seed in job["seeds"]]
    wait(futures, timeout=max(0.0, deadline - time.monotonic()))
    pool.shutdown(wait=False, cancel_futures=True)  # queued seeds never start; a seed in flight is left behind, and its row is lost
    return [f.result() if f.done() and not f.cancelled() else {"job": job, "seed": [seed], "error": "skipped: out of time"} for seed, f in zip(job["seeds"], futures)]


def _workers(job, url, model, t0):  # real workers over one seeded Library: the replies, never the answers
    from lair.library import make_library  # inside the container only
    from lair.real_workers import RealWorker
    from lair.tasks import make_task
    task = make_task(job["seed"], job["size"])
    deadline = t0 + TIMEOUT_S - 300  # no call runs past it: Modal's hard stop would discard every reply
    worker = RealWorker(job["kind"], url, model, make_library(task, job["seed"], **job["library"]), timeout=CALL_S, deadline=deadline, brief=job.get("brief", "terse"))
    replies = {}
    for it in task.items:
        reply = worker(it) if time.monotonic() <= deadline else None
        if reply is None or time.monotonic() > deadline:  # an item cut short by the deadline is not a measurement
            return {"job": job, "replies": replies, "skipped": [i.key for i in task.items if i.key not in replies]}
        replies[it.key] = reply
    return {"job": job, "replies": replies}


def _within(cast, hi):  # an argparse type: a number from 0 to hi; nan fails too. A bad value exits before the guard, so no GPU is booked
    def parse(text):
        try:
            v = cast(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"not a number: {text[:20]!r}") from None
        if not 0 <= v <= hi:
            raise argparse.ArgumentTypeError(f"{text[:20]!r} is outside 0 to {hi}")
        return v
    return parse


def _job(text):  # RUNG:SPLIT:SEEDS[:lock], SEEDS as 0,1,2 or 0-2
    rung, split, seeds, *lock = text.split(":")
    lo, _, hi = seeds.partition("-")
    nums = list(range(int(lo), int(hi) + 1)) if hi else [int(x) for x in seeds.split(",")]
    if rung not in ("r10", "r47") or lock not in ([], ["lock"]) or not 0 < len(nums) <= MAX_SEEDS:
        raise ValueError(f"bad job {text!r}: rung r10 or r47, up to {MAX_SEEDS} seeds, optional :lock")
    return {"rung": rung, "split": split, "seeds": nums, "lock": bool(lock)}


def main(argv=None):
    from ladder import spend
    from ladder.run import check_split
    from lair import load_spec
    from train import guard
    p = argparse.ArgumentParser(prog="python -I train/serve.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, text in (("smoke", "r10, dev seed 0, once, lock off"), ("score", "one or more jobs sharing one boot")):
        sc = sub.add_parser(name, help=text)
        sc.add_argument("--model", choices=list(CHOICES), default="qwen3.5-9b", help="the scored seat")
        sc.add_argument("--threads", type=_within(int, 64), default=THREADS, help=f"seeds scored at once, 1 to 64 (default {THREADS})")
        if name == "score":
            sc.add_argument("--job", action="append", required=True, help="RUNG:SPLIT:SEEDS[:lock], up to 100 seeds, as 1000-1099")
    w = sub.add_parser("workers", help="real workers of one type over a seeded Library")
    w.add_argument("--kind", choices=list(REAL_WORKERS), required=True)
    w.add_argument("--seed", type=int, required=True)
    w.add_argument("--brief", choices=BRIEFS, default="terse", help="terse: the item key only; full: the order's five fields, no answer")
    w.add_argument("--split", default="dev")
    w.add_argument("--size", type=int, default=20, help=f"items, 1 to {MAX_ITEMS}")
    for knob, cast, hi, default in (("distractors", int, 10, 2), ("conflicts", float, 1, 0.3), ("noise", float, 5, 1.0)):  # ours: a Library that is not trivial
        w.add_argument(f"--{knob}", type=_within(cast, hi), default=default, help=f"0 to {hi}")
    args = p.parse_args(argv)
    model = REAL_WORKERS[args.kind]["model"] if args.cmd == "workers" else CHOICES[args.model]
    if args.cmd == "workers":
        if not 0 < args.size <= MAX_ITEMS:
            sys.exit(f"size must be 1 to {MAX_ITEMS}")
        jobs = [{"kind": args.kind, "split": args.split, "seeds": [args.seed], "seed": args.seed, "size": args.size, "brief": args.brief,
                 "library": {k: getattr(args, k) for k in ("distractors", "conflicts", "noise")}}]
    else:
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
            result = run_jobs.remote(jobs, model, max(1, getattr(args, "threads", THREADS)))
    finally:  # a failed run is charged what the clock says, capped at the timeout: never recorded as free
        secs = result["gpu_seconds"] + BOOT_S if result else min(time.monotonic() - start, TIMEOUT_S)
        spend.append(LEDGER, spend.row(run_id, guard.LANE, GPU, round(secs, 1), GPU_USD_H, round(secs / 3600 * GPU_USD_H, 4), 0))
    print(json.dumps(result["rows"], indent=2))
    print(f"{run_id}: {secs:.0f} GPU seconds, ${secs / 3600 * GPU_USD_H:.2f} at list price, ledger row added {result.get('error', '')}", file=sys.stderr)


if __name__ == "__main__":
    main()
