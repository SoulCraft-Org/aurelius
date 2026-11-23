"""Evolve the seat prompt with GEPA (MIT) on Modal behind the spend guard (#69, refs #60); the served student (Apache-2.0) also reflects."""

import collections
import json
import os
import subprocess
import sys
import time
import types
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ladder.env import LairEnv  # noqa: E402
from ladder.models import ModelSeat, render  # noqa: E402
from ladder.run import check_split, stamp  # noqa: E402
from lair import load_spec  # noqa: E402
from train import serve  # noqa: E402  (its image, constants and vLLM wait; serve.py is not edited)

TIMEOUT_S, MAX_CALLS, WORKERS, ROUNDS, RUNG = 1500, 80, 4, 40, "r10"  # 25 minute hard stop; episodes GEPA may score; vLLM's --max-num-seqs
TRAIN, PARETO = list(range(8)), list(range(8, 16))  # dev seeds: GEPA reflects on the first, picks among candidates on the second
URL, PROMPT = f"http://localhost:{serve.PORT}/v1/chat/completions", ROOT / "spec" / "prompts" / "seat.txt"
app = modal.App("aurelius-gepa")
image = serve.image.add_local_python_source("train")


class SeatAdapter:
    """GEPA's adapter: a candidate is {"prompt": text}, a data instance a dev seed, a score the share of items right."""

    def __init__(self, spec, deadline):
        self.spec, self.deadline, self.log = spec, deadline, {}

    def evaluate(self, batch, candidate, capture_traces=False):
        check_split(self.spec, "dev", batch)  # a val or test seed never reaches the seat
        seats = [ModelSeat(self.spec, max_calls=12) for _ in batch]  # one per episode: its own cap and cache
        for seat in seats:
            seat.system = seat.prompt = render(candidate["prompt"], self.spec, seat.types)
        with ThreadPoolExecutor(WORKERS) as pool:  # vLLM batches the concurrent calls
            runs = list(pool.map(self._episode, batch, seats))
        entry = self.log.setdefault(candidate["prompt"], {"stamp": stamp(self.spec, "model", seats[0]), "by_seed": {}})
        for seed, (reward, _) in zip(batch, runs):
            entry["by_seed"].setdefault(seed, []).append(reward)
        rewards = [reward for reward, _ in runs]  # the fields of gepa's EvaluationBatch, so this file imports without gepa
        return types.SimpleNamespace(outputs=rewards, scores=rewards, trajectories=[t for _, t in runs] if capture_traces else None,
                                     objective_scores=None, num_metric_calls=None)

    def _episode(self, seed, seat):  # obs in, actions out; env.log, the truth, is never read
        env, steps = LairEnv(self.spec), []
        obs = env.reset(RUNG, seed, split="dev")
        try:
            for _ in range(ROUNDS):
                if time.monotonic() > self.deadline:
                    raise TimeoutError("out of time")
                acts = seat.decide(obs)
                steps.append({"pending": len(obs["pending"]), "replies": dict(collections.Counter(r["status"] for r in obs["replies"].values())),
                              "budget_left": obs["budget_left"]["credits"], "actions": [{**a, "children": len(a.get("children", []))} for a in acts]})
                obs, done = env.act(acts)
                if done:
                    break
        except ValueError as err:  # the Env refused the list: the episode ends as it stands
            steps.append({"refused": str(err)[:100]})
        return env.reward(), {"seed": seed, "steps": steps, "reward": env.reward()}

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        recs = [{"Inputs": {"rung": RUNG, "seed": t["seed"]}, "Generated Outputs": t["steps"],
                 "Feedback": f"reward {t['reward']:.2f} of 1, the share of items right"} for t in eval_batch.trajectories]
        return {name: recs for name in components_to_update}

    def rows(self):  # one score row per generation: each prompt GEPA tried, in order, on the dev seeds it saw
        mean = lambda e: sum(sum(r) / len(r) for r in e["by_seed"].values()) / len(e["by_seed"])
        return [{"generation": i, "split": "dev", "mean_reward": round(mean(e), 4), "stamp": e["stamp"]} for i, e in enumerate(self.log.values())]


def reflect(prompt):  # GEPA's reflection_lm: text in, text out, from the same served student
    body = json.dumps({"model": serve.MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7, "max_tokens": 1024})
    with urllib.request.urlopen(urllib.request.Request(URL, body.encode(), {"Content-Type": "application/json"}), timeout=120) as r:
        return json.load(r)["choices"][0]["message"]["content"] or ""


@app.function(image=image, gpu=serve.GPU, timeout=TIMEOUT_S, max_containers=1, scaledown_window=2, single_use_containers=True)
def run_gepa(seed_prompt):
    from gepa import optimize  # inside the container only
    t0 = time.monotonic()
    os.environ.update(SEAT_URL=URL, SEAT_MODEL=serve.MODEL, SEAT_GPU_USD_H=str(serve.GPU_USD_H), SEAT_LOCK="0")
    cmd = ["vllm", "serve", serve.MODEL, "--revision", serve.REVISION, "--served-model-name", serve.MODEL, "--host", "127.0.0.1",
           "--port", str(serve.PORT), "--max-model-len", "16384", "--max-num-seqs", str(WORKERS), "--gpu-memory-utilization", "0.90",
           "--language-model-only", "--enforce-eager", "--enable-auto-tool-choice", "--tool-call-parser", "qwen3_coder",
           "--default-chat-template-kwargs", '{"enable_thinking": false}']  # serve.run_jobs's start, which is inline there
    proc, out, error, deadline = None, {}, None, t0 + TIMEOUT_S - 300  # no episode starts past it: Modal's hard stop would drop every row
    try:
        proc = subprocess.Popen(cmd)
        serve._wait(proc, t0)
        adapter = SeatAdapter(load_spec(), deadline)
        res = optimize(seed_candidate={"prompt": seed_prompt}, trainset=TRAIN, valset=PARETO, adapter=adapter, reflection_lm=reflect,
                       max_metric_calls=MAX_CALLS, reflection_minibatch_size=3, seed=0, raise_on_exception=False,  # False: a timeout keeps the rows
                       stop_callbacks=lambda state: time.monotonic() > deadline)
        out = {"best": res.best_candidate["prompt"], "rows": adapter.rows()}
    except Exception as err:  # the GPU time was spent: return it, so the ledger records it
        error = type(err).__name__
    finally:
        if proc:
            proc.terminate()  # the container is single use and ends with this call
    return {**out, "gpu_seconds": round(time.monotonic() - t0, 1), **({"error": error} if error else {})}


def main():
    from ladder import spend
    from train import guard
    try:
        guard.ensure(guard.worst_usd(TIMEOUT_S, serve.GPU_USD_H), serve.LEDGER)
    except guard.Refused as err:
        sys.exit(f"refused: {err}")
    run_id, start, result = f"{datetime.now(timezone.utc):%Y-%m-%dT%H%M%SZ}-gepa", time.monotonic(), None
    try:
        with modal.enable_output(), app.run():
            result = run_gepa.remote(PROMPT.read_text(encoding="utf-8"))
    finally:  # a failed run is charged what the clock says, capped at the timeout: never recorded as free
        secs = result["gpu_seconds"] + serve.BOOT_S if result else min(time.monotonic() - start, TIMEOUT_S)
        spend.append(serve.LEDGER, spend.row(run_id, guard.LANE, serve.GPU, round(secs, 1), serve.GPU_USD_H, round(secs / 3600 * serve.GPU_USD_H, 4), 0))
    print(json.dumps({k: result.get(k) for k in ("best", "rows", "error")}, indent=2))


if __name__ == "__main__":
    main()
