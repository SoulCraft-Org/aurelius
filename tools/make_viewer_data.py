#!/usr/bin/env python3
"""make_viewer_data.py: one run log as docs/viewer/run.json for the 5D viewer. Stdlib only, no randomness.

Node 0 is the seat, nodes 1 to 47 the workers, on a bowl under it (golden-angle spiral, x y z in about -1 to 1).
Events are in time order: the seat maps at 0, each worker reply lands at its done time (cost in credits, wrong
when its check failed), the report goes up. Same log as docs/img/run.svg: the swept rule seat on r47, dev seed 0.
Usage: python3 -I tools/make_viewer_data.py [--check]   (--check exits 1 when the committed file differs)
"""
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import make_run_svg as run_svg  # noqa: E402

OUT = ROOT / "docs" / "viewer" / "run.json"
GOLD = math.pi * (3 - 5 ** 0.5)


def render(log):
    done = run_svg.calls(log)
    report = next(r for r in log if r["kind"] == "report")
    n = len({c["key"] for c in done})
    nodes = [{"id": 0, "kind": "seat", "x": 0.0, "y": 0.9, "z": 0.0}]
    for i in range(n):
        r, a = math.sqrt((i + 0.5) / n), i * GOLD
        nodes.append({"id": i + 1, "kind": "worker", "x": round(r * math.cos(a), 3),
                      "y": round(-0.3 - 0.5 * r * r, 3), "z": round(r * math.sin(a), 3)})
    events = [{"t": 0.0, "node": 0, "kind": "map", "cost": 0, "wrong": False}]
    events += [{"t": c["done"], "node": int(c["key"][1:]) + 1, "kind": "reply", "cost": c["credits"],
                "wrong": c["verdict"] is False} for c in done]
    events.append({"t": report["t"], "node": 0, "kind": "report", "cost": 0, "wrong": False})
    events.sort(key=lambda e: (e["t"], e["node"], e["kind"]))
    meta = {"label": "sim", "rung": run_svg.RUNG, "seat": "rule", "seed": run_svg.SEED, "bar": run_svg.BAR,
            "sample": run_svg.SAMPLE, "end": max(e["t"] for e in events), "facts_in": report["facts_in"],
            "wrong_in": report["wrong_in"], "wrong_out": report["wrong_out"]}
    rows = ",\n".join(json.dumps(e, separators=(",", ":")) for e in events)
    head = json.dumps({"meta": meta, "nodes": nodes}, separators=(",", ":"))
    return head[:-1] + ',"events":[\n' + rows + "\n]}\n"


def build():
    from ladder.run import run_once
    from lair import load_spec
    from lair.seat import RuleSeat
    spec = load_spec()
    return render(run_once(run_svg.RUNG, "rule", spec, run_svg.SEED,
                           model=RuleSeat(spec, bar=run_svg.BAR, sample=run_svg.SAMPLE)))


def main(argv):
    text = build()
    if "--check" in argv:
        return 0 if OUT.exists() and OUT.read_text() == text else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(text.encode())} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
