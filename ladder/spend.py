"""The credit ledger: one JSON line per cloud run in ladder/spend.jsonl. No key, no prompt, no answer text."""

import json
import math
import os

TEXT = ("run_id", "lane", "gpu")
NUMBERS = ("seconds", "usd_per_hour", "credits_usd", "billed_usd")


def _number(x):
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        return False
    try:
        return math.isfinite(x) and x >= 0
    except OverflowError:  # an int too big for a float
        return False


def row(run_id, lane, gpu, seconds, usd_per_hour, credits_usd, billed_usd):
    """A ledger row with every field; raise ValueError on empty text or a number that is not finite and 0 or more."""
    out = dict(zip(TEXT + NUMBERS, (run_id, lane, gpu, seconds, usd_per_hour, credits_usd, billed_usd)))
    bad = [k for k in TEXT if not (isinstance(out[k], str) and out[k])] + [k for k in NUMBERS if not _number(out[k])]
    if bad:
        raise ValueError(f"ledger row needs text for run_id, lane and gpu and numbers 0 or more elsewhere: {bad}")
    return out


def append(path, entry):
    """Write one validated row as one JSON line; a missing or extra field is refused."""
    entry = row(**entry)
    with open(path, "a+b") as f:  # binary, so the last byte is read as it is
        f.seek(0, os.SEEK_END)
        if f.tell():
            f.seek(-1, os.SEEK_END)
            lead = b"" if f.read(1) == b"\n" else b"\n"  # a file that ends mid-line gets its line closed first
        else:
            lead = b""
        f.write(lead + (json.dumps(entry, sort_keys=True) + "\n").encode())
        f.flush()
        os.fsync(f.fileno())


def unbilled(rows):
    """True only for a non-empty ledger where every row billed 0: credits paid for all of it."""
    rows = list(rows)
    return bool(rows) and all(_number(r.get("billed_usd")) and r["billed_usd"] == 0 for r in rows)
