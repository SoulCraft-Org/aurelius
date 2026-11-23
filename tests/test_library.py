"""Unit tests for the library."""

import re
import unittest

from lair.library import make_library
from lair.tasks import make_task

VALUE = re.compile(r"\b[0-9a-f]{8}\b")


def naive(lib, task):
    """Share of items where the first value-like string in the top hit is the answer."""
    right = 0
    for it in task.items:
        hits = lib.search(it.key, 1)
        found = VALUE.search(hits[0][1]) if hits else None
        right += bool(found) and found.group() == it.answer
    return right / len(task.items)


def careful(lib, item):
    """Read every document on the exact key: skip superseded ones, trust a correction."""
    mine = re.compile(rf"(?<![\w-]){item.key}(?![\w-])")
    texts = [t for t in lib.docs.values() if mine.search(t) and "Superseded" not in t]
    for t in texts:
        if "Correction:" in t:
            return VALUE.findall(t.split("corrected value is")[1])[0]
    return VALUE.search(texts[0]).group()


class LibraryTest(unittest.TestCase):
    def test_same_corpus_twice(self):
        task = make_task(4, 60, fault_rate=0.2)
        knobs = dict(distractors=2, conflicts=0.5, noise=1.5)
        self.assertEqual(make_library(task, 9, **knobs).docs, make_library(task, 9, **knobs).docs)
        self.assertNotEqual(make_library(task, 9, **knobs).docs, make_library(task, 10, **knobs).docs)

    def test_answer_in_top_three_at_zero_knobs(self):
        task = make_task(1, 80, fault_rate=0.2)
        lib = make_library(task, 3)
        for it in task.items:
            top = [text for _, text in lib.search(it.key, 3)]
            self.assertTrue(any(it.answer in t for t in top), it.key)

    def test_naive_reader_falls_with_distractors_and_conflicts(self):
        task = make_task(2, 120, fault_rate=0.0)
        clean = naive(make_library(task, 5), task)
        self.assertEqual(clean, 1.0)
        few = naive(make_library(task, 5, distractors=2), task)
        many = naive(make_library(task, 5, distractors=8), task)
        self.assertLess(few, clean)
        self.assertLess(many, few)
        half = naive(make_library(task, 5, conflicts=0.5), task)
        every = naive(make_library(task, 5, conflicts=1.0), task)
        self.assertLess(half, clean)
        self.assertLess(every, half)

    def test_faulted_truth_is_recoverable(self):
        task = make_task(6, 200, fault_rate=0.3)
        lib = make_library(task, 8, distractors=3, conflicts=0.5, noise=2)
        faulted = [it for it in task.items if it.fault]
        self.assertGreater(len(faulted), 20)
        for it in faulted:
            self.assertEqual(careful(lib, it), it.answer, it.key)


if __name__ == "__main__":
    unittest.main()
