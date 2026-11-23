"""The 8 metrics, computed from run logs (lists of Sim.log rows)."""

METRIC_IDS = (
    "verified_success",
    "cost_per_verified_success",
    "critical_steps",
    "error_growth_per_tier",
    "alarms_reaching_top",
    "fake_split_rate",
    "resume_rate",
    "budget_overruns",
)


def _rows(run_logs, kind):
    return [row for log in run_logs for row in log if row["kind"] == kind]


def _pct(part, whole):
    return None if not whole else 100.0 * part / whole


def _growth(run_logs):
    """Mean over tiers of the smoothed wrong-fact rate out over rate in.

    Report rows are pooled per tier (counts summed). Each rate adds one wrong
    fact and two facts (add-one smoothing), so zero counts never divide by zero
    and a tier that turns clean input into wrong output still scores above 1.
    """
    tiers = {}
    for r in _rows(run_logs, "report"):
        t = tiers.setdefault(r["tier"], [0, 0, 0, 0])
        for i, k in enumerate(("facts_in", "wrong_in", "facts_out", "wrong_out")):
            t[i] += r[k]
    growth = [
        ((wo + 1) / (fo + 2)) / ((wi + 1) / (fi + 2)) for fi, wi, fo, wo in tiers.values()
    ]
    return sum(growth) / len(growth) if growth else None


def _alarms(run_logs):
    planted = reached = 0
    for log in run_logs:
        tops = {r["key"] for r in log if r["kind"] == "alarm_top"}
        keys = [r["key"] for r in log if r["kind"] == "alarm_planted"]
        planted += len(keys)
        reached += sum(1 for k in keys if k in tops)
    return _pct(reached, planted)


def compute(run_logs):
    """Return {metric id: value} for a list of run logs; None when undefined."""
    finals = _rows(run_logs, "final")
    verified = sum(1 for f in finals if f["verified"])
    credits = sum(r["credits"] for r in _rows(run_logs, "spend"))
    splits = _rows(run_logs, "split")
    kills = _rows(run_logs, "kill")
    resumes = _rows(run_logs, "resume")
    steps = [f["critical_steps"] for f in finals]
    return {
        "verified_success": _pct(verified, len(finals)),
        "cost_per_verified_success": credits / verified if verified else None,
        "critical_steps": sum(steps) / len(steps) if steps else None,
        "error_growth_per_tier": _growth(run_logs),
        "alarms_reaching_top": _alarms(run_logs),
        "fake_split_rate": _pct(sum(1 for s in splits if not s["shortened"]), len(splits)),
        "resume_rate": _pct(sum(1 for r in resumes if r["same"]), len(kills)),
        "budget_overruns": len(_rows(run_logs, "overrun")),
    }
