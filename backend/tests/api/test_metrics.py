"""Tests for the metrics endpoint and the instrumentation that feeds it."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.api.support import ask, upload

METRICS_URL = "/api/v1/metrics"


def read_metrics(client: TestClient) -> dict[str, Any]:
    """Return a metrics snapshot.

    Reading the endpoint is itself a request, so a snapshot always includes the read
    that produced it: ``http.requests.total`` is one higher than the number of requests
    the test made.
    """
    response = client.get(METRICS_URL)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_request_that_reads_the_metrics_is_counted_as_in_flight(client: TestClient) -> None:
    """A snapshot taken inside a request cannot include that request's own outcome.

    Counting the response happens once it exists, which is after the handler has
    produced the snapshot, so the read shows up as a request and nothing more. Stating
    this as a test keeps it a documented property rather than a puzzling gap.
    """
    body = read_metrics(client)

    assert body["counters"] == {"http.requests.total": 1}
    assert body["latencies"] == {}


def test_the_read_is_recorded_once_it_has_finished(app: FastAPI, client: TestClient) -> None:
    read_metrics(client)

    # Read the registry rather than the endpoint: another request would add to what
    # this assertion is about.
    latency = app.state.metrics.latency("http.request")
    assert latency is not None
    assert latency.observed == 1
    assert app.state.metrics.counter("http.route./metrics") == 1
    assert app.state.metrics.counter("http.responses.2xx") == 1


def test_a_fresh_process_reports_no_latency_it_never_measured(client: TestClient) -> None:
    """A stage that never ran is absent, not zero."""
    body = read_metrics(client)

    assert "retrieval" not in body["latencies"]
    assert "generation" not in body["latencies"]


def test_requests_are_labelled_by_route_template_rather_than_by_path(
    client: TestClient, knowledge_base_id: str
) -> None:
    upload(client, knowledge_base_id)

    counters = read_metrics(client)["counters"]

    # The label is the template as the router declares it: the API version prefix is
    # not part of it, so changing APP_API_V1_PREFIX does not split every counter.
    assert counters["http.route./knowledge-bases"] == 1
    assert counters["http.route./knowledge-bases/{knowledge_base_id}/documents"] == 1
    assert counters["http.responses.2xx"] == 2  # the two 201s; responses are bucketed by class
    # The identifier never becomes a label, so a caller cannot invent metric series.
    assert not any(knowledge_base_id in name for name in counters)


def test_unmatched_requests_share_one_bucket(client: TestClient) -> None:
    client.get("/does-not-exist")
    client.get("/also-not-here")

    counters = read_metrics(client)["counters"]

    assert counters["http.route.unmatched"] == 2
    assert counters["http.responses.4xx"] == 2
    assert not any("does-not-exist" in name or "also-not-here" in name for name in counters)


def test_the_window_is_reported_with_the_latencies(client: TestClient) -> None:
    body = read_metrics(client)

    assert body["window"] == 1024


def test_a_server_side_failure_is_counted_as_a_5xx(app: FastAPI, settings: Any) -> None:
    @app.get("/_probe/metrics-boom")
    async def _boom() -> None:
        raise RuntimeError("probe")

    with TestClient(app, raise_server_exceptions=False) as failing_client:
        assert failing_client.get("/_probe/metrics-boom").status_code == 500

    # Read the registry rather than the endpoint: the assertion is about what the
    # failure recorded, and another request would only add to it.
    counters = app.state.metrics.snapshot().counters
    assert counters["http.responses.5xx"] == 1
    assert counters["http.route./_probe/metrics-boom"] == 1


def test_a_successful_ingestion_is_counted(
    client: TestClient, knowledge_base_id: str, ingest_pending: Any
) -> None:
    upload(client, knowledge_base_id)
    assert ingest_pending() == 1

    body = read_metrics(client)

    assert body["counters"]["ingestion.succeeded"] == 1
    assert body["counters"]["ingestion.chunks.total"] >= 1
    assert body["latencies"]["ingestion"]["observed"] == 1
    assert "ingestion.failed" not in body["counters"]


def test_a_failed_ingestion_is_counted_as_a_failure(
    client: TestClient, knowledge_base_id: str, ingest_pending: Any
) -> None:
    upload(client, knowledge_base_id, "broken.pdf", b"definitely not a PDF")
    ingest_pending()

    counters = read_metrics(client)["counters"]

    assert counters["ingestion.failed"] == 1
    assert "ingestion.succeeded" not in counters
    assert "ingestion.chunks.total" not in counters


def test_an_answered_query_records_every_stage_it_used(
    client: TestClient, knowledge_base_id: str, ingest_pending: Any
) -> None:
    upload(client, knowledge_base_id)
    ingest_pending()

    ask(client, knowledge_base_id, "How often do database credentials rotate?")

    body = read_metrics(client)

    assert body["counters"]["query.answered"] == 1
    assert body["counters"]["retrieval.candidates.total"] >= 1
    assert body["counters"]["retrieval.selected.total"] >= 1
    assert body["latencies"]["retrieval"]["observed"] == 1
    assert body["latencies"]["generation"]["observed"] == 1
    assert body["latencies"]["query"]["observed"] == 1
    # The extractive adapter reports no token usage, so nothing is counted: a missing
    # usage report is not the same measurement as zero tokens.
    assert "generation.input_tokens.total" not in body["counters"]
    assert "generation.output_tokens.total" not in body["counters"]


def test_a_question_without_evidence_records_no_generation_at_all(
    client: TestClient, knowledge_base_id: str, ingest_pending: Any
) -> None:
    """The invariant of the query pipeline, asserted through the metrics."""
    upload(client, knowledge_base_id)
    ingest_pending()

    result = ask(
        client,
        knowledge_base_id,
        "How often do database credentials rotate?",
        min_score=0.99,
    )
    assert result["outcome"] == "insufficient_evidence"

    body = read_metrics(client)

    assert body["counters"]["query.insufficient_evidence"] == 1
    assert "query.answered" not in body["counters"]
    assert "generation" not in body["latencies"]
