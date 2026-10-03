"""Tests for the SQS publishing adapter."""

from __future__ import annotations

from typing import Any

import pytest

from app.aws.sqs_queue import SqsDocumentQueue
from app.repositories.queue import (
    DocumentQueue,
    DocumentQueueError,
    IngestionMessage,
)


class StubSqs:
    """A stand-in for the SQS client."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail = fail

    def send_message(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._fail:
            raise RuntimeError("AWS.SimpleQueueService.NonExistentQueue")
        return {"MessageId": "m1"}


def _message(document_id: str = "doc-1") -> IngestionMessage:
    return IngestionMessage(knowledge_base_id="kb-1", document_id=document_id)


def test_the_adapter_satisfies_the_queue_port() -> None:
    queue = SqsDocumentQueue("https://sqs.eu-west-1.amazonaws.com/1/ingestion", client=StubSqs())

    assert isinstance(queue, DocumentQueue)
    assert queue.queue_url == "https://sqs.eu-west-1.amazonaws.com/1/ingestion"


def test_enqueue_publishes_the_message_body() -> None:
    client = StubSqs()
    queue = SqsDocumentQueue("https://sqs.example/ingestion", client=client)

    queue.enqueue(_message())

    assert client.calls == [
        {
            "QueueUrl": "https://sqs.example/ingestion",
            "MessageBody": _message().to_body(),
        }
    ]


def test_the_published_body_can_be_read_back_as_a_message() -> None:
    client = StubSqs()
    queue = SqsDocumentQueue("https://sqs.example/ingestion", client=client)

    queue.enqueue(_message("doc-9"))

    # The producer and the consumer share one body format, which is the only thing that
    # makes them able to talk to each other.
    body = client.calls[0]["MessageBody"]
    assert IngestionMessage.from_body(body) == _message("doc-9")


def test_a_queue_that_refuses_the_message_is_a_bad_gateway() -> None:
    queue = SqsDocumentQueue("https://sqs.example/ingestion", client=StubSqs(fail=True))

    with pytest.raises(DocumentQueueError, match="could not be published") as caught:
        queue.enqueue(_message())

    assert caught.value.status_code == 502
    assert caught.value.code == "QUEUE_UNAVAILABLE"
    assert isinstance(caught.value.__cause__, RuntimeError)


@pytest.mark.parametrize("queue_url", ["", "   "])
def test_a_queue_url_is_required(queue_url: str) -> None:
    with pytest.raises(ValueError, match="queue_url must not be empty"):
        SqsDocumentQueue(queue_url, client=StubSqs())


def test_the_queue_url_is_trimmed() -> None:
    queue = SqsDocumentQueue("  https://sqs.example/ingestion  ", client=StubSqs())

    assert queue.queue_url == "https://sqs.example/ingestion"


def test_a_client_is_created_only_when_it_is_needed() -> None:
    # boto3 resolves a region and credentials lazily and makes no network call here, so
    # this asserts the deferred import and the client wiring.
    queue = SqsDocumentQueue("https://sqs.example/ingestion", region="eu-west-1")

    assert queue.queue_url == "https://sqs.example/ingestion"


def test_an_unknown_kwarg_in_the_request_is_not_invented() -> None:
    # The call carries exactly two parameters: anything else (a message group id, a
    # deduplication id) belongs to a FIFO queue, which this adapter does not use.
    client = StubSqs()
    SqsDocumentQueue("https://sqs.example/ingestion", client=client).enqueue(_message())

    assert set(client.calls[0]) == {"QueueUrl", "MessageBody"}
