"""Tasks with known answers, planted faults and chains that must not be split."""

import random
from dataclasses import dataclass

KINDS = ("table", "no_split")


@dataclass(frozen=True)
class Item:
    """One cell to fill: its true answer, and whether it hides a fault or alarm."""

    key: str
    answer: str
    fault: bool
    alarm: bool
    after: str | None


@dataclass(frozen=True)
class Task:
    """A list of items. A table can be split; a no_split chain cannot."""

    id: str
    kind: str
    items: tuple[Item, ...]

    @property
    def can_split(self):
        return self.kind == "table"


def make_task(seed, size, kind="table", fault_rate=0.05, alarm_rate=0.01):
    """Build a task from seed alone. In no_split each item waits on the one before."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if size < 1:
        raise ValueError("size must be at least 1")
    rng = random.Random(seed)
    items = []
    prev = None
    for i in range(size):
        key = f"k{i}"
        fault = rng.random() < fault_rate
        alarm = rng.random() < alarm_rate
        answer = f"{rng.getrandbits(32):08x}"
        items.append(Item(key, answer, fault, alarm, prev if kind == "no_split" else None))
        prev = key
    return Task(f"{kind}-{seed}-{size}-{fault_rate}-{alarm_rate}", kind, tuple(items))


def grade(task, answers):
    """Share of items whose answer matches, from 0 to 1."""
    right = sum(1 for it in task.items if answers.get(it.key) == it.answer)
    return right / len(task.items) if task.items else 0.0


def critical_path(task):
    """Longest dependency chain: 1 for a table, size for a no_split chain."""
    depth = {}
    for it in task.items:
        depth[it.key] = 1 + (depth[it.after] if it.after is not None else 0)
    return max(depth.values(), default=0)
