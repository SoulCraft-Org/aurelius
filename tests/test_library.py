"""Unit tests for the library."""

import re
import unittest

from lair.library import OLD_CUES, Library, make_library, tokens
from lair.tasks import make_task

VALUE = re.compile(r"\b[0-9a-f]{8}\b")


def naive(lib, task):
    """Share of items where the first value-like string in the top hit is the answer."""
    top = [VALUE.search(lib.search(it.key, 1)[0][1]) for it in task.items]
    return sum(m.group() == it.answer for m, it in zip(top, task.items)) / len(top)


def careful(lib, item):
    """Read every document on the exact key: skip superseded ones, trust a two-value correction."""
    mine = re.compile(rf"(?<![\w-]){item.key}(?![\w-])")
    texts = [t for t in lib.docs.values() if mine.search(t) and not any(c in t.lower() for c in OLD_CUES)]
    fixes = [VALUE.findall(t) for t in texts if len(VALUE.findall(t)) == 2]
    return fixes[0][-1] if fixes else VALUE.search(texts[0]).group()


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
        for knob, lo, hi in (("distractors", 2, 8), ("conflicts", 0.5, 1.0)):
            few = naive(make_library(task, 5, **{knob: lo}), task)
            many = naive(make_library(task, 5, **{knob: hi}), task)
            self.assertLess(few, clean)
            self.assertLess(many, few)

    def test_faulted_truth_is_recoverable(self):
        task = make_task(6, 200, fault_rate=0.3)
        lib = make_library(task, 8, distractors=3, conflicts=0.5, noise=2)
        for it in (i for i in task.items if i.fault):
            self.assertEqual(careful(lib, it), it.answer, it.key)

    def test_no_one_word_finds_most_corrections(self):
        lib = make_library(make_task(6, 200, fault_rate=0.3), 8)
        fixes = {d for d, t in lib.docs.items() if len(VALUE.findall(t)) == 2}
        self.assertGreater(len(fixes), 30)
        for w in {w for d in fixes for w in tokens(lib.docs[d])}:
            hits = {d for d, _ in lib.search(w, len(lib.docs))} & fixes
            self.assertLessEqual(len(hits), len(fixes) / 2, w)

    def test_more_distractors_leave_other_documents_alone(self):
        task = make_task(7, 50, fault_rate=0.2)
        base = make_library(task, 2, conflicts=0.5, noise=1.5)
        more = make_library(task, 2, distractors=4, conflicts=0.5, noise=1.5)
        self.assertEqual([d for d in more.docs if d in base.docs], list(base.docs))
        self.assertTrue(all(more.docs[d] == t for d, t in base.docs.items()))

    def test_bm25_by_hand(self):
        got = Library({"a": "cat sat", "b": "cat"}).scores("cat sat")  # idf: cat ln 1.2, sat ln 2; average length 1.5, so norm is 1.25 in a, 0.75 in b
        self.assertAlmostEqual(got["a"], (0.1823216 + 0.6931472) * 2.5 / 2.875, places=5)
        self.assertAlmostEqual(got["b"], 0.1823216 * 2.5 / 2.125, places=5)


if __name__ == "__main__":
    unittest.main()
