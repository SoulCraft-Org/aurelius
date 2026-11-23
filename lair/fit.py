"""Fit worker rates from real replies (step 30, #72). Stdlib only.

A record is {"kind", "brief", "reply", "answer"}: one real-worker reply and its item's true answer. Each rate is
grouped by worker type and brief, and carries its count and a 95% interval (Wilson for shares, normal for seconds).
"""

import math
from datetime import datetime, timezone

Z = 1.96  # 95%


def _share(hits, n):
    """A share with its Wilson interval; None when n is 0."""
    if n == 0:
        return {"value": None, "n": 0, "lo": None, "hi": None}
    p, d = hits / n, 1 + Z * Z / n
    mid, half = (p + Z * Z / (2 * n)) / d, Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return {"value": p, "n": n, "lo": max(0.0, mid - half), "hi": min(1.0, mid + half)}


def _mean(xs):
    """A mean with its normal interval; the interval needs two values."""
    n = len(xs)
    if n == 0:
        return {"value": None, "n": 0, "lo": None, "hi": None}
    m = sum(xs) / n
    if n < 2:
        return {"value": m, "n": n, "lo": None, "hi": None}
    half = Z * math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1) / n)
    return {"value": m, "n": n, "lo": m - half, "hi": m + half}


def _right(reply, answer):
    return any(f["value"] == answer for f in reply["facts"][:1])


def fit(records):
    """Return {kind: {brief: {skill, crash, seconds, seen_precision}}}. Refuses an empty list."""
    if not records:
        raise ValueError("no replies to fit")
    groups = {}
    for r in records:
        groups.setdefault((r["kind"], r["brief"]), []).append(r)
    out = {}
    for (kind, brief), rs in sorted(groups.items()):
        done = [r for r in rs if r["reply"]["status"] == "completed"]
        seen = [r for r in done if r["reply"]["facts"] and r["reply"]["facts"][0]["tag"] == "seen"]
        out.setdefault(kind, {})[brief] = {
            "skill": _share(sum(_right(r["reply"], r["answer"]) for r in done), len(done)),
            "crash": _share(len(rs) - len(done), len(rs)),
            "seconds": _mean([r["reply"]["spent"]["seconds"] for r in rs]),
            "seen_precision": _share(sum(_right(r["reply"], r["answer"]) for r in seen), len(seen)),
        }
    return out


def as_spec(fitted, spec, brief, date=None):
    """The spec's worker_types, with skill and seconds replaced by the fitted values for one brief, labelled fitted with the date.

    A type with no fit for that brief keeps its entry. Refuses a brief that no type has.
    """
    if not any(brief in by for by in fitted.values()):
        raise ValueError(f"no fit for brief {brief!r}")
    date = date or datetime.now(timezone.utc).date().isoformat()
    out = []
    for t in spec["worker_types"]:
        f = fitted.get(t["id"], {}).get(brief)
        if f and f["skill"]["value"] is not None and f["seconds"]["value"] is not None:
            t = {**t, "skill": round(f["skill"]["value"], 4), "seconds": round(f["seconds"]["value"], 3), "source": f"fitted {date}, brief {brief}"}
        out.append(t)
    return out
