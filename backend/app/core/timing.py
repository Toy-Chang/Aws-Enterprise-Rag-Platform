"""Timing helpers for the stage durations reported in a query trace."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager


def elapsed_ms(started: float) -> float:
    """Milliseconds elapsed since a :func:`time.perf_counter` reading."""
    return round((time.perf_counter() - started) * 1000, 3)


@contextmanager
def stopwatch() -> Iterator[list[float]]:
    """Measure a block, exposing the duration once it has finished.

    >>> durations: list[float] = []
    >>> with stopwatch() as durations:
    ...     pass
    >>> len(durations)
    1
    """
    started = time.perf_counter()
    durations = [0.0]
    try:
        yield durations
    finally:
        durations[0] = elapsed_ms(started)
