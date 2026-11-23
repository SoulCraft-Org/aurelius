"""Unit tests for the step-by-step Lair environment."""

import unittest

from ladder.env import LairEnv
from ladder.run import run_once
from lair import load_spec
from lair.seat import RuleSeat

SPEC = load_spec()


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

    def test_a_seed_outside_the_split_or_another_rung_is_refused(self):
        env = LairEnv(SPEC)
        for args in (("r10", 1000), ("r2209", 0)):
            with self.assertRaises(ValueError):
                env.reset(*args)
        with self.assertRaises(ValueError):
            env.reset("r10", 0, split="val")
        with self.assertRaises(RuntimeError):
            LairEnv(SPEC).act([])
