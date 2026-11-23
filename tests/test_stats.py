"""Unit tests for the paired gain: hand-worked bootstrap cases."""

import unittest

from ladder.stats import kept, paired_gain


class StatsTest(unittest.TestCase):
    def test_a_gain_that_cancels_has_an_interval_across_zero(self):
        # diffs [-1, 1]: a resampled mean is -1, 0 or 1 with chance 1/4, 1/2, 1/4, so the 2.5th and 97.5th percentiles are -1 and 1
        self.assertEqual(paired_gain([1, 0], [0, 1]), (0.0, -1.0, 1.0))
        self.assertFalse(kept([1, 0], [0, 1]))

    def test_one_win_in_four_is_not_enough(self):
        # diffs [0, 0, 0, 1]: P(no win in a resample) = (3/4)^4 = 0.32 is over 2.5%, so low is 0;
        # P(at most 2 wins) = 0.949 is under 97.5% and P(at most 3) = 0.996 is over, so high is 3/4
        self.assertEqual(paired_gain([0, 0, 0, 0], [0, 0, 0, 1]), (0.25, 0.0, 0.75))
        self.assertFalse(kept([0, 0, 0, 0], [0, 0, 0, 1]))

    def test_three_wins_in_four_clear_zero(self):
        # diffs [1, 1, 1, 0]: P(no win) = 0.004 is under 2.5% and P(at most 1 win) = 0.051 is over, so low is 1/4;
        # P(all four wins) = 0.32 puts the 97.5th percentile at 1
        self.assertEqual(paired_gain([0, 0, 0, 0], [1, 1, 1, 0]), (0.75, 0.25, 1.0))
        self.assertTrue(kept([0, 0, 0, 0], [1, 1, 1, 0]))

    def test_the_same_grades_give_the_same_interval(self):
        a, b = [0.2, 0.5, 0.4, 0.9], [0.3, 0.5, 0.7, 0.8]
        self.assertEqual(paired_gain(a, b), paired_gain(a, b))

    def test_bad_input_is_refused(self):
        for a, b in (([1], [1, 2]), ([], [])):
            with self.assertRaises(ValueError):
                paired_gain(a, b)


if __name__ == "__main__":
    unittest.main()
