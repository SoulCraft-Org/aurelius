"""Three baselines to beat: one agent, flat fan-out, cheapest that passes."""

from lair.sim import Sim
from lair.tasks import critical_path, grade
from lair.workers import do_item, worker_types

PASS_GRADE = 0.95  # a run is verified at this grade or better
BAR = 0.75  # the skill a worker type needs for cheapest_that_passes
NAMES = ("one_agent", "flat_fan_out", "cheapest_that_passes")


def _pick(types, name):
    """The one worker type a baseline sends every item to."""
    if name == "one_agent":
        return types["large"]
    if name == "flat_fan_out":
        return types["medium"]
    clear = [t for t in types.values() if t["skill"] >= BAR]
    pool = clear or [max(types.values(), key=lambda t: t["skill"])]
    return min(pool, key=lambda t: t["credits_per_call"])


def run_baseline(name, task, spec, seed, budget_credits):
    """Run one baseline on a task and return its log. Spend never passes the budget."""
    if name not in NAMES:
        raise ValueError(f"name must be one of {NAMES}")
    sim = Sim(seed)
    wtype = _pick(worker_types(spec), name)
    cost = wtype["credits_per_call"]
    serial = name == "one_agent" or not task.can_split
    if name != "one_agent":
        sim.record("split", tier=1, shortened=task.can_split)
    for it in task.items:
        if it.alarm:
            sim.record("alarm_planted", key=it.key)
    answers = {}
    spent = 0
    longest = 0.0
    for it in task.items:
        if spent + cost > budget_credits:
            break  # items not done count as wrong
        reply = do_item(sim.rng, wtype, it)
        spent += reply["spent"]["credits"]
        secs = reply["spent"]["seconds"]
        if serial:
            sim.now += secs
        else:
            longest = max(longest, secs)
        sim.record("spend", credits=reply["spent"]["credits"], seconds=secs)
        if reply["status"] == "completed":
            answers[it.key] = reply["facts"][0]["value"]
        for key in reply["alarms"]:
            sim.record("alarm_top", key=key)
    if not serial:
        sim.now = longest
    steps = len(task.items) if name == "one_agent" else critical_path(task)
    score = grade(task, answers)
    sim.record("final", task_id=task.id, grade=score, verified=score >= PASS_GRADE,
               critical_steps=steps)
    return sim.log
