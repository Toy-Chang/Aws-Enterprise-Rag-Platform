"""Metrics endpoint: what this process has recorded."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import MetricsDep
from app.schemas.metrics import MetricsResponse

router = APIRouter(tags=["operations"])


@router.get("/metrics", summary="Report process counters and latency summaries")
def read_metrics(metrics: MetricsDep) -> MetricsResponse:
    """Return the counters and latency summaries of this process.

    The numbers are per process and in memory. Nothing is aggregated across replicas
    and nothing survives a restart, so this is a snapshot for an operator or a local
    run rather than a time series: the deployment's CloudWatch metrics remain the
    record. Counters are named after what happened (``query.insufficient_evidence``)
    or after the route template that handled it, never after a concrete path.

    Latency percentiles are computed from a bounded window of recent samples, which
    ``window`` and each metric's ``retained`` and ``observed`` fields describe.
    """
    return MetricsResponse.from_snapshot(metrics.snapshot())
