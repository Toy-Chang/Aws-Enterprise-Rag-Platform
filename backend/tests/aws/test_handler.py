"""Tests for the Lambda entry point of the ingestion queue."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.aws import handler as lambda_handler
from app.core.config import Settings, get_settings
from app.repositories.queue import IngestionMessage, ReceivedMessage
from app.services.ingestion_consumer import ConsumerResult, DeferredMessage, IngestionConsumer

EVENT_MESSAGE = {"messageId": "m1", "receiptHandle": "r1", "body": "{}"}


class StubConsumer:
    """A consumer that returns a fixed result and records the batches it was given."""

    def __init__(self, result: ConsumerResult) -> None:
        self.result = result
        self.batches: list[list[ReceivedMessage]] = []

    def handle_records(self, records: list[ReceivedMessage]) -> ConsumerResult:
        self.batches.append(list(records))
        return self.result


def _event(*records: dict[str, Any]) -> dict[str, Any]:
    return {"Records": list(records)}


def test_the_handler_reports_only_the_messages_to_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = StubConsumer(
        ConsumerResult(handled=1, deferred=(DeferredMessage("m2", "still processing"),))
    )
    monkeypatch.setattr(lambda_handler, "get_consumer", lambda: stub)

    response = lambda_handler.handler(_event(EVENT_MESSAGE, {**EVENT_MESSAGE, "messageId": "m2"}))

    # The event source mapping retries exactly these and deletes the rest.
    assert response == {"batchItemFailures": [{"itemIdentifier": "m2"}]}
    assert [record.message_id for record in stub.batches[0]] == ["m1", "m2"]


def test_a_fully_handled_batch_reports_no_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = StubConsumer(ConsumerResult(handled=1, deferred=()))
    monkeypatch.setattr(lambda_handler, "get_consumer", lambda: stub)

    assert lambda_handler.handler(_event(EVENT_MESSAGE)) == {"batchItemFailures": []}


def test_an_event_that_is_not_an_sqs_event_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        lambda_handler, "get_consumer", lambda: pytest.fail("no consumer should be built")
    )

    # There is nothing to report a retry against, so the invocation fails loudly.
    with pytest.raises(ValueError, match="no Records list"):
        lambda_handler.handler({})


def test_the_resources_are_built_once_and_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        lambda_handler,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            environment="test",
            log_level="WARNING",
            log_format="json",
            database_url=f"sqlite:///{tmp_path / 'handler.db'}",
            storage_dir=str(tmp_path / "documents"),
        ),
    )
    lambda_handler.reset()
    try:
        first = lambda_handler.get_resources()

        # A warm invocation pays for nothing but the work itself.
        assert lambda_handler.get_resources() is first
        assert lambda_handler.get_resources().consumer is first.consumer
        assert isinstance(first.consumer, IngestionConsumer)

        lambda_handler.reset()

        # A new container starts from nothing, which is what the reset models.
        assert lambda_handler.get_resources() is not first
    finally:
        lambda_handler.reset()


def test_the_consumer_is_built_with_the_local_adapters_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        lambda_handler,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            environment="test",
            log_level="WARNING",
            log_format="json",
            database_url=f"sqlite:///{tmp_path / 'handler.db'}",
            storage_dir=str(tmp_path / "documents"),
        ),
    )
    lambda_handler.reset()
    try:
        ingestion = lambda_handler.get_consumer()._ingestion

        # The consumer ingests through the same service the API uses, built from the same
        # configuration, so a document is ingested identically whichever path asked.
        assert type(ingestion._embedder).__name__ == "HashingEmbeddingModel"
        assert type(ingestion._vector_store).__name__ == "InMemoryVectorStore"
        assert type(ingestion._storage).__name__ == "LocalFileSystemStorage"
    finally:
        lambda_handler.reset()


def test_the_schema_is_created_on_a_cold_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The consumer can be the first thing to run after a deployment, so it cannot assume
    # the API process created the tables.
    monkeypatch.setattr(
        lambda_handler,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            environment="test",
            log_level="WARNING",
            log_format="json",
            database_url=f"sqlite:///{tmp_path / 'handler.db'}",
            storage_dir=str(tmp_path / "documents"),
        ),
    )
    lambda_handler.reset()
    try:
        consumer = lambda_handler.get_consumer()
        body = IngestionMessage(knowledge_base_id="kb-1", document_id="doc-1").to_body()

        result = consumer.handle_records([ReceivedMessage(message_id="m1", body=body)])

        # The document is unknown, which is only knowable by reading the table: without
        # creating the schema this would fail with an OperationalError instead.
        assert result.deferred[0].reason == "the document does not exist"
    finally:
        lambda_handler.reset()


def test_the_settings_resolve_the_database_url_from_a_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An ECS task definition resolves `secrets.valueFrom` itself; a Lambda cannot, so the
    # function reads the same secret on cold start.
    monkeypatch.setenv("APP_DATABASE_SECRET_ARN", "arn:aws:secretsmanager:eu-west-1:1:secret:db")
    monkeypatch.setenv("APP_QUEUE_BACKEND", "sqs")
    monkeypatch.setenv("APP_SQS_QUEUE_URL", "https://sqs.eu-west-1.amazonaws.com/1/queue")
    get_settings.cache_clear()
    monkeypatch.setattr(
        lambda_handler, "resolve_database_url", lambda arn: f"postgresql+psycopg://user:pw@{arn}"
    )

    settings = lambda_handler.load_settings()

    assert settings.database_url == (
        "postgresql+psycopg://user:pw@arn:aws:secretsmanager:eu-west-1:1:secret:db"
    )
    # The cached settings object is not mutated: the API process in the same image must not
    # inherit a resolved URL it never asked for.
    assert get_settings().database_url != settings.database_url


def test_without_a_secret_the_configured_url_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_DATABASE_SECRET_ARN", raising=False)
    monkeypatch.setenv("APP_DATABASE_URL", "sqlite:///./from-environment.db")
    get_settings.cache_clear()
    monkeypatch.setattr(
        lambda_handler,
        "resolve_database_url",
        lambda arn: pytest.fail("no secret should be read"),
    )

    assert lambda_handler.load_settings().database_url == "sqlite:///./from-environment.db"
