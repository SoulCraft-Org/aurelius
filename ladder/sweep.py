"""Step 24, move 3: sweep the rule seat's two knobs on val seeds and keep the best pair only if its gain is real.

`python3 -m ladder.sweep --out DIR` scores the grid on the first 100 val seeds of r10 and r47 and writes
DIR/rows.json (score rows) and DIR/transcripts.jsonl (obs and actions of the pair that stays, on the first
100 dev seeds, never val or test). It prints a Markdown table.
"""

import argparse
import json
import os
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from statistics import mean

from ladder.metrics import compute
from ladder.run import run_once, stamp
from ladder.stats import kept, paired_gain
from lair import load_spec
from lair.seat import RuleSeat

BARS = (0.5, 0.6, 0.7, 0.75, 0.8, 0.9)
SAMPLES = (0, 0.1, 0.2, 0.4, 0.7, 1.0)
GRID = tuple(product(BARS, SAMPLES))
DEFAULT = (0.75, 0.2)  # RuleSeat's own defaults
RUNGS = ("r10", "r47")
SEEDS = 100


def seeds(spec, split, n=SEEDS):
    """The split's first n seeds."""
    lo = spec["seeds"][split][0]
    return tuple(range(lo, lo + n))


def scored(spec, rung, pair, split, seed_list):
    """(score row, per-seed final grades) of RuleSeat(bar, sample): the one scorer, for the sweep and for replay."""
    seat = RuleSeat(spec, bar=pair[0], sample=pair[1])
    logs = [run_once(rung, "rule", spec, s, model=seat, split=split) for s in seed_list]
    grades = [r["grade"] for log in logs for r in log if r["kind"] == "final"]
    row = {"date": datetime.now(timezone.utc).date().isoformat(), "commit": os.environ.get("GITHUB_SHA", "local"),
           "rung": rung, "seat": "rule", "workers": "sim", "seed": list(seed_list), "metrics": compute(logs),
           "split": split, "rates": 0.0, "stamp": stamp(spec, "rule"),
           "params": {"bar": pair[0], "sample": pair[1]}, "grade": mean(grades)}
    return row, grades


def sweep(spec, n=SEEDS):
    """(rows, the pair that stays, kept). Best = highest mean r47 grade among pairs with no overruns on either rung."""
    val = seeds(spec, "val", n)
    got = {r: {p: scored(spec, r, p, "val", val) for p in GRID} for r in RUNGS}
    clean = [p for p in GRID if all(got[r][p][0]["metrics"]["budget_overruns"] == 0 for r in RUNGS)] or [DEFAULT]
    best = max(clean, key=lambda p: (mean(got["r47"][p][1]), p == DEFAULT))  # a tie goes to the default
    grades = {r: (got[r][DEFAULT][1], got[r][best][1]) for r in RUNGS}
    keep = all(kept(*grades[r]) for r in RUNGS)
    rows = []
    for r in RUNGS:
        gain, low, high = paired_gain(*grades[r])
        block = {"pair": {"bar": best[0], "sample": best[1]}, "gain": gain, "interval": [low, high], "kept": keep}
        rows += [{**got[r][p][0], "sweep": block} for p in GRID]
    return rows, (best if keep else DEFAULT), keep


class _Tap:
    """A seat that keeps each (obs, actions) of the first leaf run; the kill-and-resume copies are skipped."""

    def __init__(self, seat, lines, **tag):
        self.seat, self.lines, self.tag, self.done = seat, lines, tag, False

    def decide(self, obs):
        actions = self.seat.decide(obs)
        if not self.done:  # the first run ends at its report or stop
            self.lines.append(json.dumps({**self.tag, "obs": obs, "actions": actions}))
            self.done = any(a["name"] in ("report", "stop") for a in actions)
        return actions


def transcripts(spec, pair, n=SEEDS):
    """JSON lines, one per decision, on the first n dev seeds of each rung; run_once refuses val and test seeds. Each line has split and the final reward."""
    lines = []
    for rung, seed in product(RUNGS, seeds(spec, "dev", n)):
        mine = []
        tap = _Tap(RuleSeat(spec, bar=pair[0], sample=pair[1]), mine, rung=rung, seed=seed, split="dev")
        log = run_once(rung, "rule", spec, seed, model=tap, split="dev")
        reward = next(r["grade"] for r in log if r["kind"] == "final")
        lines += [json.dumps({**json.loads(line), "reward": reward}, sort_keys=True) for line in mine]
    return lines


def table(rows, chosen, keep):
    out = ["| Rung | Bar | Sample | Mean grade | Verified % | Overruns |", "|---|---|---|---|---|---|"]
    for r in rows:
        m, p = r["metrics"], r["params"]
        out.append(f"| {r['rung']} | {p['bar']} | {p['sample']} | {r['grade']:.4f} | {m['verified_success']:.1f} | {m['budget_overruns']} |")
    for r in {r["rung"]: r for r in rows}.values():
        s = r["sweep"]
        out.append(f"\n{r['rung']}: best bar {s['pair']['bar']}, sample {s['pair']['sample']}; gain over the default "
                   f"{s['gain']:+.4f}, 95% interval [{s['interval'][0]:+.4f}, {s['interval'][1]:+.4f}].")
    return "\n".join(out + [f"\nKept: {keep}. The pair that stays: bar {chosen[0]}, sample {chosen[1]}."])


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m ladder.sweep", description=__doc__.splitlines()[0])
    p.add_argument("--out", required=True, type=Path, help="directory for rows.json and transcripts.jsonl")
    p.add_argument("--seeds", type=int, default=SEEDS, help="seeds per rung: the split's first N")
    args = p.parse_args(argv)
    spec = load_spec()
    rows, chosen, keep = sweep(spec, args.seeds)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "rows.json").write_text(json.dumps(rows, indent=2) + "\n")
    (args.out / "transcripts.jsonl").write_text("\n".join(transcripts(spec, chosen, args.seeds)) + "\n")
    print(table(rows, chosen, keep))


if __name__ == "__main__":
    main()
