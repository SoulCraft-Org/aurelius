"""Step 31: turn transcript lines into prompt-completion rows for TRL SFT (conversational format with tool calls).

`python3 -m train.traces IN.jsonl OUT.jsonl --min-reward 0.9`. Each input line has seed, split, rung, obs, actions and
the run's final reward. Dev seeds only: a val or test seed stops the run. Prints counts kept and dropped by reason.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from ladder.models import ModelSeat
from lair import load_spec
from lair.seat import validate_action


def user_message(obs):
    """The user turn exactly as ModelSeat.decide sends it: replies shown by status only."""
    view = {**obs, "replies": {k: r["status"] for k, r in obs["replies"].items()}}
    return json.dumps(view, sort_keys=True, separators=(",", ":"))


def split_of(spec, line):
    """The line's split, checked against its seed: a line that says dev but holds a val seed is val."""
    seed = line["seed"]
    own = next((s for s, (lo, hi) in spec["seeds"].items() if lo <= seed <= hi), None)
    if own is None or line.get("split", own) != own:
        raise ValueError(f"seed {seed} and split {line.get('split')!r} disagree with the spec")
    return own


def visible(user, actions):
    """The actions with only what the user turn shows: an alarm stays only if a reply in the view lists it; None if a child key is hidden."""
    shown = {x for r in json.loads(user)["replies"].values() if isinstance(r, dict) for x in r.get("alarms", [])}
    if not all(json.dumps(k) in user for a in actions for k in a.get("children", [])):
        return None
    return [{**a, "alarms": [x for x in a["alarms"] if x in shown]} if "alarms" in a else a for a in actions]


def example(seat, line):
    """One prompt-completion row: [system, user] and the actions as tool calls (arguments as JSON strings), with the tools."""
    user = user_message(line["obs"])
    if (acts := visible(user, line["actions"])) is None:
        return None
    calls = [{"type": "function", "function": {"name": a["name"], "arguments": json.dumps({k: v for k, v in a.items() if k != "name"})}} for a in acts]
    return {"prompt": [{"role": "system", "content": seat.system}, {"role": "user", "content": user}],
            "completion": [{"role": "assistant", "content": "", "tool_calls": calls}], "tools": seat.tools}


def convert(spec, lines, min_reward, cap=50):
    """(examples, dropped Counter). Raises ValueError on a val or test seed, before anything is kept."""
    seat, drops, out, seen, per_run = ModelSeat(spec), Counter(), [], set(), Counter()
    for line in lines:
        if (s := split_of(spec, line)) != "dev":
            raise ValueError(f"refused: seed {line['seed']} is in the {s} split; only dev seeds train")
    for line in lines:
        reward = line.get("reward")
        if isinstance(reward, bool) or not isinstance(reward, (int, float)) or reward < min_reward:
            drops["no_reward" if not isinstance(reward, (int, float)) else "below_reward"] += 1
            continue
        try:
            for a in line["actions"]:
                validate_action(spec, a)
            user_message(line["obs"])
        except (ValueError, KeyError, TypeError, AttributeError):
            drops["invalid"] += 1
            continue
        if all(a["name"] == "wait" for a in line["actions"]):  # also no actions: ModelSeat rejects both as "no usable tool call"
            drops["no_usable_call"] += 1
            continue
        ex = example(seat, line)
        key, run = ex and json.dumps([ex["prompt"][1], ex["completion"]], sort_keys=True), (line.get("rung"), line["seed"])
        if ex is None:
            drops["hidden"] += 1
        elif key in seen:
            drops["duplicate"] += 1
        elif per_run[run] >= cap:
            drops["over_cap"] += 1
        else:
            seen.add(key)
            per_run[run] += 1
            out.append(ex)
    return out, drops


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m train.traces", description=__doc__.splitlines()[0])
    p.add_argument("src", type=Path, help="transcript JSON lines")
    p.add_argument("dst", type=Path, help="prompt-completion rows, JSON lines")
    p.add_argument("--min-reward", type=float, required=True, help="keep runs at or above this final reward")
    p.add_argument("--cap", type=int, default=50, help="examples kept per run (rung and seed)")
    args = p.parse_args(argv)
    lines = [json.loads(x) for x in args.src.read_text().splitlines() if x.strip()]
    try:
        rows, drops = convert(load_spec(), lines, args.min_reward, args.cap)
    except ValueError as err:
        sys.exit(str(err))
    args.dst.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    print(f"kept {len(rows)} of {len(lines)}")
    for why, n in sorted(drops.items()):
        print(f"dropped {why}: {n}")


if __name__ == "__main__":
    main()
