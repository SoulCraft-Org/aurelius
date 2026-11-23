"""Unit tests for the rate fit. Replies come from the stand-in workers with a fixed seed; no HTTP leaves the machine."""

import io
import json
import random
import unittest
from unittest import mock

from lair import load_spec
from lair.fit import as_spec, fit
from lair.library import make_library
from lair.real_workers import RealWorker
from lair.tasks import Item, make_task
from lair.workers import do_item, worker_types

SPEC = load_spec()
CRASH = 0.1


def records(kind, brief, n, rng):
    wtype = worker_types(SPEC)[kind]
    items = [Item(f"k{i}", f"{rng.getrandbits(32):08x}", False, False, None) for i in range(n)]
    return [{"kind": kind, "brief": brief, "answer": it.answer, "reply": do_item(rng, wtype, it, CRASH)} for it in items]


def inside(stat, truth):
    return stat["lo"] <= truth <= stat["hi"]


class FitTest(unittest.TestCase):
    def test_it_recovers_known_skill_and_crash_rates(self):
        rng = random.Random(7)
        got = fit(records("small", "terse", 3000, rng) + records("large", "terse", 3000, rng))
        for kind in ("small", "large"):
            stats = got[kind]["terse"]
            self.assertTrue(inside(stats["skill"], worker_types(SPEC)[kind]["skill"]), stats["skill"])
            self.assertTrue(inside(stats["crash"], CRASH), stats["crash"])
            self.assertAlmostEqual(stats["seconds"]["value"], worker_types(SPEC)[kind]["seconds"])

    def test_each_brief_is_fitted_on_its_own(self):
        rng = random.Random(1)
        got = fit(records("small", "terse", 400, rng) + records("small", "full", 300, rng))
        self.assertEqual(set(got["small"]), {"terse", "full"})
        self.assertEqual((got["small"]["terse"]["crash"]["n"], got["small"]["full"]["crash"]["n"]), (400, 300))

    def test_empty_input_refuses(self):
        with self.assertRaises(ValueError):
            fit([])

    def test_as_spec_keeps_the_shape_and_labels_the_fit(self):
        got = fit(records("small", "full", 200, random.Random(2)))
        types = as_spec(got, SPEC, "full", "2026-11-24")
        self.assertEqual([t["id"] for t in types], [t["id"] for t in SPEC["worker_types"]])
        self.assertEqual(set(types[0]), set(SPEC["worker_types"][0]))
        self.assertEqual(types[0]["source"], "fitted 2026-11-24, brief full")
        self.assertEqual(types[1], SPEC["worker_types"][1])  # no fit for medium: unchanged
        with self.assertRaises(ValueError):
            as_spec(got, SPEC, "terse")

    def test_the_full_brief_never_contains_the_answer(self):
        task, sent = make_task(5, 6), []

        def fake(req, timeout):
            sent.append(req.data.decode())
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 9}}).encode())

        worker = RealWorker("small", "http://localhost:8000/v1/chat/completions", "m", make_library(task, 5), brief="full")
        with mock.patch("urllib.request.urlopen", fake):
            replies = [worker.do_item(it) for it in task.items]
        self.assertEqual({r["brief"] for r in replies}, {"full"})
        self.assertEqual(len(sent), len(task.items))
        for it in task.items:
            self.assertNotIn(it.answer, json.dumps(worker.order(it.key)))
            self.assertTrue(all(it.answer not in body for body in sent))
        self.assertTrue(all("goal" in body and "done_check" in body for body in sent))
        with self.assertRaises(ValueError):
            RealWorker("small", "http://localhost:8000", "m", make_library(task, 5), brief="loud")
