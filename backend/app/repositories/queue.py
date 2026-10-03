"""Port for handing ingestion work to a queue.

The port is owned by the domain, and the local stack satisfies it with a null
implementation: the ingestion worker polls the database for pending documents, so an
upload is picked up without anything being published. A deployment with more than one
task needs a real queue, because two pollers would claim the same document.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.core.errors import AppError

#: The wire format version. A consumer that meets a version it does not know refuses the
#: message instead of guessing at its fields.
MESSAGE_VERSION = 1


class MalformedMessageError(ValueError):
    """Raised when a queued message cannot be understood."""


class DocumentQueueError(AppError):
    """Raised when ingestion work cannot be published.

    A queue that cannot be reached is an upstream fault rather than a defect here, so it
    maps to 502 like the other adapter failures declared beside their ports.
    """

    status_code = 502
    code = "QUEUE_UNAVAILABLE"
    message = "The ingestion queue could not be reached."


@dataclass(frozen=True)
class IngestionMessage:
    """One unit of ingestion work, as it travels through a queue.

    The body carries only identifiers: the document is the source of truth for what has
    to be ingested, so a message cannot disagree with a row about content, chunking or
    embeddings that have since changed.
    """

    knowledge_base_id: str
    document_id: str

    def to_body(self) -> str:
        """Return the message body to publish."""
        return json.dumps(
            {
                "version": MESSAGE_VERSION,
                "knowledge_base_id": self.knowledge_base_id,
                "document_id": self.document_id,
            },
            sort_keys=True,
        )

    @classmethod
    def from_body(cls, body: str) -> IngestionMessage:
        """Parse a message body.

        Raises:
            MalformedMessageError: if the body is not a message this version understands.
        """
        try:
            payload = json.loads(body)
        except (TypeError, ValueError) as exc:
            raise MalformedMessageError(f"the body is not JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise MalformedMessageError("the body is not a JSON object")

        version = payload.get("version")
        if version != MESSAGE_VERSION:
            raise MalformedMessageError(f"unsupported message version {version!r}")

        knowledge_base_id = payload.get("knowledge_base_id")
        document_id = payload.get("document_id")
        if not isinstance(knowledge_base_id, str) or not knowledge_base_id:
            raise MalformedMessageError("the message carries no knowledge_base_id")
        if not isinstance(document_id, str) or not document_id:
            raise MalformedMessageError("the message carries no document_id")
        return cls(knowledge_base_id=knowledge_base_id, document_id=document_id)


@dataclass(frozen=True)
class ReceivedMessage:
    """One message as a consumer sees it, whichever transport delivered it.

    SQS spells the same fields two ways: the boto3 API returns ``MessageId``,
    ``ReceiptHandle`` and ``Body``, while a Lambda event source mapping sends
    ``messageId``, ``receiptHandle`` and ``body``. Normalising here keeps that difference
    in one place instead of in every consumer -- and it is the kind of difference that
    would otherwise be found in production rather than in a test.
    """

    message_id: str
    body: str
    receipt_handle: str | None = None

    @classmethod
    def from_sqs(cls, record: Mapping[str, Any]) -> ReceivedMessage:
        """Build one message from a ``receive_message`` record."""
        return cls(
            message_id=_required(record, "MessageId"),
            body=_required(record, "Body"),
            receipt_handle=_optional(record, "ReceiptHandle"),
        )

    @classmethod
    def from_lambda(cls, record: Mapping[str, Any]) -> ReceivedMessage:
        """Build one message from an SQS event source mapping record."""
        return cls(
            message_id=_required(record, "messageId"),
            body=_required(record, "body"),
            receipt_handle=_optional(record, "receiptHandle"),
        )


def messages_from_lambda_event(event: Mapping[str, Any]) -> list[ReceivedMessage]:
    """Return the messages carried by a Lambda SQS event.

    Raises:
        ValueError: if the event is not shaped like an SQS event. A record without an
            identifier could not be reported back to the event source mapping, so there
            is nothing useful to do with it except fail loudly.
    """
    records = event.get("Records")
    if not isinstance(records, list):
        raise ValueError("the event carries no Records list")
    return [ReceivedMessage.from_lambda(record) for record in records]


def _required(record: Mapping[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"the message record carries no {key}")
    return value


def _optional(record: Mapping[str, Any], key: str) -> str | None:
    value = record.get(key)
    return value if isinstance(value, str) and value else None


@runtime_checkable
class DocumentQueue(Protocol):
    """Publishes ingestion work for whatever will run it."""

    def enqueue(self, message: IngestionMessage) -> None:
        """Publish one unit of work.

        Raises:
            DocumentQueueError: if the message could not be published.
        """
        ...


class NullDocumentQueue:
    """The queue of a single-process deployment, which does not have one.

    Publishing is a no-op rather than an error so that the upload path does not have to
    branch on how the platform is deployed. The document is still ingested: the worker
    finds it by polling the database.
    """

    def enqueue(self, message: IngestionMessage) -> None:
        return None
