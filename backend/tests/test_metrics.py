"""Tests for the in-process metrics registry."""

from __future__ import annotations

import threading

import pytest

from app.core.metrics import MetricsRegistry


def test_counters_start_absent_and_read_as_zero() -> None:
    registry = MetricsRegistry()

    assert registry.counter("never.incremented") == 0
    assert registry.snapshot().counters == {}
    assert registry.snapshot().latencies == {}


def test_increment_accumulates_and_supports_weights() -> None:
    registry = MetricsRegistry()

    registry.increment("http.requests.total")
    registry.increment("http.requests.total")
    registry.increment("generation.output_tokens.total", 17)

    assert registry.counter("http.requests.total") == 2
    assert registry.counter("generation.output_tokens.total") == 17


def test_observe_keeps_a_nearest_rank_summary() -> None:
    registry = MetricsRegistry()
    for value in (1.0, 2.0, 3.0, 4.0):
        registry.observe("retrieval", value)

    latency = registry.latency("retrieval")

    assert latency is not None
    assert latency.retained == 4
    assert latency.observed == 4
    assert latency.mean_ms == 2.5
    assert latency.p50_ms == 2.0
    assert latency.p95_ms == 4.0
    assert latency.max_ms == 4.0


def test_an_unrecorded_latency_is_absent_rather_than_zero() -> None:
    """Reporting 0 ms for a stage that never ran would be a measurement that did not happen."""
    registry = MetricsRegistry()

    assert registry.latency("generation") is None
    assert "generation" not in registry.snapshot().latencies


def test_samples_are_bounded_but_the_total_is_still_reported() -> None:
    registry = MetricsRegistry(sample_limit=3)
    for value in (1.0, 2.0, 3.0, 4.0, 5.0):
        registry.observe("http.request", value)

    latency = registry.latency("http.request")

    assert latency is not None
    assert latency.retained == 3
    assert latency.observed == 5
    assert latency.max_ms == 5.0
    assert registry.snapshot().window == 3


def test_the_window_keeps_the_most_recent_samples() -> None:
    registry = MetricsRegistry(sample_limit=2)
    for value in (1.0, 2.0, 3.0):
        registry.observe("http.request", value)

    latency = registry.latency("http.request")

    assert latency is not None
    assert (latency.mean_ms, latency.max_ms) == (2.5, 3.0)


def test_the_snapshot_is_ordered_by_name() -> None:
    registry = MetricsRegistry()
    registry.increment("z.counter")
    registry.increment("a.counter")
    registry.observe("z.latency", 1.0)
    registry.observe("a.latency", 1.0)

    snapshot = registry.snapshot()

    assert list(snapshot.counters) == ["a.counter", "z.counter"]
    assert list(snapshot.latencies) == ["a.latency", "z.latency"]


def test_reset_forgets_everything() -> None:
    registry = MetricsRegistry()
    registry.increment("http.requests.total")
    registry.observe("http.request", 1.0)

    registry.reset()

    assert registry.counter("http.requests.total") == 0
    assert registry.latency("http.request") is None


def test_a_non_positive_sample_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="sample_limit"):
        MetricsRegistry(sample_limit=0)


def test_concurrent_recording_does_not_lose_updates() -> None:
    """Requests and the ingestion worker record from different threads."""
    registry = MetricsRegistry(sample_limit=10_000)
    per_thread = 500

    def record() -> None:
        for _ in range(per_thread):
            registry.increment("http.requests.total")
            registry.observe("http.request", 1.0)

    threads = [threading.Thread(target=record) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    latency = registry.latency("http.request")

    assert registry.counter("http.requests.total") == 4 * per_thread
    assert latency is not None
    assert latency.observed == 4 * per_thread
