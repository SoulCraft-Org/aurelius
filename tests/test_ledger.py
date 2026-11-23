"""Unit tests for the ledger, resume, and the Sim additions it needs."""

import unittest

from lair.ledger import Ledger, ResumeMismatch, resume
from lair.sim import Sim


def tick(sim, ledger, n):
    ledger.add("tick", t=sim.now, n=n, x=sim.rng.random())
    if n:
        sim.at(sim.rng.random(), tick, ledger, n - 1)


def start():
    sim, ledger = Sim(5), Ledger()
    sim.at(0, tick, ledger, 20)
    return sim, ledger


def mark(sim, name):
    sim.record("mark", name=name)


class LedgerTest(unittest.TestCase):
    def test_jsonl_round_trip(self):
        ledger = Ledger()
        ledger.add("a", z=1, b=[1, 2.5], c={"k": None})
        ledger.add("b")
        text = ledger.to_jsonl()
        self.assertEqual(text.splitlines()[0], '{"b": [1, 2.5], "c": {"k": null}, "kind": "a", "z": 1}')
        self.assertEqual(Ledger.from_jsonl(text).entries, ledger.entries)
        self.assertEqual(Ledger().to_jsonl(), "")
        self.assertEqual(Ledger.from_jsonl("").entries, [])

    def test_add_stores_json_form_and_reserves_kind(self):
        ledger = Ledger()
        ledger.add("a", pair=(1, 2))
        self.assertEqual(ledger.entries, [{"kind": "a", "pair": [1, 2]}])
        with self.assertRaises(ValueError):
            ledger.add("a", kind="b")
        with self.assertRaises(ValueError):
            ledger.add("a", x=float("nan"))

    def test_is_prefix_of(self):
        a, b = Ledger(), Ledger()
        a.add("x", n=1)
        b.add("x", n=1)
        b.add("y")
        self.assertTrue(Ledger().is_prefix_of(b))
        self.assertTrue(a.is_prefix_of(b))
        self.assertTrue(b.is_prefix_of(b))
        self.assertFalse(b.is_prefix_of(a))

    def test_kill_then_resume_matches_uninterrupted(self):
        sim, full = start()
        sim.run()
        killed_sim, partial = start()
        killed_sim.run(until=1.5)
        self.assertTrue(0 < len(partial.entries) < len(full.entries))
        saved = Ledger.from_jsonl(partial.to_jsonl())  # what survived on disk
        self.assertEqual(resume(start, saved).to_jsonl(), full.to_jsonl())

    def test_resume_until_stops_at_the_saved_point(self):
        killed_sim, partial = start()
        killed_sim.run(until=1.5)
        self.assertEqual(resume(start, partial, until=1.5).entries, partial.entries)

    def test_tampered_ledger_raises(self):
        saved_sim, saved = start()
        saved_sim.run(until=1.5)
        saved.entries[0]["x"] += 0.001
        with self.assertRaises(ResumeMismatch):
            resume(start, saved)

    def test_saved_longer_than_replay_raises(self):
        saved_sim, saved = start()
        saved_sim.run()
        with self.assertRaises(ResumeMismatch):
            resume(start, saved, until=1.5)


class SimAdditionsTest(unittest.TestCase):
    def test_pending_lists_queue_in_run_order(self):
        sim = Sim(1)
        sim.at(2, mark, "b")
        sim.at(1, mark, "a")
        sim.at(1, mark, "c")
        self.assertEqual(sim.pending(), [(1, 1, "mark", ("a",)), (1, 2, "mark", ("c",)), (2, 0, "mark", ("b",))])
        sim.run(until=1)
        self.assertEqual(sim.pending(), [(2, 0, "mark", ("b",))])

    def test_pending_empty(self):
        self.assertEqual(Sim(1).pending(), [])

    def test_now_is_until_after_run(self):
        sim = Sim(1)
        sim.at(1, mark, "a")
        sim.at(5, mark, "b")
        sim.run(until=2)
        self.assertEqual(sim.now, 2)
        sim.run(until=1)  # never moves time back
        self.assertEqual(sim.now, 2)
        sim.run(until=10)
        self.assertEqual(sim.now, 10)

    def test_run_without_until_leaves_now_at_last_event(self):
        sim = Sim(1)
        sim.at(3, mark, "a")
        sim.run()
        self.assertEqual(sim.now, 3)

    def test_max_events_stop_does_not_skip_time(self):
        sim = Sim(1)
        sim.at(1, mark, "a")
        sim.at(2, mark, "b")
        sim.run(until=5, max_events=1)
        self.assertEqual(sim.now, 1)


if __name__ == "__main__":
    unittest.main()
