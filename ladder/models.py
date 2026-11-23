"""A model seat: an untrained model on OpenRouter, pinned to US hosts, with a hard spend cap."""

import hashlib
import json
import os
import urllib.request

from lair.seat import OPTIONAL, Seat, validate_action
from lair.workers import CHECK_COST

URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "qwen/qwen3.5-9b"
PROVIDER = {"only": ["deepinfra", "together", "primeintellect"], "allow_fallbacks": False, "data_collection": "deny"}
PRICE_IN, PRICE_OUT, MAX_TOKENS = 0.15 / 1e6, 0.25 / 1e6, 1024  # USD per token: the highest among the pinned hosts
TYPES = {"children": "array", "alarms": "array", "facts": "array", "spent": "object", "summary": "string", "until": "string"}


def tools(spec):  # the spec's 5 actions as function schemas
    props = {f["field"]: {"type": f["type"]} for f in spec["order"]}
    props["budget"] = {"type": "object", "properties": {"credits": {"type": "number"}, "seconds": {"type": "number"}}}
    args = {"order": {"type": "object", "properties": props, "required": list(props)},
            "worker_type": {"type": "string", "enum": [w["id"] for w in spec["worker_types"]]}}
    return [{"type": "function", "function": {"name": a["name"], "description": a["does"], "parameters": {
        "type": "object", "properties": {n: args.get(n) or {"type": TYPES.get(n, "number")} for n in a["args"]},
        "required": [n for n in a["args"] if n not in OPTIONAL]}}} for a in spec["actions"]]


class ModelSeat(Seat):  # asks the model each round; the key is read per call, never stored
    def __init__(self, spec, cap_usd=None, max_calls=200):
        # MODEL_CAP_USD lets a workflow split one total cap across rungs; it can only lower the $1 ceiling.
        cap = cap_usd if cap_usd is not None else float(os.environ.get("MODEL_CAP_USD", "1.0"))
        if not cap >= 0:  # also rejects nan, which would never trip the cap
            raise ValueError("cap must be a number, 0 or more")
        self.spec, self.cap_usd, self.max_calls = spec, min(cap, 1.0), max_calls
        self.types, self.tools = {w["id"]: w for w in spec["worker_types"]}, tools(spec)
        self.spent_usd, self.calls, self.asks, self.format_errors, self._cache = 0.0, 0, 0, 0, {}
        self.errors = {}  # kind -> count: an HTTP status, an exception name or an API error code; never a body or the key
        self.system = ("You are a seat over workers: each pending key needs one reply. Call tools: map keys to one worker type "
                       "(budget = credits_per_call x keys, within budget_left), check a sample of replies, then report. "
                       f"Dial: {json.dumps(spec['dial'])}. Types: {json.dumps(self.types)}.")

    def decide(self, obs):
        view = {**obs, "replies": {k: r["status"] for k, r in obs["replies"].items()}}
        self.asks += 1  # cached answers are free but not endless: a seat that loops on one is cut off
        if self.asks > 5 * self.max_calls:
            return self._end(obs)
        body = json.dumps({"model": MODEL, "temperature": 0, "max_tokens": MAX_TOKENS, "provider": PROVIDER, "tools": self.tools,
                           "messages": [{"role": "system", "content": self.system},
                                        {"role": "user", "content": json.dumps(view, sort_keys=True, separators=(",", ":"))}]},
                          sort_keys=True)
        key = hashlib.sha256(body.encode()).hexdigest()
        if key not in self._cache:  # a replay from the same seed asks the same questions: answer them free
            if self.spent_usd >= self.cap_usd or self.calls >= self.max_calls:
                return self._end(obs)
            try:
                acts = self._parse(self._post(body), obs)  # a failed call gives None: counted, ended and cached like a bad answer
            except (ValueError, TypeError, KeyError, IndexError, AttributeError) as err:
                self.format_errors += 1
                self._note(type(err).__name__)
                acts = self._end(obs)
            self._cache[key] = json.dumps(acts)
        return json.loads(self._cache[key])

    def _post(self, body):  # one call; None on any failure, which is billed in full and whose text is dropped
        token = os.environ.get("OPENROUTER_API_KEY")
        if not token:
            raise RuntimeError("OPENROUTER_API_KEY is not set")  # loud: a score row without a key would mislead
        req = urllib.request.Request(URL, body.encode(), {"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        self.calls += 1
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
            use = data.get("usage")
        except (OSError, ValueError, AttributeError) as err:
            self._note(f"http_{err.code}" if isinstance(getattr(err, "code", None), int) else type(err).__name__)
            data = use = None
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            self._note(f"api_{data['error'].get('code', 'error')}")
        use = use if isinstance(use, dict) else {}
        num = lambda v, d: v if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else d  # unknown is never zero
        self.spent_usd += num(use.get("prompt_tokens"), len(body) // 3) * PRICE_IN + num(use.get("completion_tokens"), MAX_TOKENS) * PRICE_OUT
        return data

    def _note(self, kind):
        kind = str(kind)[:40]
        self.errors[kind] = self.errors.get(kind, 0) + 1

    def stats(self):
        """What the seat did, for the score row: no prompt, no answer text, no key."""
        return {"calls": self.calls, "spent_usd": round(self.spent_usd, 6), "format_errors": self.format_errors,
                "errors": dict(sorted(self.errors.items()))}

    def _parse(self, data, obs):
        calls = data["choices"][0]["message"].get("tool_calls") or []
        acts = [{"name": c["function"]["name"], **json.loads(c["function"]["arguments"])} for c in calls]
        retry = {k for k, r in obs["replies"].items() if r["status"] == "failed" or obs["checked"].get(k) is False}
        for a in acts:
            validate_action(self.spec, a)
            keys = a.get("children", [])
            if a["name"] == "map":
                cost = self.types[a["worker_type"]]["credits_per_call"] * len(keys)
                if not (keys and set(keys) <= set(obs["pending"]) | retry and cost <= obs["budget_left"]["credits"]):
                    raise ValueError("map must send resendable keys within budget_left")
            if a["name"] == "check" and not (keys and set(keys) <= set(obs["replies"]) - set(obs["checked"])
                                             and len(keys) * CHECK_COST <= obs["budget_left"]["credits"]):
                raise ValueError("check must name unchecked replies it can pay for")
        if all(a["name"] == "wait" for a in acts):
            raise ValueError("no usable tool call")  # wait alone would spin the runner
        return acts

    def _end(self, obs):  # stop then report with what it has, so the run ends honestly
        live = sorted(set(obs["pending"]) | {k for k in obs["types"] if k not in obs["replies"]})
        alarms = sorted({a for r in obs["replies"].values() for a in r.get("alarms", [])})
        return [{"name": "stop", "children": live, "grace_s": 5},
                {"name": "report", "summary": f"model seat ended with {len(obs['replies'])} replies", "alarms": alarms}]
