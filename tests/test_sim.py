"""Unit tests for the Lair core."""

import unittest

from lair import load_spec
from lair.sim import Sim


def mark(sim, name):
    sim.record("mark", name=name)


def noisy(sim, n):
    sim.record("roll", n=n, x=sim.rng.random())
    if n:
        sim.at(sim.rng.random(), noisy, n - 1)


class SimTest(unittest.TestCase):
    def test_time_order(self):
        sim = Sim(1)
        for delay, name in [(3, "c"), (1, "a"), (2, "b")]:
            sim.at(delay, mark, name)
        self.assertEqual(sim.run(), 3)
        self.assertEqual([r["name"] for r in sim.log], ["a", "b", "c"])
        self.assertEqual([r["t"] for r in sim.log], [1, 2, 3])
        self.assertEqual(sim.now, 3)

    def test_fifo_ties(self):
        sim = Sim(1)
        for name in "abc":
            sim.at(1, mark, name)
        sim.run()
        self.assertEqual([r["name"] for r in sim.log], ["a", "b", "c"])

    def test_same_seed_same_log(self):
        logs = []
        for seed in (7, 7, 8):
            sim = Sim(seed)
            sim.at(0, noisy, 20)
            sim.run()
            logs.append(sim.log)
        self.assertEqual(logs[0], logs[1])
        self.assertNotEqual(logs[0], logs[2])

    def test_until_stops_before_later_events(self):
        sim = Sim(1)
        sim.at(1, mark, "a")
        sim.at(5, mark, "b")
        self.assertEqual(sim.run(until=2), 1)
        self.assertEqual(len(sim.log), 1)
        self.assertEqual(sim.run(), 1)
        self.assertEqual(len(sim.log), 2)

    def test_max_events(self):
        sim = Sim(1)
        for name in "abc":
            sim.at(0, mark, name)
        self.assertEqual(sim.run(max_events=2), 2)
        self.assertEqual(len(sim.log), 2)

    def test_events_schedule_events(self):
        def spawn(sim):
            mark(sim, "parent")
            sim.at(2, mark, "child")

        sim = Sim(1)
        sim.at(1, spawn)
        self.assertEqual(sim.run(), 2)
        self.assertEqual([(r["t"], r["name"]) for r in sim.log], [(1, "parent"), (3, "child")])

    def test_negative_delay_raises(self):
        with self.assertRaises(ValueError):
            Sim(1).at(-1, mark, "x")

    def test_nan_delay_raises(self):
        with self.assertRaises(ValueError):
            Sim(1).at(float("nan"), mark, "x")

    def test_record_reserves_t_and_kind(self):
        with self.assertRaises(ValueError):
            Sim(1).record("metric", t=5)

    def test_event_at_exactly_until_runs(self):
        sim = Sim(1)
        sim.at(2, mark, "edge")
        sim.run(until=2)
        self.assertEqual([r["name"] for r in sim.log], ["edge"])

    def test_load_spec(self):
        self.assertEqual(len(load_spec()["actions"]), 5)


if __name__ == "__main__":
    unittest.main()
