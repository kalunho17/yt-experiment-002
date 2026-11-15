"""Uncertainty estimates (standard library only).

* A share (accuracy, share of good calls): Wilson score interval.
* The difference of two independent shares: Newcombe's hybrid score interval (method 10 in
  Newcombe 1998), built from the two Wilson intervals. The items answered at two load levels are
  different draws from the same pool, so the two shares are treated as independent.
* A mean over many items (tokens per task): normal approximation, mean +- 1.96 * sd / sqrt(n).
"""
from __future__ import annotations

import math
import statistics

Z = 1.959964


def wilson(k: int, n: int, z: float = Z) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def newcombe_diff(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float, float]:
    """Difference p1 - p2 of two independent shares with a 95% interval: (point, lo, hi)."""
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1)
    l2, u2 = wilson(k2, n2)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, lo, hi


def mean_ci(xs: list[float]) -> tuple[float, float, float]:
    """(mean, lo, hi), normal approximation."""
    n = len(xs)
    m = statistics.fmean(xs)
    if n < 2:
        return m, float("nan"), float("nan")
    h = Z * statistics.stdev(xs) / math.sqrt(n)
    return m, m - h, m + h


def percentile(xs: list[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0, 1]."""
    if not xs:
        return float("nan")
    xs = sorted(xs)
    i = q * (len(xs) - 1)
    lo, hi = math.floor(i), math.ceil(i)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)
