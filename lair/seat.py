"""The seat: the 5 actions, their validators and a rule-based seat."""

from abc import ABC, abstractmethod

OPTIONAL = {"sample", "grace_s", "until", "facts", "alarms", "spent"}


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
    """Raise ValueError unless action is a well-formed spec action: name, args, types."""
    if not isinstance(action, dict) or not isinstance(action.get("name"), str):
        raise ValueError("action must be a dict with a string name")
    name = action["name"]
    spec_action = {a["name"]: a for a in spec["actions"]}.get(name)
    if spec_action is None:
        raise ValueError(f"unknown action {name!r}")
    extra = set(action) - {"name"} - set(spec_action["args"])
    missing = [a for a in spec_action["args"] if a not in OPTIONAL | set(action)]
    ids = [w["id"] for w in spec["worker_types"]]
    if extra or missing or not isinstance(action.get("children", []), list):
        raise ValueError(f"{name}: unexpected {sorted(extra)}, missing {missing}, or children not a list")
    nums = all(_number(action[k]) for k in ("grace_s", "sample") if k in action)
    if not nums or action.get("worker_type", ids[0]) not in ids:
        raise ValueError("grace_s and sample must be numbers, worker_type a spec type")
    if "order" in action:
        validate_order(spec, action["order"])


class Seat(ABC):
    @abstractmethod
    def decide(self, obs):
        """Read an observation; return the list of actions to take."""


class RuleSeat(Seat):
    """Cheapest type that clears the bar, sampled checks, the spec's fix loop.

    The runner clears a key's reply and check, and adds a try, when it re-sends the key.
    """

    def __init__(self, spec, bar=0.75, sample=0.2, order=None):
        self.sample = sample
        self.tries = spec["fix_loop"]["same_worker_tries"]
        self.types = {w["id"]: w for w in spec["worker_types"]}
        self.ladder = sorted(self.types, key=lambda t: (self.types[t]["skill"], self.types[t]["credits_per_call"]))
        by_cost = sorted(self.types, key=lambda t: (self.types[t]["credits_per_call"], t))
        self.cheapest = self.types[by_cost[0]]["credits_per_call"]
        self.start = next((t for t in by_cost if self.types[t]["skill"] >= bar), self.ladder[-1])
        self.order = {"goal": "answer every item", "done_check": "the value matches the item", "scope": "the item only",
                      "reply_shape": {f["field"]: f["type"] for f in spec["reply"]}, **(order or {})}

    def _map(self, wtype, keys):
        w, n = self.types[wtype], len(keys)
        budget = {"credits": w["credits_per_call"] * n, "seconds": w["seconds"] * n}
        return {"name": "map", "order": {**self.order, "budget": budget}, "children": keys, "worker_type": wtype}

    def decide(self, obs):
        """Same obs, same actions. Order: stop, map, check, then wait or report."""
        replies, checked, tries = obs["replies"], obs["checked"], obs["tries"]
        pending = sorted(obs["pending"])
        running = sorted(k for k in obs["types"] if k not in replies and k not in pending)
        left = obs["budget_left"]["credits"]
        if left < self.cheapest and (pending or running):
            return [{"name": "stop", "children": sorted(pending + running), "grace_s": 5}]
        sends, parked = ({self.start: list(pending)} if pending else {}), []
        for key in sorted(replies):
            if replies[key]["status"] != "failed" and checked.get(key) is not False:
                continue
            wtype, n = obs["types"].get(key, self.start), tries.get(key, 1)
            if n >= self.tries:
                i = self.ladder.index(wtype) + 1
                wtype = self.ladder[i] if n == self.tries and i < len(self.ladder) else None
            (sends.setdefault(wtype, []) if wtype else parked).append(key)
        actions = []
        for wtype, keys in sorted(sends.items()):
            cost = self.types[wtype]["credits_per_call"]
            n = min(len(keys), int(left // cost))
            parked += keys[n:]
            if n:
                actions.append(self._map(wtype, keys[:n]))
                left -= n * cost
        done, s = sorted(k for k, r in replies.items() if r["status"] == "completed"), self.sample
        todo = [k for i, k in enumerate(done) if int((i + 1) * s) > int(i * s) and k not in checked]
        if todo and left >= self.cheapest:
            actions.append({"name": "check", "children": todo, "sample": s})
        if running and not actions:
            actions.append({"name": "wait", "until": "reply"})
        if not (running or actions):
            alarms = sorted({a for r in replies.values() for a in r.get("alarms", [])})
            summary = f"{sum(k not in parked for k in replies)} done, parked: {', '.join(parked) or 'none'}"
            actions.append({"name": "report", "summary": summary, "alarms": alarms})
        return actions
