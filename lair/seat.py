"""The seat: the 5 actions, their validators and a rule-based seat."""

from abc import ABC, abstractmethod


def _number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0


def validate_order(spec, order):
    """Raise ValueError unless order has exactly the spec's order fields and a sane budget."""
    if not isinstance(order, dict) or set(order) != {f["field"] for f in spec["order"]}:
        raise ValueError("order must have exactly the spec order fields")
    budget = order["budget"]
    if not isinstance(budget, dict) or not all(_number(budget.get(k)) for k in ("credits", "seconds")):
        raise ValueError("budget needs numeric credits and seconds, 0 or more")


def validate_action(spec, action):
    """Raise ValueError unless action names a spec action and uses only its args."""
    spec_action = {a["name"]: a for a in spec["actions"]}.get(action.get("name"))
    if spec_action is None:
        raise ValueError(f"unknown action {action.get('name')!r}")
    extra = set(action) - {"name"} - set(spec_action["args"])
    if extra:
        raise ValueError(f"{action['name']} does not take {sorted(extra)}")


class Seat(ABC):
    """Reads an observation, returns a list of actions."""

    @abstractmethod
    def decide(self, obs):
        """Return the actions to take for obs."""


class RuleSeat(Seat):
    """Cheapest type that clears the bar, sampled checks, the spec's fix loop.

    The runner clears a key's reply and check, and adds a try, when it re-sends the key.
    """

    def __init__(self, spec, bar=0.75, sample=0.2, order=None):
        self.bar = bar
        self.sample = sample
        self.tries = spec["fix_loop"]["same_worker_tries"]
        self.types = {w["id"]: w for w in spec["worker_types"]}
        self.ladder = sorted(self.types, key=lambda t: (self.types[t]["skill"], self.types[t]["credits_per_call"]))
        by_cost = sorted(self.types, key=lambda t: (self.types[t]["credits_per_call"], t))
        self.cheapest = self.types[by_cost[0]]["credits_per_call"]
        self.start = next((t for t in by_cost if self.types[t]["skill"] >= bar), self.ladder[-1])
        shape = {f["field"]: f["type"] for f in spec["reply"]}
        self.order = {"goal": "answer every item", "done_check": "the value matches the item",
                      "scope": "the item only", "reply_shape": shape, **(order or {}), "budget": None}

    def _map(self, wtype, keys):
        w = self.types[wtype]
        budget = {"credits": w["credits_per_call"] * len(keys), "seconds": w["seconds"] * len(keys)}
        return {"name": "map", "order": {**self.order, "budget": budget}, "children": keys, "worker_type": wtype}

    def decide(self, obs):
        """Same obs, same actions. Order: stop, map, check, then wait or report."""
        replies, checked, tries = obs["replies"], obs["checked"], obs["tries"]
        pending = sorted(obs["pending"])
        running = sorted(k for k in obs["types"] if k not in replies and k not in pending)
        if obs["budget_left"]["credits"] < self.cheapest:
            if pending or running:
                return [{"name": "stop", "children": sorted(pending + running), "grace_s": 5}]
            return [self._report(replies, [])]
        sends, parked = {}, []
        for key in pending:
            sends.setdefault(self.start, []).append(key)
        for key in sorted(replies):
            if replies[key]["status"] != "failed" and checked.get(key) is not False:
                continue
            wtype, n = obs["types"].get(key, self.start), tries.get(key, 1)
            if n >= self.tries:
                i = self.ladder.index(wtype) + 1
                wtype = self.ladder[i] if n == self.tries and i < len(self.ladder) else None
            (sends.setdefault(wtype, []) if wtype else parked).append(key)
        actions = [self._map(t, ks) for t, ks in sorted(sends.items())]
        done = sorted(k for k, r in replies.items() if r["status"] == "completed")
        picks = [k for i, k in enumerate(done) if int((i + 1) * self.sample) > int(i * self.sample)]
        todo = [k for k in picks if k not in checked]
        if todo:
            actions.append({"name": "check", "children": todo, "sample": self.sample})
        if running and not actions:
            actions.append({"name": "wait", "until": "reply"})
        if not (pending or running or actions):
            actions.append(self._report(replies, parked))
        return actions

    def _report(self, replies, parked):
        alarms = sorted({a for r in replies.values() for a in r.get("alarms", [])})
        summary = f"{len(replies) - len(parked)} done, parked: {', '.join(parked) or 'none'}"
        return {"name": "report", "summary": summary, "alarms": alarms}
