"""Schemas for the metrics endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.metrics import MetricsSnapshot


class LatencyRead(BaseModel):
    """A latency summary over the samples this process retained."""

    observed: int = Field(
        description=(
            "Measurements recorded in total, including those that have fallen out of "
            "the retained window"
        )
    )
    retained: int = Field(description="Measurements the summary was computed from")
    mean_ms: float
    p50_ms: float
    p95_ms: float = Field(description="Nearest-rank 95th percentile: a value that was measured")
    max_ms: float


class MetricsResponse(BaseModel):
    """Everything this process has recorded since it started.

    Percentiles describe the retained window rather than all of history; ``retained``
    and ``observed`` say how large that window is and how much traffic it covers.
    """

    window: int = Field(description="How many samples per latency metric are retained")
    counters: dict[str, int]
    latencies: dict[str, LatencyRead]

    @classmethod
    def from_snapshot(cls, snapshot: MetricsSnapshot) -> MetricsResponse:
        return cls(
            window=snapshot.window,
            counters=snapshot.counters,
            latencies={
                name: LatencyRead(
                    observed=latency.observed,
                    retained=latency.retained,
                    mean_ms=latency.mean_ms,
                    p50_ms=latency.p50_ms,
                    p95_ms=latency.p95_ms,
                    max_ms=latency.max_ms,
                )
                for name, latency in snapshot.latencies.items()
            },
        )
