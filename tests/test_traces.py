"""Trace conversion: no network, no model."""

import json
import os
import unittest
from unittest import mock

from ladder.models import ModelSeat
from lair import load_spec
from lair.seat import RuleSeat, validate_action
from train.traces import convert, example

SPEC = load_spec()
OBS = {"pending": ["k1"], "replies": {"k0": {"status": "completed", "facts": [{"claim": "k0", "value": 1}], "alarms": []}},
       "checked": {}, "tries": {}, "types": {"k0": "medium"}, "budget_left": {"credits": 50}}
ORDER = {"goal": "g", "done_check": "d", "scope": "s", "reply_shape": {}, "budget": {"credits": 4, "seconds": 4}}
MAP = {"name": "map", "order": ORDER, "children": ["k1"], "worker_type": "medium"}


def line(**kw):
    return {"seed": 3, "split": "dev", "rung": "r10", "obs": OBS, "actions": [MAP], "reward": 0.95, **kw}


class TestTraces(unittest.TestCase):
    def test_val_and_test_seeds_refused(self):
        for seed, split in ((1000, "val"), (2500, "test"), (1000, "dev")):  # the last: a dev label on a val seed
            with self.assertRaises(ValueError):
                convert(SPEC, [line(), line(seed=seed, split=split)], 0.9)

    def test_threshold_dedupe_and_cap(self):
        wait, nope = [{"name": "wait", "until": "reply"}], [{"name": "nope"}]
        rows, drops = convert(SPEC, [line(), line(), line(reward=0.5), line(reward=None), line(actions=wait), line(actions=nope)], 0.9)
        self.assertEqual(len(rows), 1)
        self.assertEqual(dict(drops), {"duplicate": 1, "below_reward": 1, "no_reward": 1, "no_usable_call": 1, "invalid": 1})
        many = [line(obs={**OBS, "budget_left": {"credits": 50 - i}}) for i in range(5)]
        self.assertEqual(len(convert(SPEC, many, 0.9, cap=2)[0]), 2)

    def test_user_message_is_what_model_seat_sends(self):
        resp = mock.MagicMock(**{"__enter__.return_value.read.return_value": b"{}"})
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "x"}), mock.patch("urllib.request.urlopen", return_value=resp) as urlopen:
            seat = ModelSeat(SPEC)
            seat.decide(OBS)
        sent = json.loads(urlopen.call_args.args[0].data)
        row = example(seat, line())
        self.assertEqual(row["prompt"], sent["messages"])
        self.assertNotIn('"facts"', row["prompt"][1]["content"])  # no truth fields reach the prompt

    def test_tool_calls_validate(self):
        acts = RuleSeat(SPEC).decide(OBS | {"replies": {}})
        row = example(ModelSeat(SPEC), line(actions=acts))
        self.assertEqual(row["tools"], ModelSeat(SPEC).tools)
        for fn in (c["function"] for c in row["completion"][0]["tool_calls"]):
            self.assertIsInstance(fn["arguments"], str)  # a JSON string, as the API sends it
            validate_action(SPEC, {"name": fn["name"], **json.loads(fn["arguments"])})

    def test_the_assistant_turn_holds_only_what_the_user_turn_shows(self):
        report = {"name": "report", "summary": "s", "alarms": ["late", "hidden"]}
        for acts, obs, shown in (([MAP, report], OBS, []), ([report], {**OBS, "pending": ["late"]}, ["late"])):
            row = example(ModelSeat(SPEC), line(obs=obs, actions=acts))
            args = [json.loads(c["function"]["arguments"]) for c in row["completion"][0]["tool_calls"]]
            self.assertEqual([x for a in args for x in a.get("alarms", [])], shown)
            self.assertTrue(all(json.dumps(v) in row["prompt"][1]["content"] for a in args for v in a.get("children", []) + a.get("alarms", [])))
        self.assertEqual(convert(SPEC, [line(actions=[{**MAP, "children": ["nope"]}])], 0.9)[1]["hidden"], 1)


if __name__ == "__main__":
    unittest.main()
