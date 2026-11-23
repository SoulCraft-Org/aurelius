#!/usr/bin/env python3
"""make_run_svg.py: one run log as docs/img/run.svg, the 4D tree. Stdlib only, no randomness.

The seat sits on top and its workers fan out below. Over about 12 seconds the log plays: the seat maps,
replies arrive (worker colour by credits spent), checks pass (green ring) or fail (red), the report goes up.
Time is the fourth dimension. CSS keyframes only: no script, no outside link; a still under reduced motion.
Usage: python3 -I tools/make_run_svg.py [--check]   (--check exits 1 when the committed file differs)
"""
import math
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RUNG, SEED, BAR, SAMPLE = "r47", 0, 0.5, 1.0
W, H, SEAT, R, ARC = 960, 420, (480, 60), 270, 70
CYCLE, RUN = 16, 12  # seconds: the whole loop, and the part that plays the log
# Every colour clears 3:1 on white and on #0d1117 (GitHub shows the SVG on either); text sits on a dark chip.
COST = [(1, "#9A82F5", "1 credit"), (2, "#7C5FE0", "2 to 5"), (6, "#6A4FD8", "6 or more")]
IDLE, RED, GREEN = "none", "#E5484D", "#2EA66B"
OUT = ROOT / "docs" / "img" / "run.svg"


def calls(log):
    """Each worker call, in log order, as {key, credits, done, verdict, n}: done is when the reply is in,
    verdict the check of that reply (None when none came), n the key's calls so far. A call row names no
    key, so the keys come from what the seat does: it sends every key once, then sends again the keys whose
    check failed and the keys that never answered, sorted. Raises ValueError when a log does not fit that."""
    rows = [r for r in log if r["kind"] in ("spend", "check")]
    call = lambda r: r["kind"] == "spend" and r["seconds"] > 0
    last, out, i = {}, [], 0
    while i < len(rows):
        r = rows[i]
        if r["kind"] == "check":
            last[r["key"]]["verdict"] = r["verdict"]
        if not call(r):
            i += 1
            continue
        j = i
        while j < len(rows) and call(rows[j]) and rows[j]["t"] == r["t"]:
            j += 1
        k = j  # the checks that follow in this step answer keys that did reply
        while k < len(rows) and not call(rows[k]):
            k += 1
        replied = {x["key"] for x in rows[j:k] if x["kind"] == "check"}
        group = rows[i:j]
        if not last:
            pool = [f"k{x}" for x in range(len(group))]
        else:  # a key that never answered has no verdict and no check coming
            pool = [key for key, v in last.items() if v["verdict"] is False or (
                v["verdict"] is None and v["done"] <= r["t"] and key not in replied)]
        if len(pool) != len(group):
            raise ValueError("the log does not fit the seat's order")
        tries = lambda q: last[q]["n"] if q in last else 0
        # the keys on their third call go up a type, so they take the dearest calls
        for key, row in zip(sorted(pool, key=lambda q: (-tries(q), q)), sorted(group, key=lambda x: -x["credits"])):
            last[key] = {"key": key, "credits": row["credits"], "n": tries(key) + 1, "verdict": None,
                         "done": r["t"] + row["seconds"]}
            out.append(last[key])
        i = j
    return out


def states(log):
    """{key: [(done, fill, stroke)]}: each worker's look from the moment a reply lands and its check says."""
    spent, look = defaultdict(int), defaultdict(list)
    for c in calls(log):
        spent[c["key"]] += c["credits"]
        bad = c["verdict"] is False
        fill = next(col for n, col, _ in reversed(COST) if spent[c["key"]] >= n)
        look[c["key"]].append((c["done"], RED if bad else fill, RED if bad else GREEN if c["verdict"] else IDLE))
    return look


def _pct(t, end):
    return round(100 * RUN / CYCLE * t / end, 2)


