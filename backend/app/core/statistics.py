"""Numeric summaries shared by the metrics registry and the evaluation report."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Summary:
    """A summary of a non-empty sequence of samples."""

    count: int
    mean: float
    minimum: float
    p50: float
    p95: float
    maximum: float


def percentile(samples: Sequence[float], quantile: float) -> float:
    """Return the nearest-rank percentile of ``samples``.

    Nearest-rank is used rather than an interpolating definition because these samples
    are measurements: reporting a value between two observations, or below the smallest
    one, would imply a precision the measurement does not have.
    """
    if not samples:
        raise ValueError("a percentile needs at least one sample")
    if not 0.0 < quantile <= 1.0:
        raise ValueError("quantile must be in (0, 1]")

    ordered = sorted(samples)
    rank = max(math.ceil(quantile * len(ordered)), 1)
    return float(ordered[min(rank, len(ordered)) - 1])


def summarise(samples: Sequence[float]) -> Summary:
    """Return the count, mean, minimum, median, 95th percentile and maximum."""
    if not samples:
        raise ValueError("a summary needs at least one sample")

    ordered = sorted(samples)
    return Summary(
        count=len(ordered),
        mean=mean(ordered),
        minimum=float(ordered[0]),
        p50=percentile(ordered, 0.5),
        p95=percentile(ordered, 0.95),
        maximum=float(ordered[-1]),
    )


def mean(values: Sequence[float]) -> float:
    """Return the arithmetic mean, rounded for reporting.

    Rounding happens here rather than at every call site so that a reported aggregate
    does not depend on how many places formatted it.
    """
    if not values:
        raise ValueError("a mean needs at least one value")
    return round(sum(values) / len(values), 6)
