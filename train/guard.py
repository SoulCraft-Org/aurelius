"""The spend guard for a Modal run. Stdlib only, no Modal import. It refuses on any doubt: unreadable input is a refusal."""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

CREDIT_USD, FLOOR_USD, MONTH_CAP_USD = 30.0, 3.0, 15.0  # Modal's monthly credit, the least we leave, and our cap for Aurelius per month
LANE = "modal"  # the ledger lane of a Modal run; its run_id starts with the UTC date, so a row knows its month


class Refused(Exception):
    """The guard says no; the message says why."""


def worst_usd(timeout_s, usd_per_hour):
    """The most one container can cost: its hard timeout at the list price."""
    return timeout_s / 3600 * usd_per_hour


def _usd(x):  # "12.5", "$1,200.50" or a number; refuses nan, inf, a negative and a bool
    try:
        v = Decimal(str(x).strip().replace("$", "").replace(",", ""))
    except InvalidOperation:
        raise Refused(f"not a dollar amount: {str(x)[:20]!r}") from None
    if isinstance(x, bool) or not v.is_finite() or v < 0:
        raise Refused(f"not a dollar amount: {str(x)[:20]!r}")
    return float(v)


def read_billing(run=subprocess.run):
    """`modal billing summary --json` for this month: a dict, or a refusal."""
    try:
        out = run([sys.executable, "-m", "modal", "billing", "summary", "--json"], capture_output=True, text=True, timeout=60, check=True)
        return json.loads(out.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as err:
        raise Refused(f"cannot read the billing summary ({type(err).__name__})") from None


def credit_left(billing):
    """The month's credit minus the metered cost. Title Case and snake_case keys both read. Refuses if money is being billed."""
    if not isinstance(billing, dict):
        raise Refused("the billing summary is not an object")
    got = {str(k).strip().lower().replace(" ", "_"): v for k, v in billing.items()}
    if "metered_cost" not in got or "billed_cost" not in got:
        raise Refused("the billing summary has no metered_cost or billed_cost")
    if _usd(got["billed_cost"]) > 0:
        raise Refused("this month already bills money: the credit is gone")
    return CREDIT_USD - _usd(got["metered_cost"])


def month_spend(path, month):
    """What Modal rows for this YYYY-MM in the ledger add up to (credits plus billed). Any row it cannot read is a refusal."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = [x for x in f.read().splitlines() if x.strip()]
    except OSError:
        raise Refused("cannot read the spend ledger") from None
    total = 0.0
    for line in lines:
        try:
            r = json.loads(line)
            if not isinstance(r, dict):
                raise ValueError
            if r.get("lane") != LANE:
                continue
            if not re.match(r"\d{4}-\d{2}-\d{2}", str(r["run_id"])):
                raise ValueError
            if str(r["run_id"])[:7] == month:
                total += _usd(r["credits_usd"]) + _usd(r["billed_usd"])
        except (ValueError, KeyError, Refused):
            raise Refused("the spend ledger has a Modal row it cannot read") from None
    return total


def check(billing, spent_usd, worst, limit_checked, month):
    """Raise Refused unless every rule holds, with the reasons together."""
    why = []
    if limit_checked != month:
        why.append(f"MODAL_LIMIT_CHECKED must be {month}: read the usage limit on the Modal dashboard, then set it")
    left = credit_left(billing)
    if left < FLOOR_USD:
        why.append(f"${left:.2f} of the credit is left, under ${FLOOR_USD:.0f}")
    elif left - worst < FLOOR_USD:
        why.append(f"the worst case ${worst:.2f} would leave under ${FLOOR_USD:.0f} of ${left:.2f}")
    if spent_usd >= MONTH_CAP_USD:
        why.append(f"Aurelius rows already add up to ${spent_usd:.2f} this month, cap ${MONTH_CAP_USD:.0f}")
    elif spent_usd + worst >= MONTH_CAP_USD:
        why.append(f"${spent_usd:.2f} spent plus the worst case ${worst:.2f} would reach the ${MONTH_CAP_USD:.0f} cap")
    if why:
        raise Refused("; ".join(why))


def ensure(worst, ledger, env=os.environ, now=None, run=subprocess.run):
    """The whole guard: read the bill and the ledger, then check. Returns the month on a pass."""
    month = (now or datetime.now(timezone.utc)).strftime("%Y-%m")
    check(read_billing(run), month_spend(ledger, month), worst, env.get("MODAL_LIMIT_CHECKED"), month)
    return month
