"""A step-by-step Lair environment: one tier-1 seat, driven by whoever calls act()."""

import copy

from ladder.run import _Leaf, _rung, check_split
from lair.seat import validate_action
from lair.tasks import grade, make_task

RUNGS = ("r10", "r47")  # one tier-1 seat: the whole task is one leaf


class LairEnv:
    """reset() builds the task as run_once does; act() takes the seat's actions and runs to the replies."""

    def __init__(self, spec):
        self.spec, self.leaf, self.done = spec, None, False

    def reset(self, rung, seed, split="dev", kind="table"):
        """Start a run of the single tier-1 seat of r10 or r47. Return the first obs."""
        if rung not in RUNGS:
            raise ValueError(f"the env runs on {' and '.join(RUNGS)} only")
        check_split(self.spec, split, [seed])
        agents = _rung(self.spec, rung)["agents"]
        task = make_task(seed, agents, kind)  # same task, leaf seed and budget share as run_once
        self.leaf = _Leaf(self.spec, task, task.items, seed * 1_000_003, 5 * agents, scheduled=False)
        self.done = False
        return self._obs()

    def _obs(self):
        return copy.deepcopy(self.leaf.observe())  # a copy: the seat cannot reach the leaf's state

    def act(self, actions):
        """Validate every action, apply them, run until the replies are in. Return (obs, done)."""
        if self.leaf is None or self.done:
            raise RuntimeError("call reset() first: there is no run in progress")
        for action in actions:
            validate_action(self.spec, action)
        sim = self.leaf.sim
        delay = self.leaf.apply(actions, sim)
        if delay is None:
            self.done = True
        else:
            sim.run(until=sim.now + delay)
        return self._obs(), self.done

    def reward(self):
        """The share of items right over what the seat reported (lair.tasks.grade); 0 before done."""
        if not self.done:
            return 0.0
        return grade(self.leaf.task, {k: f["value"] for k, f in self.leaf.facts.items()})

    @property
    def log(self):
        """The run's rows, as run_once logs them."""
        return self.leaf.sim.log if self.leaf else []
