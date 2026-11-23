"""A model seat: an untrained model on OpenRouter, pinned to US hosts, with a hard spend cap."""

import hashlib
import json
import os
import urllib.request

from lair.seat import OPTIONAL, Seat, validate_action

URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "qwen/qwen3.5-9b"
PROVIDER = {"only": ["deepinfra", "together", "primeintellect"], "allow_fallbacks": False, "data_collection": "deny"}
PRICE_IN, PRICE_OUT = 0.15 / 1e6, 0.25 / 1e6  # USD per token: the highest price among the pinned hosts
TYPES = {"children": "array", "alarms": "array", "facts": "array", "spent": "object", "summary": "string", "until": "string"}


def tools(spec):
    """The spec's 5 actions as function schemas."""
    props = {f["field"]: {"type": f["type"]} for f in spec["order"]}
    props["budget"] = {"type": "object", "properties": {"credits": {"type": "number"}, "seconds": {"type": "number"}}}
    args = {"order": {"type": "object", "properties": props, "required": list(props)},
            "worker_type": {"type": "string", "enum": [w["id"] for w in spec["worker_types"]]}}
    return [{"type": "function", "function": {"name": a["name"], "description": a["does"], "parameters": {
        "type": "object", "properties": {n: args.get(n) or {"type": TYPES.get(n, "number")} for n in a["args"]},
        "required": [n for n in a["args"] if n not in OPTIONAL]}}} for a in spec["actions"]]


class ModelSeat(Seat):
    """Asks the model what to do each round. The key is read per call, never stored."""
    def __init__(self, spec, cap_usd=1.0, max_calls=200):
        self.spec, self.cap_usd, self.max_calls = spec, cap_usd, max_calls
        self.types, self.tools = {w["id"]: w for w in spec["worker_types"]}, tools(spec)
        self.spent_usd, self.calls, self.format_errors, self._cache = 0.0, 0, 0, {}
        self.system = ("You are a seat over workers: each pending key needs one worker reply. Call tools: map keys to one "
                       "worker type (order budget = credits_per_call x keys, within budget_left), check a sample of replies, "
                       f"then report. Dial: {json.dumps(spec['dial'])}. Types: {json.dumps(self.types)}.")

    def decide(self, obs):
        alarms = sorted({a for r in obs["replies"].values() for a in r.get("alarms", [])})
        view = {**obs, "replies": {k: r["status"] for k, r in obs["replies"].items()}, "alarms": alarms}
        body = json.dumps({"model": MODEL, "temperature": 0, "provider": PROVIDER, "tools": self.tools, "messages": [
            {"role": "system", "content": self.system},
            {"role": "user", "content": json.dumps(view, sort_keys=True, separators=(",", ":"))}]}, sort_keys=True)
        key = hashlib.sha256(body.encode()).hexdigest()
        if key not in self._cache:  # a replay from the same seed asks the same questions: answer them free
            if self.spent_usd >= self.cap_usd or self.calls >= self.max_calls:
                return self._end(obs, alarms)
            data = self._post(body)
            if data is None:
                return self._end(obs, alarms)
            try:
                acts = self._parse(data, obs)
            except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                self.format_errors += 1
                acts = self._end(obs, alarms)
            self._cache[key] = json.dumps(acts)
        return json.loads(self._cache[key])

    def _post(self, body):
        """One call. A failed call is counted and returns None; its text is dropped, never raised."""
        token = os.environ.get("OPENROUTER_API_KEY")
        if not token:
            raise ValueError("OPENROUTER_API_KEY is not set")
        req = urllib.request.Request(URL, body.encode(), {"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        self.calls += 1
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
            use = data.get("usage") or {}  # unknown usage is never zero: price the request as sent plus 1k out
            self.spent_usd += use.get("prompt_tokens", len(body) // 3) * PRICE_IN + use.get("completion_tokens", 1024) * PRICE_OUT
            return data
        except (OSError, ValueError, AttributeError):
            self.format_errors += 1

    def _parse(self, data, obs):
        calls = data["choices"][0]["message"].get("tool_calls") or []
        acts = [{"name": c["function"]["name"], **json.loads(c["function"]["arguments"])} for c in calls]
        retry = {k for k, r in obs["replies"].items() if r["status"] == "failed" or obs["checked"].get(k) is False}
        for a in acts:
            validate_action(self.spec, a)
            keys = a.get("children", [])
            if a["name"] in ("map", "check") and not keys:
                raise ValueError("no children")
            if a["name"] == "map":
                cost = self.types[a["worker_type"]]["credits_per_call"] * len(keys)
                if not (set(keys) <= set(obs["pending"]) | retry and cost <= obs["budget_left"]["credits"]):
                    raise ValueError("map must send resendable keys within budget_left")
            if a["name"] == "check" and not set(keys) <= set(obs["replies"]) - set(obs["checked"]):
                raise ValueError("check must name replies not yet checked")
        if all(a["name"] == "wait" for a in acts):
            raise ValueError("no usable tool call")  # wait alone would spin the runner
        return acts

    def _end(self, obs, alarms):
        """Stop then report with what it has, so the run ends honestly."""
        live = sorted(set(obs["pending"]) | {k for k in obs["types"] if k not in obs["replies"]})
        return [{"name": "stop", "children": live, "grace_s": 5},
                {"name": "report", "summary": f"model seat ended with {len(obs['replies'])} replies", "alarms": alarms}]
