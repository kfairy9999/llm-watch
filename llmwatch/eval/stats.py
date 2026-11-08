"""Paired percentile bootstrap for the mean per-test score delta.

This is a CI gate, not a paper-ready test. It ignores dependence between scorers
and does not correct for multiple comparisons. Pairing matters: the same item
is hard for both models, so the delta is the unit of analysis.
"""

from __future__ import annotations

import math
import random


def quantile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation quantile. `q` is in [0, 1] and `sorted_values` is sorted."""
    if not sorted_values:
        raise ValueError("quantile of an empty sample")
    if not 0 <= q <= 1:
        raise ValueError("q must be between 0 and 1")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return sorted_values[low]
    weight = position - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def bootstrap_mean_ci(
    values: list[float],
    *,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Return (mean, ci_low, ci_high) for the mean of paired deltas."""
    if not values:
        raise ValueError("bootstrap needs at least one value")
    if n_boot < 1:
        raise ValueError("n_boot must be >= 1")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    count = len(values)
    mean = sum(values) / count
    if count == 1:
        return mean, mean, mean
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(n_boot):
        total = 0.0
        for _ in range(count):
            total += values[rng.randrange(count)]
        means.append(total / count)
    means.sort()
    low = quantile(means, alpha / 2)
    high = quantile(means, 1 - alpha / 2)
    return mean, low, high
