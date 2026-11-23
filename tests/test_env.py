"""Unit tests for the step-by-step Lair environment."""

import copy
import unittest

from ladder.env import LairEnv
from ladder.run import run_once
from lair import load_spec
from lair.seat import RuleSeat

SPEC = load_spec()
ORDER = {**RuleSeat(SPEC).order, "budget": {"credits": 1, "seconds": 1}}


def send(wtype, keys):
    return {"name": "map", "children": keys, "worker_type": wtype, "order": ORDER}


def look(keys):
    return {"name": "check", "children": keys, "sample": 1}


def state(env):
    return copy.deepcopy((env.leaf.observe(), env.log, env.leaf.rounds))


def drive(env, rung, seed):
    obs, done = env.reset(rung, seed), False
    seat = RuleSeat(SPEC)
    while not done:
        obs, done = env.act(seat.decide(obs))
    return env.reward()


class EnvTest(unittest.TestCase):
    def test_the_rule_seat_gets_the_grade_of_run_once(self):
        for rung in ("r10", "r47"):
            for seed in range(3):
                env = LairEnv(SPEC)
                final = [r for r in run_once(rung, "rule", SPEC, seed) if r["kind"] == "final"][-1]
                self.assertEqual(drive(env, rung, seed), final["grade"])
                self.assertTrue(any(r["kind"] == "report" for r in env.log))

    def test_reward_is_zero_before_done(self):
        env = LairEnv(SPEC)
        obs = env.reset("r10", 0)
        self.assertEqual(env.reward(), 0.0)
        obs, done = env.act(RuleSeat(SPEC).decide(obs))
        self.assertEqual((done, env.reward()), (False, 0.0))

    def test_an_invalid_action_raises_and_changes_nothing(self):
        env = LairEnv(SPEC)
        env.reset("r10", 0)
        for bad in ({"name": "fly"}, {"name": "map", "children": ["k0"], "worker_type": "nope", "order": {}}):
            with self.assertRaises(ValueError):
                env.act([bad])
        self.assertEqual(env.log, [])

    def test_a_refused_act_changes_nothing(self):
        env = LairEnv(SPEC)
        env.act(RuleSeat(SPEC).decide(env.reset("r10", 0)))
        got = next(k for k, r in env.leaf.replies.items() if r["status"] == "completed")
        before = state(env)
        for acts in ([send("small", ["k0", "k99"])], [look(["k99"])], [look([got, got])], [send("small", [got])],
                     [send("small", [])], [send("small", ["k0"]), send("small", ["k0"])]):
            with self.assertRaises(ValueError):
                env.act(acts)
            self.assertEqual(state(env), before)

    def test_a_map_without_a_worker_type_raises_value_error_and_changes_nothing(self):
        env = LairEnv(SPEC)
        env.reset("r10", 0)
        before = state(env)
        with self.assertRaises(ValueError):
            env.act([{"name": "map", "children": ["k0"], "order": ORDER}])
        self.assertEqual(state(env), before)

    def test_a_list_that_costs_more_than_the_budget_is_refused(self):
        env = LairEnv(SPEC)
        env.reset("r10", 0)
        env.leaf.left = 9  # ten small calls would cost 10
        before, keys = state(env), [f"k{i}" for i in range(10)]
        for acts in ([send("small", keys)], [send("medium", keys[:3])],
                     [send("small", keys[:5]), send("small", keys[5:])]):
            with self.assertRaises(ValueError):
                env.act(acts)
            self.assertEqual(state(env), before)

    def test_obs_holds_no_truth_and_log_is_a_copy(self):
        env = LairEnv(SPEC)
        obs, _ = env.act(RuleSeat(SPEC).decide(env.reset("r10", 0)))
        names = []

        def walk(x):
            for k, v in x.items() if isinstance(x, dict) else enumerate(x) if isinstance(x, list) else ():
                names.append(k)
                walk(v)

        walk(obs)
        self.assertFalse({"answer", "wrong_in", "wrong_out"} & {*names})
        env.log.append({"kind": "x"})
        self.assertNotIn({"kind": "x"}, env.log)

    def test_a_seed_outside_the_split_or_another_rung_is_refused(self):
        env = LairEnv(SPEC)
        for args in (("r10", 1000), ("r2209", 0)):
            with self.assertRaises(ValueError):
                env.reset(*args)
        with self.assertRaises(ValueError):
            env.reset("r10", 0, split="val")
        with self.assertRaises(RuntimeError):
            LairEnv(SPEC).act([])
