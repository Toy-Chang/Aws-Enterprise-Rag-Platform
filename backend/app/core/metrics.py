"""In-process counters and latency samples.

This is the local stand-in for the metrics a deployment publishes to CloudWatch. It is
deliberately not a time-series store: latency samples live in a bounded window, so a
long-running process cannot grow without limit, and the reported percentiles describe
that window. ``observed`` reports how many samples were taken in total, so a reader can
tell when the window is the limiting factor rather than the traffic.

Counters are plain integers keyed by name. Callers keep cardinality bounded by naming
metrics after route templates and outcomes, never after concrete identifiers.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

from app.core.statistics import summarise

DEFAULT_SAMPLE_LIMIT = 1024


@dataclass(frozen=True, slots=True)
class LatencySnapshot:
    """A summary of one latency metric over the retained window."""

    observed: int
    retained: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    """Every counter and latency summary recorded so far."""

    window: int
    counters: dict[str, int]
    latencies: dict[str, LatencySnapshot]


class MetricsRegistry:
    """Thread-safe counters and bounded latency samples.

    The ingestion worker records from its own thread while requests record from theirs,
    so every mutation takes the same lock.
    """

    def __init__(self, *, sample_limit: int = DEFAULT_SAMPLE_LIMIT) -> None:
        if sample_limit < 1:
            raise ValueError("sample_limit must be positive")
        self._sample_limit = sample_limit
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._samples: dict[str, deque[float]] = {}
        self._observed: dict[str, int] = {}

    @property
    def sample_limit(self) -> int:
        """How many latency samples per metric are retained."""
        return self._sample_limit

    def increment(self, name: str, amount: int = 1) -> None:
        """Add ``amount`` to the counter ``name``, creating it on first use."""
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def observe(self, name: str, milliseconds: float) -> None:
        """Record one latency measurement, in milliseconds."""
        with self._lock:
            samples = self._samples.get(name)
            if samples is None:
                samples = deque(maxlen=self._sample_limit)
                self._samples[name] = samples
            samples.append(milliseconds)
            self._observed[name] = self._observed.get(name, 0) + 1

    def counter(self, name: str) -> int:
        """Return one counter, or zero when it was never incremented."""
        with self._lock:
            return self._counters.get(name, 0)

    def latency(self, name: str) -> LatencySnapshot | None:
        """Return one latency summary, or ``None`` when nothing was recorded."""
        with self._lock:
            samples = list(self._samples.get(name, ()))
            observed = self._observed.get(name, 0)
        return _summarise(samples, observed=observed)

    def snapshot(self) -> MetricsSnapshot:
        """Return every counter and latency summary, ordered by name."""
        with self._lock:
            counters = dict(sorted(self._counters.items()))
            samples = {name: list(values) for name, values in sorted(self._samples.items())}
            observed = dict(self._observed)

        latencies: dict[str, LatencySnapshot] = {}
        for name, values in samples.items():
            summary = _summarise(values, observed=observed.get(name, 0))
            if summary is not None:
                latencies[name] = summary

        return MetricsSnapshot(window=self._sample_limit, counters=counters, latencies=latencies)

    def reset(self) -> None:
        """Forget everything recorded so far."""
        with self._lock:
            self._counters.clear()
            self._samples.clear()
            self._observed.clear()


def _summarise(samples: list[float], *, observed: int) -> LatencySnapshot | None:
    if not samples:
        return None
    summary = summarise(samples)
    return LatencySnapshot(
        observed=observed,
        retained=summary.count,
        mean_ms=summary.mean,
        p50_ms=summary.p50,
        p95_ms=summary.p95,
        max_ms=summary.maximum,
    )