def render(log):
    look, end = states(log), max(r["t"] for r in log)
    report = next(r for r in log if r["kind"] == "report")
    n = len(look)
    xy = [(SEAT[0] + R * math.sin(math.radians(ARC * (2 * i / (n - 1) - 1))),
           SEAT[1] + R * math.cos(math.radians(ARC * (2 * i / (n - 1) - 1)))) for i in range(n)]
    css, body = [], []
    for i, (x, y) in enumerate(xy):
        steps = look[f"k{i}"]
        final = steps[-1]
        frames = "0%{fill:none;stroke:#8B949E}" + "".join(
            f"{_pct(t, end)}%{{fill:{f};stroke:{s if s != IDLE else '#8B949E'}}}" for t, f, s in steps) + "97%{fill:none;stroke:#8B949E}"
        css.append(f".w{i}{{animation:a{i} {CYCLE}s step-end infinite}}@keyframes a{i}{{{frames}}}")
        body.append(f'<line class="l" x1="{SEAT[0]}" y1="{SEAT[1]}" x2="{x:.1f}" y2="{y:.1f}"/>')
        body.append(f'<circle class="w{i}" cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{final[1]}" '
                    f'stroke="{final[2] if final[2] != IDLE else "#8B949E"}" stroke-width="2"/>')
    legend = [f'<circle cx="{40 + 130 * j}" cy="358" r="6" fill="{c}" stroke="#8B949E" stroke-width="2"/>'
              f'<text x="{52 + 130 * j}" y="363">{label}</text>' for j, (_, c, label) in enumerate(COST)]
    legend += [f'<circle cx="430" cy="358" r="6" fill="{RED}" stroke="{RED}" stroke-width="2"/><text x="442" y="363">wrong fact caught</text>',
               f'<circle cx="610" cy="358" r="6" fill="none" stroke="{GREEN}" stroke-width="2"/><text x="622" y="363">check passed</text>']
    caption = f"sim run, rule seat, dev seed {SEED}"
    note = (f"{RUNG}, bar {BAR}, sample {SAMPLE}: {report['facts_in']} facts in, {report['wrong_in']} wrong; "
            f"{report['facts_out']} out, {report['wrong_out']} wrong after checks; sim time 0 to {end:g} s")
    title = f"Aurelius {RUNG} sim run: one seat maps {n} workers, replies arrive, checks pass or fail, the report goes up"
    head = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="{title}">'
    style = (".l{stroke:#8B949E;stroke-width:1;opacity:.5;animation:ln %ds linear infinite}"
             "@keyframes ln{0%%{opacity:0}2%%{opacity:.5}97%%{opacity:.5}100%%{opacity:0}}"
             ".s{fill:#B8860B}.p{fill:none;stroke:#B8860B;stroke-width:3;opacity:0;transform-origin:%dpx %dpx;"
             "animation:rg %ds ease-out infinite}"
             "@keyframes rg{0%%,%s%%{opacity:0;transform:scale(1)}%s%%{opacity:1}%s%%{opacity:0;transform:scale(2.2)}100%%{opacity:0}}"
             ".c{fill:#7C5FE0;transform-origin:40px 0;animation:cl %ds linear infinite}"
             "@keyframes cl{0%%{transform:scaleX(0)}%s%%,100%%{transform:scaleX(1)}}"
             'text{font:600 13px system-ui,-apple-system,"Segoe UI",sans-serif;fill:#E6EDF3}text.m{font-weight:400}'
             ".k{fill:#0d1117;stroke:#8B949E}"
             "@media (prefers-reduced-motion:reduce){*{animation:none!important}.p{opacity:0}}"
             % (CYCLE, SEAT[0], SEAT[1], CYCLE, _pct(end, end) - 0.01, _pct(end, end), _pct(end, end) + 6,
                CYCLE, _pct(end, end)))
    parts = [head, f"<title>{title}</title>", f"<style>{style}{''.join(css)}</style>", *body,
             f'<circle class="s" cx="{SEAT[0]}" cy="{SEAT[1]}" r="16"/>',
             f'<circle class="p" cx="{SEAT[0]}" cy="{SEAT[1]}" r="16"/>',
             f'<rect class="c" x="40" y="378" width="880" height="3"/>',
             '<rect class="k" x="24" y="344" width="912" height="28" rx="6"/>', *legend,
             '<rect class="k" x="24" y="12" width="300" height="28" rx="6"/><rect class="k" x="24" y="386" width="912" height="26" rx="6"/>',
             f'<text x="38" y="31">{caption}</text>', f'<text class="m" x="38" y="403">{note}</text>', "</svg>"]
    return "\n".join(parts) + "\n"


def build():
    from ladder.run import run_once
    from lair import load_spec
    from lair.seat import RuleSeat
    spec = load_spec()
    return render(run_once(RUNG, "rule", spec, SEED, model=RuleSeat(spec, bar=BAR, sample=SAMPLE)))


def main():
    text = build()
    if "--check" in sys.argv[1:]:
        return 0 if OUT.exists() and OUT.read_text() == text else 1
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(text.encode())} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
