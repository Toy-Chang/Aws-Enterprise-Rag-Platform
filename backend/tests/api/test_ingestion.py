"""End-to-end tests for ingestion: upload, parse, chunk, embed, index."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.core.config import Settings
from app.core.db import session_scope
from app.main import create_app
from app.models import Document, DocumentStatus
from tests.api.support import (
    KB_BASE,
    MANUAL_TXT,
    POLICY_MD,
    chunks_url,
    documents_url,
    upload,
)
from tests.ingestion.pdf_builder import build_pdf


def test_an_upload_is_queued_then_becomes_ready(
    client: TestClient, ingest_pending: Callable[[], int], knowledge_base_id: str
) -> None:
    uploaded = upload(client, knowledge_base_id)

    assert uploaded["status"] == "pending"
    assert uploaded["chunk_count"] == 0

    assert ingest_pending() == 1

    document = client.get(f"{documents_url(knowledge_base_id)}/{uploaded['id']}").json()
    assert document["status"] == "ready"
    assert document["error_message"] is None
    assert document["chunk_count"] > 0


def test_chunk_metadata_preserves_the_markdown_heading_path(
    client: TestClient, ingest_pending: Callable[[], int], knowledge_base_id: str
) -> None:
    uploaded = upload(client, knowledge_base_id)
    ingest_pending()

    chunks = client.get(chunks_url(knowledge_base_id, uploaded["id"])).json()

    assert [chunk["heading_path"] for chunk in chunks] == [
        ["Encryption policy"],
        ["Encryption policy", "Credential rotation"],
    ]
    assert [chunk["chunk_index"] for chunk in chunks] == [0, 1]
    assert all(chunk["content"].strip() for chunk in chunks)


def test_pdf_chunks_carry_their_page_number(
    client: TestClient, ingest_pending: Callable[[], int], knowledge_base_id: str
) -> None:
    content = build_pdf(["Encryption uses KMS.", "Rotation happens every ninety days."])
    uploaded = upload(client, knowledge_base_id, "manual.pdf", content)
    ingest_pending()

    chunks = client.get(chunks_url(knowledge_base_id, uploaded["id"])).json()

    assert [chunk["page_number"] for chunk in chunks] == [1, 2]
    assert all(chunk["heading_path"] == [] for chunk in chunks)


def test_ingested_content_becomes_retrievable_by_the_vector_index(
    client: TestClient, app: FastAPI, ingest_pending: Callable[[], int], knowledge_base_id: str
) -> None:
    policy = upload(client, knowledge_base_id, "policy.md", POLICY_MD)
    manual = upload(client, knowledge_base_id, "manual.txt", MANUAL_TXT)

    query = app.state.embedder.embed_query("credentials rotate every ninety days")
    assert app.state.vector_store.search(query, knowledge_base_id=knowledge_base_id, top_k=3) == []

    assert ingest_pending() == 2

    matches = app.state.vector_store.search(query, knowledge_base_id=knowledge_base_id, top_k=3)

    assert matches
    assert matches[0].document_id == policy["id"]
    assert matches[0].score > 0
    assert manual["id"] != policy["id"]


def test_the_index_only_answers_for_its_own_knowledge_base(
    client: TestClient, app: FastAPI, ingest_pending: Callable[[], int], knowledge_base_id: str
) -> None:
    other = client.post(KB_BASE, json={"name": "Other"}).json()["id"]
    upload(client, knowledge_base_id)
    ingest_pending()

    query = app.state.embedder.embed_query("credentials rotate")

    assert app.state.vector_store.search(query, knowledge_base_id=knowledge_base_id, top_k=5)
    assert app.state.vector_store.search(query, knowledge_base_id=other, top_k=5) == []


def test_an_unparsable_document_fails_with_a_readable_reason(
    client: TestClient, app: FastAPI, ingest_pending: Callable[[], int], knowledge_base_id: str
) -> None:
    uploaded = upload(client, knowledge_base_id, "broken.pdf", b"definitely not a PDF")

    assert ingest_pending() == 1

    document = client.get(f"{documents_url(knowledge_base_id)}/{uploaded['id']}").json()
    assert document["status"] == "failed"
    assert document["chunk_count"] == 0
    assert "could not be read" in document["error_message"]
    assert client.get(chunks_url(knowledge_base_id, uploaded["id"])).json() == []
    assert app.state.vector_store.count() == 0


def test_a_document_without_extractable_text_fails_with_a_reason(
    client: TestClient, ingest_pending: Callable[[], int], knowledge_base_id: str
) -> None:
    uploaded = upload(client, knowledge_base_id, "blank.txt", b"   \n\n\t\n")

    ingest_pending()

    document = client.get(f"{documents_url(knowledge_base_id)}/{uploaded['id']}").json()
    assert document["status"] == "failed"
    assert document["error_message"] == "no text could be extracted from the document"


def test_reprocessing_rebuilds_the_chunks_without_duplicating_them(
    client: TestClient, app: FastAPI, ingest_pending: Callable[[], int], knowledge_base_id: str
) -> None:
    uploaded = upload(client, knowledge_base_id)
    ingest_pending()
    first_pass = client.get(chunks_url(knowledge_base_id, uploaded["id"])).json()
    assert first_pass
    assert app.state.vector_store.count() == len(first_pass)

    response = client.post(f"{documents_url(knowledge_base_id)}/{uploaded['id']}/reprocess")

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["chunk_count"] == 0
    assert client.get(chunks_url(knowledge_base_id, uploaded["id"])).json() == []
    assert app.state.vector_store.count() == 0

    assert ingest_pending() == 1

    second_pass = client.get(chunks_url(knowledge_base_id, uploaded["id"])).json()
    assert len(second_pass) == len(first_pass)
    assert second_pass[0]["content"] == first_pass[0]["content"]
    assert app.state.vector_store.count() == len(second_pass)


def test_deleting_a_document_removes_its_chunks_and_vectors(
    client: TestClient, app: FastAPI, ingest_pending: Callable[[], int], knowledge_base_id: str
) -> None:
    uploaded = upload(client, knowledge_base_id)
    ingest_pending()
    assert app.state.vector_store.count() > 0

    assert client.delete(f"{documents_url(knowledge_base_id)}/{uploaded['id']}").status_code == 204

    assert app.state.vector_store.count() == 0
    assert client.get(chunks_url(knowledge_base_id, uploaded["id"])).status_code == 404


def test_deleting_a_knowledge_base_removes_its_chunks_and_vectors(
    client: TestClient, app: FastAPI, ingest_pending: Callable[[], int], knowledge_base_id: str
) -> None:
    upload(client, knowledge_base_id)
    upload(client, knowledge_base_id, "manual.txt", MANUAL_TXT)
    ingest_pending()
    assert app.state.vector_store.count() > 0

    assert client.delete(f"{KB_BASE}/{knowledge_base_id}").status_code == 204

    assert app.state.vector_store.count() == 0


def test_the_index_is_rebuilt_from_the_database_after_a_restart(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        knowledge_base_id = client.post(KB_BASE, json={"name": "Persistent"}).json()["id"]
        upload(client, knowledge_base_id)
        client.app.state.ingestion.run_pending()
        expected = client.app.state.vector_store.count()
        assert expected > 0

    with TestClient(create_app(settings)) as client:
        assert client.app.state.vector_store.count() == expected

        matches = client.app.state.vector_store.search(
            client.app.state.embedder.embed_query("credentials rotate"),
            knowledge_base_id=knowledge_base_id,
            top_k=1,
        )
        assert matches


def test_an_interrupted_ingestion_is_queued_again_at_startup(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        knowledge_base_id = client.post(KB_BASE, json={"name": "Interrupted"}).json()["id"]
        document_id = upload(client, knowledge_base_id)["id"]
        # A document left behind by a crash, with nothing else looking at it.
        with session_scope(client.app.state.session_factory) as session:
            session.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(status=DocumentStatus.PROCESSING.value)
            )

    with TestClient(create_app(settings)) as client:
        document = client.get(f"{documents_url(knowledge_base_id)}/{document_id}").json()
        assert document["status"] == "pending"

        client.app.state.ingestion.run_pending()

        document = client.get(f"{documents_url(knowledge_base_id)}/{document_id}").json()
        assert document["status"] == "ready"


def test_the_worker_ingests_uploaded_documents(tmp_path: Path) -> None:
    """Cover the worker loop itself, with the thread running for real."""
    settings = Settings(
        _env_file=None,
        environment="test",
        log_level="WARNING",
        database_url=f"sqlite:///{tmp_path / 'worker.db'}",
        storage_dir=str(tmp_path / "documents"),
        ingestion_poll_seconds=0.05,
    )

    with TestClient(create_app(settings)) as client:
        knowledge_base_id = client.post(KB_BASE, json={"name": "Worker"}).json()["id"]
        document_id = upload(client, knowledge_base_id)["id"]

        deadline = time.monotonic() + 15
        status = "pending"
        while time.monotonic() < deadline:
            status = client.get(f"{documents_url(knowledge_base_id)}/{document_id}").json()[
                "status"
            ]
            if status == "ready":
                break
            time.sleep(0.05)

    assert status == "ready"


def test_the_worker_thread_is_absent_when_it_is_disabled(app: FastAPI) -> None:
    with TestClient(app):
        assert app.state.ingestion_worker.running is False


def test_the_worker_thread_runs_when_it_is_enabled(settings: Settings) -> None:
    enabled = settings.model_copy(update={"ingestion_worker_enabled": True})

    with TestClient(create_app(enabled)) as client:
        assert client.app.state.ingestion_worker.running is True
