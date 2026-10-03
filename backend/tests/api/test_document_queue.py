"""Tests for publishing ingestion work from the document endpoints."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.db import session_scope
from app.models.document import Document
from app.repositories.queue import DocumentQueue, DocumentQueueError, IngestionMessage
from tests.api.support import documents_url, upload


class RecordingQueue:
    """A queue that records what it was asked to publish.

    It also reads the document with its own session at publish time. A separate connection
    cannot see uncommitted work, so a recorded status is what proves the row was committed
    before the message went out.
    """

    def __init__(self, session_factory: sessionmaker, *, fail: bool = False) -> None:
        self.messages: list[IngestionMessage] = []
        self.statuses_at_publish: list[str | None] = []
        self._session_factory = session_factory
        self._fail = fail

    def enqueue(self, message: IngestionMessage) -> None:
        if self._fail:
            raise DocumentQueueError("the queue is unreachable")
        with session_scope(self._session_factory) as session:
            status = session.scalar(
                select(Document.status).where(Document.id == message.document_id)
            )
        self.messages.append(message)
        self.statuses_at_publish.append(status)


@pytest.fixture
def queue(app: FastAPI) -> RecordingQueue:
    """Replace the application's queue with one the test can inspect."""
    recorded = RecordingQueue(app.state.session_factory)
    app.state.document_queue = recorded
    return recorded


@pytest.fixture
def queue_client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


def test_the_recording_queue_satisfies_the_port(queue: RecordingQueue) -> None:
    assert isinstance(queue, DocumentQueue)


def test_upload_publishes_the_document_for_ingestion(
    queue: RecordingQueue, queue_client: TestClient, knowledge_base_id: str
) -> None:
    document = upload(queue_client, knowledge_base_id)

    assert queue.messages == [
        IngestionMessage(knowledge_base_id=knowledge_base_id, document_id=document["id"])
    ]
    # Published after the commit: a consumer that receives the message immediately can
    # already see the row it refers to.
    assert queue.statuses_at_publish == ["pending"]


def test_reprocess_publishes_the_document_again(
    queue: RecordingQueue, queue_client: TestClient, knowledge_base_id: str
) -> None:
    document = upload(queue_client, knowledge_base_id)
    queue.messages.clear()
    queue.statuses_at_publish.clear()

    response = queue_client.post(f"{documents_url(knowledge_base_id)}/{document['id']}/reprocess")
    assert response.status_code == 202
    assert queue.messages == [
        IngestionMessage(knowledge_base_id=knowledge_base_id, document_id=document["id"])
    ]
    # The reprocess committed the document as pending before publishing, which is the
    # state the consumer has to see: the previous terminal state would look like finished
    # work and the message would be treated as done.
    assert queue.statuses_at_publish == ["pending"]


def test_reading_endpoints_do_not_publish_anything(
    queue: RecordingQueue, queue_client: TestClient, knowledge_base_id: str
) -> None:
    document = upload(queue_client, knowledge_base_id)
    queue.messages.clear()

    queue_client.get(documents_url(knowledge_base_id))
    queue_client.get(f"{documents_url(knowledge_base_id)}/{document['id']}")
    queue_client.get(f"{documents_url(knowledge_base_id)}/{document['id']}/chunks")

    assert queue.messages == []


def test_a_publish_that_fails_is_reported_and_the_document_survives(
    app: FastAPI, queue_client: TestClient, knowledge_base_id: str
) -> None:
    app.state.document_queue = RecordingQueue(app.state.session_factory, fail=True)

    response = queue_client.post(
        documents_url(knowledge_base_id),
        files={"file": ("policy.md", b"# Policy\n\nText.\n", "text/markdown")},
    )

    # Reported rather than swallowed: a caller that believes the work was queued while
    # nothing will ever pick it up has no way to find out otherwise.
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "QUEUE_UNAVAILABLE"

    # The document is still there, pending, and reprocessing it is the recovery path.
    listed = queue_client.get(documents_url(knowledge_base_id)).json()
    assert [entry["status"] for entry in listed] == ["pending"]
