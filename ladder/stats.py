"""Paired gain of one seat over another across seeds."""

import random

RESAMPLES = 2000
SEED = 0  # fixed, so the same grades always give the same interval


def paired_gain(a, b):
    """(mean, low, high) of mean(b - a) over equal-length per-seed lists.

    The interval is a 95% percentile bootstrap of the paired differences: 2000 resamples
    with random.Random(0), the 2.5th and 97.5th percentiles of the resampled means.
    """
    if len(a) != len(b) or not a:
        raise ValueError("a and b must be equal-length and not empty")
    diffs = [y - x for x, y in zip(a, b)]
    rng = random.Random(SEED)
    means = sorted(sum(rng.choices(diffs, k=len(diffs))) / len(diffs) for _ in range(RESAMPLES))
    tail = RESAMPLES // 40  # 2.5% of the resamples
    return sum(diffs) / len(diffs), means[tail], means[RESAMPLES - tail - 1]


def kept(a, b):
    """True only when the whole 95% interval of the gain is above 0."""
    return paired_gain(a, b)[1] > 0
