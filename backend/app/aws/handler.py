"""Lambda entry point for the ingestion queue.

The SQS event source mapping delivers a batch of messages and deletes the ones this
function does not report as failures. That is why the handler deletes nothing itself, and
why the mapping has to be created with ``ReportBatchItemFailures``: without it, a batch
that reports a partial failure is treated as a success and every message in it is deleted.

The resources are built once per container and reused, so a warm invocation pays for
nothing but the work itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine

from app.adapters import (
    build_embedder,
    build_ingestion_service,
    build_storage,
    build_vector_store,
)
from app.core.config import Settings, get_settings
from app.core.db import create_db_engine, create_session_factory, init_db
from app.core.logging import configure_logging, get_logger
from app.core.metrics import MetricsRegistry
from app.aws.secrets import resolve_database_url
from app.repositories.queue import messages_from_lambda_event
from app.services.ingestion_consumer import IngestionConsumer

logger = get_logger(__name__)

_resources: _Resources | None = None


@dataclass(frozen=True)
class _Resources:
    """What a cold start builds and every warm invocation reuses."""

    consumer: IngestionConsumer
    engine: Engine


def get_consumer() -> IngestionConsumer:
    """Return the consumer, building the platform's resources on first use."""
    return get_resources().consumer


def load_settings() -> Settings:
    """Return the settings this process runs with.

    The one difference from the API's settings: a Lambda cannot have an environment
    variable resolved from Secrets Manager the way an ECS task definition can, so when the
    deployment points this function at a secret, the connection URL is read from it here.
    """
    settings = get_settings()
    if settings.database_secret_arn:
        settings = settings.model_copy(
            update={"database_url": resolve_database_url(settings.database_secret_arn)}
        )
    return settings


def get_resources() -> _Resources:
    """Return the process-wide resources, building them once."""
    global _resources
    if _resources is None:
        settings = load_settings()
        configure_logging(settings)

        engine = create_db_engine(settings)
        # The schema is created here as well as by the API process, because the consumer
        # can be the first thing to run after a deployment. Creating it is idempotent.
        init_db(engine)
        session_factory = create_session_factory(engine)

        storage = build_storage(settings)
        embedder = build_embedder(settings)
        vector_store = build_vector_store(settings)
        metrics = MetricsRegistry()
        consumer = IngestionConsumer(
            ingestion=build_ingestion_service(
                settings,
                session_factory=session_factory,
                storage=storage,
                embedder=embedder,
                vector_store=vector_store,
                metrics=metrics,
            ),
            session_factory=session_factory,
            metrics=metrics,
        )
        _resources = _Resources(consumer=consumer, engine=engine)
        logger.info(
            "ingestion_consumer_ready",
            storage=type(storage).__name__,
            embedder=type(embedder).__name__,
            vector_store=type(vector_store).__name__,
        )
    return _resources


def handler(event: Mapping[str, Any], context: Any = None) -> dict[str, list[dict[str, str]]]:
    """Handle one batch of queue messages.

    Returns the messages the event source mapping has to deliver again. An event that is
    not shaped like an SQS event raises instead: there is nothing to report a retry
    against, so failing the invocation is the only honest outcome.
    """
    records = messages_from_lambda_event(event)
    result = get_consumer().handle_records(records)
    if result.deferred:
        logger.warning(
            "ingestion_batch_partially_deferred",
            handled=result.handled,
            deferred=result.failed_message_ids,
        )
    return {
        "batchItemFailures": [
            {"itemIdentifier": message_id} for message_id in result.failed_message_ids
        ]
    }


def reset() -> None:
    """Drop the cached resources and their connection pool. Used by tests."""
    global _resources
    if _resources is not None:
        _resources.engine.dispose()
    _resources = None
