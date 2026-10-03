"""Publishes ingestion work to an SQS queue.

This module only publishes. Whoever consumes the queue deletes from it: with a Lambda
event source mapping, the mapping deletes the messages the function does not report as
failures, so a consumer that deleted them itself would be racing it.

A standard queue is enough. Every message is independent work, and ingesting a document
replaces that document's chunks and vectors, so a duplicate delivery converges on the
same state rather than corrupting anything. Ordering is not needed for the same reason,
which is why no FIFO queue is involved.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.core.logging import get_logger
from app.repositories.queue import DocumentQueueError, IngestionMessage

logger = get_logger(__name__)


class SqsClient(Protocol):
    """The part of the SQS client this adapter uses."""

    def send_message(self, **kwargs: Any) -> dict[str, Any]: ...


class SqsDocumentQueue:
    """Publishes one message per unit of ingestion work."""

    def __init__(
        self,
        queue_url: str,
        *,
        region: str | None = None,
        client: SqsClient | None = None,
    ) -> None:
        if not queue_url or not queue_url.strip():
            raise ValueError("queue_url must not be empty")
        self._queue_url = queue_url.strip()
        self._region = region
        self._client = client

    @property
    def queue_url(self) -> str:
        """The queue this adapter publishes to."""
        return self._queue_url

    def enqueue(self, message: IngestionMessage) -> None:
        """Publish one unit of work.

        Raises:
            DocumentQueueError: if the queue refused the message. The failure is raised
                rather than swallowed: a caller that believes the work was queued while
                nothing will pick it up has no way to find out otherwise.
        """
        client = self._client_or_create()
        try:
            client.send_message(QueueUrl=self._queue_url, MessageBody=message.to_body())
        except Exception as exc:
            logger.error(
                "ingestion_message_not_published",
                document_id=message.document_id,
                error_type=type(exc).__name__,
            )
            raise DocumentQueueError(
                f"the ingestion message for document {message.document_id!r} could not be published"
            ) from exc

    def _client_or_create(self) -> SqsClient:
        if self._client is None:
            self._client = _create_client(self._region)
        return self._client


def _create_client(region: str | None) -> SqsClient:
    """Build an SQS client with the SDK's ambient credentials."""
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - depends on the installed extras
        raise RuntimeError(
            "the SQS queue adapter needs the AWS SDK: install the 'aws' extra "
            "(pip install -e '.[aws]') or set APP_QUEUE_BACKEND=none"
        ) from exc
    return boto3.client("sqs", region_name=region)
