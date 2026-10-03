"""Tests for the ingestion queue port."""

from __future__ import annotations

import json

import pytest

from app.repositories.queue import (
    MESSAGE_VERSION,
    DocumentQueue,
    IngestionMessage,
    MalformedMessageError,
    NullDocumentQueue,
    ReceivedMessage,
    messages_from_lambda_event,
)


def test_a_message_round_trips_through_its_body() -> None:
    message = IngestionMessage(knowledge_base_id="kb-1", document_id="doc-1")

    assert IngestionMessage.from_body(message.to_body()) == message


def test_the_body_carries_only_identifiers() -> None:
    message = IngestionMessage(knowledge_base_id="kb-1", document_id="doc-1")

    # The document is the source of truth for content, chunking and embeddings, so a
    # message cannot disagree with a row about any of them.
    assert json.loads(message.to_body()) == {
        "version": MESSAGE_VERSION,
        "knowledge_base_id": "kb-1",
        "document_id": "doc-1",
    }


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("not json", "not JSON"),
        ("[]", "not a JSON object"),
        ('"a string"', "not a JSON object"),
        ("{}", "unsupported message version"),
        ('{"version": 2, "knowledge_base_id": "kb", "document_id": "doc"}', "unsupported"),
        ('{"version": "1", "knowledge_base_id": "kb", "document_id": "doc"}', "unsupported"),
        ('{"version": 1, "document_id": "doc"}', "no knowledge_base_id"),
        ('{"version": 1, "knowledge_base_id": "kb"}', "no document_id"),
        ('{"version": 1, "knowledge_base_id": "", "document_id": "doc"}', "no knowledge_base_id"),
        ('{"version": 1, "knowledge_base_id": "kb", "document_id": 7}', "no document_id"),
        ('{"version": 1, "knowledge_base_id": null, "document_id": "doc"}', "no knowledge_base_id"),
    ],
)
def test_a_body_that_is_not_a_message_is_refused(body: str, reason: str) -> None:
    with pytest.raises(MalformedMessageError, match=reason):
        IngestionMessage.from_body(body)


def test_the_null_queue_satisfies_the_port_and_does_nothing() -> None:
    queue = NullDocumentQueue()

    assert isinstance(queue, DocumentQueue)
    # The local stack polls the database, so publishing is a no-op rather than an error.
    queue.enqueue(IngestionMessage(knowledge_base_id="kb-1", document_id="doc-1"))


def test_a_boto3_record_is_normalised() -> None:
    message = ReceivedMessage.from_sqs({"MessageId": "m1", "ReceiptHandle": "r1", "Body": "{}"})

    assert message == ReceivedMessage(message_id="m1", body="{}", receipt_handle="r1")


def test_a_lambda_record_is_normalised() -> None:
    # The event source mapping spells the same fields in camel case, which is exactly the
    # kind of difference that would otherwise be found in production.
    message = ReceivedMessage.from_lambda({"messageId": "m1", "receiptHandle": "r1", "body": "{}"})

    assert message == ReceivedMessage(message_id="m1", body="{}", receipt_handle="r1")


def test_the_receipt_handle_is_optional() -> None:
    assert ReceivedMessage.from_sqs({"MessageId": "m1", "Body": "{}"}).receipt_handle is None


@pytest.mark.parametrize(
    "record",
    [
        {"MessageId": "m1"},
        {"Body": "{}"},
        {"MessageId": "", "Body": "{}"},
        {"MessageId": "m1", "Body": ""},
    ],
)
def test_a_record_without_an_identifier_or_a_body_is_refused(record: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="carries no"):
        ReceivedMessage.from_sqs(record)


def test_a_lambda_event_yields_its_messages_in_order() -> None:
    event = {
        "Records": [
            {"messageId": "m1", "body": "first"},
            {"messageId": "m2", "body": "second"},
        ]
    }

    assert [message.message_id for message in messages_from_lambda_event(event)] == ["m1", "m2"]
    assert [message.body for message in messages_from_lambda_event(event)] == ["first", "second"]


def test_an_empty_lambda_event_yields_nothing() -> None:
    assert messages_from_lambda_event({"Records": []}) == []


@pytest.mark.parametrize("event", [{}, {"Records": "nope"}, {"Records": None}])
def test_an_event_without_records_is_refused(event: dict[str, object]) -> None:
    # A record without an identifier could not be reported back for retry, so there is
    # nothing useful to do with such an event except fail loudly.
    with pytest.raises(ValueError, match="no Records list"):
        messages_from_lambda_event(event)
