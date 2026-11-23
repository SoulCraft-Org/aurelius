"""Stand-in workers: typed by price and skill, with a noisy check.

Every rate here is assumed: skill, price, seconds, crash_rate, false_pass and
false_fail come from spec/aurelius.json or are ours until real runs fit them.
All randomness comes from the rng passed in, never the global random module.
"""


def worker_types(spec):
    """Map each worker type id to its credits_per_call, skill and seconds."""
    keys = ("credits_per_call", "skill", "seconds")
    return {t["id"]: {k: t[k] for k in keys} for t in spec["worker_types"]}


CHECK_COST = 1  # the small type's credits per call (assumed)


def do_item(rng, wtype, item, crash_rate=0.02):
    """One worker call on one item; return a reply with the spec's reply fields."""
    spent = {"credits": wtype["credits_per_call"], "seconds": wtype["seconds"]}
    if rng.random() < crash_rate:
        return {"status": "failed", "facts": [], "alarms": [], "spent": spent}
    skill = wtype["skill"] / 2 if item.fault else wtype["skill"]
    if rng.random() < skill:
        value, tag = item.answer, "seen"
    else:
        value = item.answer + "?"
        tag = "inferred" if rng.random() < 0.5 else "seen"
    alarms = [item.key] if item.alarm and rng.random() < wtype["skill"] else []
    fact = {"claim": item.key, "value": value, "tag": tag, "source": "stand-in"}
    return {"status": "completed", "facts": [fact], "alarms": alarms, "spent": spent}


def check(rng, reply, item, spec):
    """A noisy verdict: passes a wrong reply at false_pass, fails a right one at false_fail."""
    facts = reply["facts"]
    right = reply["status"] == "completed" and bool(facts) and facts[0]["value"] == item.answer
    rates = spec["check"]
    if right:
        return rng.random() >= rates["false_fail"]
    return rng.random() < rates["false_pass"]
