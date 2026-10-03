"""Turns queued ingestion messages into ingestion runs.

The consumer does not know which transport delivered a message, so it can be driven by an
SQS event in Lambda or by any other queue without changing a line of it. What it does own
is the rule for when a message is finished, and that rule comes from the document rather
than from the run:

* a document that reached a terminal state (``ready`` or ``failed``) means the outcome of
  the run was recorded, and the message did its job;
* anything else -- no such document, a document still ``processing``, an unreadable body,
  a status that could not be read -- means the work is not finished, so the message is
  left on the queue.

Leaving it is deliberate. A message can legitimately arrive before the transaction that
created the document has committed, and a run whose own failure could not be recorded
leaves the document mid-ingestion; in both cases a retry is what makes the system
converge. SQS redelivers it, and a message that never becomes valid ends up in the
dead-letter queue where an operator can see it. Nothing is deleted on a guess.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import session_scope
from app.core.logging import get_logger
from app.core.metrics import MetricsRegistry
from app.models.document import Document, DocumentStatus
from app.repositories.queue import IngestionMessage, MalformedMessageError, ReceivedMessage
from app.services.ingestion import IngestionService

logger = get_logger(__name__)

#: A document in one of these states has had its outcome recorded, so the message that
#: asked for it is done. Everything else is retried.
TERMINAL_STATUSES = frozenset({DocumentStatus.READY.value, DocumentStatus.FAILED.value})


@dataclass(frozen=True)
class DeferredMessage:
    """A message that has to be delivered again, and why."""

    message_id: str
    reason: str


@dataclass(frozen=True)
class ConsumerResult:
    """What one batch of messages amounted to."""

    handled: int
    deferred: tuple[DeferredMessage, ...]

    @property
    def failed_message_ids(self) -> list[str]:
        """The ids to report back for redelivery, in the order they arrived."""
        return [message.message_id for message in self.deferred]


class IngestionConsumer:
    """Runs ingestion for the messages a queue delivers."""

    def __init__(
        self,
        *,
        ingestion: IngestionService,
        session_factory: sessionmaker[Session],
        metrics: MetricsRegistry,
    ) -> None:
        self._ingestion = ingestion
        self._session_factory = session_factory
        self._metrics = metrics

    def handle_records(self, records: Sequence[ReceivedMessage]) -> ConsumerResult:
        """Handle one batch, reporting which messages have to be delivered again."""
        handled = 0
        deferred: list[DeferredMessage] = []
        for record in records:
            reason = self._handle(record)
            if reason is None:
                handled += 1
            else:
                deferred.append(DeferredMessage(record.message_id, reason))

        if handled:
            self._metrics.increment("ingestion.messages.handled", handled)
        if deferred:
            self._metrics.increment("ingestion.messages.deferred", len(deferred))
        return ConsumerResult(handled=handled, deferred=tuple(deferred))

    def _handle(self, record: ReceivedMessage) -> str | None:
        """Handle one message, returning a retry reason or ``None`` when it is done."""
        try:
            message = IngestionMessage.from_body(record.body)
        except MalformedMessageError as exc:
            # A body this version cannot read will not become readable by trying again,
            # but deleting it would drop whatever it was meant to do. It goes to the
            # dead-letter queue instead.
            logger.warning(
                "ingestion_message_unreadable", message_id=record.message_id, reason=str(exc)
            )
            return f"unreadable message: {exc}"

        try:
            self._ingestion.run(message.knowledge_base_id, message.document_id)
        except Exception:
            # The service records a failure rather than raising it, so reaching here means
            # a defect in the run itself; one message must not take the batch with it.
            logger.exception(
                "ingestion_run_raised",
                message_id=record.message_id,
                document_id=message.document_id,
            )
            return "the ingestion run raised"

        try:
            status = self._document_status(message.document_id)
        except Exception as exc:
            logger.exception(
                "ingestion_message_status_unreadable",
                message_id=record.message_id,
                document_id=message.document_id,
            )
            return f"the document status could not be read: {type(exc).__name__}"

        if status is None:
            logger.warning(
                "ingestion_message_unknown_document",
                message_id=record.message_id,
                document_id=message.document_id,
            )
            return "the document does not exist"

        if status not in TERMINAL_STATUSES:
            logger.warning(
                "ingestion_message_incomplete",
                message_id=record.message_id,
                document_id=message.document_id,
                status=status,
            )
            return f"the document is still {status}"

        return None

    def _document_status(self, document_id: str) -> str | None:
        """Return the document's status, or ``None`` if the document is gone."""
        with session_scope(self._session_factory) as session:
            return session.scalar(select(Document.status).where(Document.id == document_id))
