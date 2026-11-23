"""Unit tests for tools/make_tree.py: the 3D tree is deterministic, sized by the spec, and committed."""

import pathlib
import sys
import unittest

from ladder.run import tree
from lair import load_spec

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import make_tree  # noqa: E402

SPEC = load_spec()
STL = ROOT / "docs" / "img" / "tree.stl"


class MakeTreeTest(unittest.TestCase):
    def test_same_text_twice(self):
        self.assertEqual(make_tree.render(SPEC), make_tree.render(SPEC))

    def test_counts_follow_the_ladder_tree(self):
        seats = tree(SPEC, make_tree.RUNG)
        top, mid, workers, _ = make_tree.counts(SPEC)
        self.assertEqual((top, mid, workers), (seats[-1], seats[0], 2209))

    def test_facet_count_matches_the_formula(self):
        top, seats, workers, _ = make_tree.counts(SPEC)
        want = (top + seats) * 20 + (seats + workers) * 8 + workers * 4
        self.assertEqual(make_tree.facet_count(SPEC), want)
        self.assertEqual(make_tree.render(SPEC).count("endfacet"), want)

    def test_size_under_the_github_limit(self):
        self.assertLess(len(make_tree.render(SPEC).encode()), 10 * 1024 * 1024)

    def test_committed_file_is_the_generators_output(self):
        self.assertEqual(STL.read_text(), make_tree.render(SPEC))
