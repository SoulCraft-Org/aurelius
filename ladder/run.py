"""The Ladder runner: one run of a seat on a task, and the score row over seeds."""

import os
import random
from datetime import datetime, timezone
from functools import partial

from ladder.metrics import compute
from lair import load_spec
from lair.baselines import PASS_GRADE, run_baseline
from lair.ledger import Ledger, ResumeMismatch, resume
from lair.seat import RuleSeat
from lair.sim import Sim
from lair.tasks import critical_path, grade, make_task
from lair.workers import CHECK_COST, check, do_item, worker_types


def _rung(spec, rung_id):
    return {r["id"]: r for r in spec["rungs"]}[rung_id]


def tree(spec, rung_id):
    """Seats per tier, leaves first: ceil(agents / span ** tier) for each tier."""
    rung, span = _rung(spec, rung_id), spec["tree"]["span"]
    return [-(-rung["agents"] // span**t) for t in range(1, rung["tiers"] + 1)]


def _wrong(items, facts):
    return sum(f["value"] != items[f["claim"]].answer for f in facts)


class _Leaf:
    """A tier-1 seat: the RuleSeat loop on its own Sim, whose log is its ledger."""

    def __init__(self, spec, task, items, seed, left):
        self.sim, self.led, self.spec, self.task = Sim(seed), Ledger(), spec, task
        self.led.entries = self.sim.log  # the ledger is the log, so replay checks every row
        self.items, self.left, self.types = {i.key: i for i in items}, left, worker_types(spec)
        self.seat, self.pending, self.sent = RuleSeat(spec), list(self.items), {}
        self.replies, self.checked, self.tries, self.rounds = {}, {}, {}, 0
        self.sim.at(0, self.step)

    def step(self, sim):
        """Ask the seat what to do, do it, and come back when the replies are in."""
        self.rounds += 1
        obs = {"pending": self.pending, "replies": self.replies, "checked": self.checked,
               "tries": self.tries, "types": self.sent, "budget_left": {"credits": self.left}}
        secs = []
        for act in self.seat.decide(obs):
            keys = act.get("children", [])
            if act["name"] == "map":
                wtype = self.types[act["worker_type"]]
                sim.record("split", tier=1, shortened=self.task.can_split)
                self.pending = [k for k in self.pending if k not in keys]
                for key in keys:
                    self.replies.pop(key, None), self.checked.pop(key, None)
                    self.tries[key], self.sent[key] = self.tries.get(key, 0) + 1, act["worker_type"]
                    reply = do_item(sim.rng, wtype, self.items[key])
                    self.left -= reply["spent"]["credits"]
                    sim.record("spend", **reply["spent"])
                    if self.left < 0:
                        sim.record("overrun", key=key)
                    sim.at(wtype["seconds"], lambda _, k=key, r=reply: self.replies.__setitem__(k, r))
                secs += [wtype["seconds"]] * len(keys)
            elif act["name"] == "check":  # a check is code: it costs credits, no sim time
                keys = keys[: self.left // CHECK_COST]
                self.left -= CHECK_COST * len(keys)
                for key in keys:
                    self.checked[key] = check(sim.rng, self.replies[key], self.items[key], self.spec)
                    sim.record("spend", credits=CHECK_COST, seconds=0)
                    sim.record("check", key=key, tier=1, verdict=self.checked[key])
            elif act["name"] in ("stop", "report"):  # stop ends the seat with what it has
                return self.report()
        sim.at(max(secs, default=0) if self.task.can_split else sum(secs), self.step)

    def report(self):
        done = {k: r["facts"][0] for k, r in self.replies.items() if r["status"] == "completed"}
        self.facts = {k: f for k, f in done.items() if self.checked.get(k) is not False}
        self.alarms = [a for r in self.replies.values() for a in r["alarms"]]
        self.sim.record("report", tier=1, facts_in=len(done), wrong_in=_wrong(self.items, done.values()),
                        facts_out=len(self.facts), wrong_out=_wrong(self.items, self.facts.values()))


def _same_after_kill(make, full):
    """Kill a copy of the leaf halfway, resume it by replay; does it end as the full run did?"""
    def start():
        leaf = make()
        return leaf.sim, leaf.led

    sim, saved = start()
    sim.run(until=full.sim.now / 2)
    try:
        return resume(start, saved).entries == full.led.entries
    except ResumeMismatch:
        return False


def _lift(top, task, spec, by_key, tier, kids, pot):
    """A seat above tier 1: join its children's facts, check 1 in 5, drop the failures."""
    facts = {k: f for kid in kids for k, f in kid[0].items()}
    top.record("split", tier=tier, shortened=task.can_split)
    row = {"facts_in": len(facts), "wrong_in": _wrong(by_key, facts.values())}
    for key in list(facts)[::5]:
        if pot[0] < CHECK_COST:
            break
        pot[0] -= CHECK_COST
        ok = check(top.rng, {"status": "completed", "facts": [facts[key]]}, by_key[key], spec)
        top.record("spend", credits=CHECK_COST, seconds=0)
        top.record("check", key=key, tier=tier, verdict=ok)
        if not ok:
            del facts[key]
    top.record("report", tier=tier, **row, facts_out=len(facts), wrong_out=_wrong(by_key, facts.values()))
    return facts, [a for kid in kids for a in kid[1]]


def _rule(task, spec, rung_id, seed, budget):
    n, span, sizes = len(task.items), spec["tree"]["span"], tree(spec, rung_id)
    by_key, top = {i.key: i for i in task.items}, Sim(seed)
    for it in (i for i in task.items if i.alarm):
        top.record("alarm_planted", key=it.key)
    kill = random.Random(seed).randrange(sizes[0])  # the leaf that dies halfway
    seats, rounds, spent, end = [], 0, 0, 0.0
    for i in range(sizes[0]):
        mine = task.items[i * span:(i + 1) * span]
        share = budget * len(mine) // n
        make = partial(_Leaf, spec, task, mine, seed * 1_000_003 + i, share)
        leaf = make()
        leaf.sim.run()
        top.log.extend(leaf.sim.log)
        seats.append((leaf.facts, leaf.alarms))
        rounds, spent, end = max(rounds, leaf.rounds), spent + share - leaf.left, max(end, leaf.sim.now)
        if i == kill:
            top.record("kill", seat=f"t1-{i}")
            top.record("resume", seat=f"t1-{i}", same=_same_after_kill(make, leaf))
    top.now, pot = end, [budget - spent]
    for tier in range(2, len(sizes) + 1):
        seats = [_lift(top, task, spec, by_key, tier, seats[j:j + span], pot)
                 for j in range(0, len(seats), span)]
    facts, alarms = seats[0]
    for key in alarms:
        top.record("alarm_top", key=key)
    got = grade(task, {k: f["value"] for k, f in facts.items()})
    steps = rounds + len(sizes) - 1 if task.can_split else critical_path(task)
    top.record("final", task_id=task.id, grade=got, verified=got >= PASS_GRADE, critical_steps=steps)
    return top.log


def run_once(rung_id, seat, spec, seed, kind="table", budget=None):
    """One run log. seat is "rule" or a baseline id. Budget: one medium call per item."""
    agents = _rung(spec, rung_id)["agents"]
    task, budget = make_task(seed, agents, kind), 4 * agents if budget is None else budget
    if seat == "rule":
        return _rule(task, spec, rung_id, seed, budget)
    return run_baseline(seat, task, spec, seed, budget)


def score(rung_id, seat, seeds=(0, 1, 2), kind="table"):
    """The spec's score row for a seat on a rung, with the 8 metrics over all seeds."""
    spec = load_spec()
    return {"date": datetime.now(timezone.utc).date().isoformat(),
            "commit": os.environ.get("GITHUB_SHA", "local"), "rung": rung_id, "seat": seat,
            "workers": "sim", "seed": list(seeds), "metrics": compute([run_once(rung_id, seat, spec, s, kind) for s in seeds])}
