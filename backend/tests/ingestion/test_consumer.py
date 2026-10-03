"""Tests for the queue consumer: when a message is finished and when it is retried.

The rule under test comes from the document rather than from the run, so most of these
tests assert on what happens to a document in a real database.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import init_db, session_scope
from app.core.metrics import MetricsRegistry
from app.models.document import Document, DocumentStatus
from app.repositories.queue import IngestionMessage, ReceivedMessage
from app.services.ingestion_consumer import IngestionConsumer
from tests.api.support import upload


class StubIngestion:
    """An ingestion service that does what the test asks instead of ingesting."""

    def __init__(self, *, raises: bool = False) -> None:
        self.runs: list[tuple[str, str]] = []
        self._raises = raises

    def run(self, knowledge_base_id: str, document_id: str) -> None:
        self.runs.append((knowledge_base_id, document_id))
        if self._raises:
            raise RuntimeError("the database went away")


@pytest.fixture
def database(app: FastAPI) -> FastAPI:
    """Create the schema without starting the server."""
    init_db(app.state.engine)
    return app


def _consumer(
    app: FastAPI, ingestion: object | None = None, metrics: MetricsRegistry | None = None
):
    return IngestionConsumer(
        ingestion=ingestion or app.state.ingestion,  # type: ignore[arg-type]
        session_factory=app.state.session_factory,
        metrics=metrics or app.state.metrics,
    )


def _record(knowledge_base_id: str, document_id: str, *, message_id: str = "m1") -> ReceivedMessage:
    return ReceivedMessage(
        message_id=message_id,
        body=IngestionMessage(knowledge_base_id, document_id).to_body(),
    )


def _status(app: FastAPI, document_id: str) -> str | None:
    with session_scope(app.state.session_factory) as session:
        return session.scalar(select(Document.status).where(Document.id == document_id))


def test_a_message_for_a_pending_document_is_handled(
    app: FastAPI, client: TestClient, knowledge_base_id: str
) -> None:
    document = upload(client, knowledge_base_id)

    result = _consumer(app).handle_records([_record(knowledge_base_id, document["id"])])

    assert result.handled == 1
    assert result.deferred == ()
    assert result.failed_message_ids == []
    assert _status(app, document["id"]) == DocumentStatus.READY.value


def test_a_document_that_cannot_be_parsed_is_still_handled(
    app: FastAPI, client: TestClient, knowledge_base_id: str
) -> None:
    # The run recorded the outcome, so the message did its job: a failed document is a
    # result, not an unprocessed message. Retrying it would fail in exactly the same way.
    document = upload(client, knowledge_base_id, filename="broken.pdf", content=b"%PDF-1.4 nope")

    result = _consumer(app).handle_records([_record(knowledge_base_id, document["id"])])

    assert result.handled == 1
    assert _status(app, document["id"]) == DocumentStatus.FAILED.value


def test_a_message_for_an_unknown_document_is_deferred(database: FastAPI) -> None:
    # Not deleted: a message can arrive before the transaction that creates the document
    # has committed, and only a retry makes that converge.
    result = _consumer(database).handle_records([_record("kb-1", "does-not-exist")])

    assert result.handled == 0
    assert result.failed_message_ids == ["m1"]
    assert "does not exist" in result.deferred[0].reason


def test_a_document_left_mid_ingestion_is_deferred(
    app: FastAPI, client: TestClient, knowledge_base_id: str
) -> None:
    # A run that neither finished nor recorded a failure leaves the document where it
    # was, and the message has to come back.
    document = upload(client, knowledge_base_id)
    stub = StubIngestion()

    result = _consumer(app, stub).handle_records([_record(knowledge_base_id, document["id"])])

    assert stub.runs == [(knowledge_base_id, document["id"])]
    assert result.handled == 0
    assert "still pending" in result.deferred[0].reason


def test_an_unreadable_message_is_deferred_without_running_anything(database: FastAPI) -> None:
    stub = StubIngestion()
    record = ReceivedMessage(message_id="m1", body="not json at all")

    result = _consumer(database, stub).handle_records([record])

    assert stub.runs == []
    assert result.handled == 0
    assert "unreadable message" in result.deferred[0].reason


def test_a_run_that_raises_defers_only_its_own_message(
    app: FastAPI, client: TestClient, knowledge_base_id: str
) -> None:
    # The service is documented not to raise, so reaching here is a defect; a batch of
    # messages still has to survive one of them.
    document = upload(client, knowledge_base_id)
    stub = StubIngestion(raises=True)

    result = _consumer(app, stub).handle_records([_record(knowledge_base_id, document["id"])])

    assert result.handled == 0
    assert result.deferred[0].reason == "the ingestion run raised"


def test_a_status_that_cannot_be_read_defers(
    app: FastAPI, client: TestClient, knowledge_base_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = upload(client, knowledge_base_id)
    consumer = _consumer(app)

    def _explode(document_id: str) -> str | None:
        raise RuntimeError("the database is unreachable")

    monkeypatch.setattr(consumer, "_document_status", _explode)

    result = consumer.handle_records([_record(knowledge_base_id, document["id"])])

    assert result.handled == 0
    assert "could not be read" in result.deferred[0].reason


def test_a_batch_reports_each_message_separately(
    app: FastAPI, client: TestClient, knowledge_base_id: str
) -> None:
    document = upload(client, knowledge_base_id)

    result = _consumer(app).handle_records(
        [
            _record("kb-1", "does-not-exist", message_id="m1"),
            _record(knowledge_base_id, document["id"], message_id="m2"),
            _record("kb-1", "also-missing", message_id="m3"),
        ]
    )

    assert result.handled == 1
    # Order is preserved so the reported failures map onto the batch the queue sent.
    assert result.failed_message_ids == ["m1", "m3"]


def test_the_counters_report_what_happened(
    app: FastAPI, client: TestClient, knowledge_base_id: str
) -> None:
    document = upload(client, knowledge_base_id)
    metrics = MetricsRegistry()

    _consumer(app, metrics=metrics).handle_records(
        [
            _record(knowledge_base_id, document["id"], message_id="m1"),
            _record("kb-1", "does-not-exist", message_id="m2"),
        ]
    )

    counters = metrics.snapshot().counters
    assert counters["ingestion.messages.handled"] == 1
    assert counters["ingestion.messages.deferred"] == 1


def test_an_empty_batch_does_nothing(app: FastAPI) -> None:
    result = _consumer(app).handle_records([])

    assert result.handled == 0
    assert result.deferred == ()
