"""Tests for document upload and metadata endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

KB_BASE = "/api/v1/knowledge-bases"


@pytest.fixture
def knowledge_base_id(client: TestClient) -> str:
    response = client.post(KB_BASE, json={"name": "Compliance"})
    assert response.status_code == 201
    return response.json()["id"]


def _documents_url(knowledge_base_id: str) -> str:
    return f"{KB_BASE}/{knowledge_base_id}/documents"


def _upload(
    client: TestClient,
    knowledge_base_id: str,
    filename: str = "policy.md",
    content: bytes = b"# Policy\n\nRotate credentials.",
    content_type: str = "text/markdown",
):
    return client.post(
        _documents_url(knowledge_base_id),
        files={"file": (filename, content, content_type)},
    )


def test_upload_stores_metadata_and_content(
    client: TestClient, knowledge_base_id: str, storage_dir: Path
) -> None:
    content = b"# Encryption policy\n\nUse KMS."

    response = _upload(client, knowledge_base_id, "policy.md", content, "text/markdown")

    assert response.status_code == 201
    body = response.json()
    assert body["knowledge_base_id"] == knowledge_base_id
    assert body["name"] == "policy.md"
    assert body["content_type"] == "text/markdown"
    assert body["size_bytes"] == len(content)
    assert body["status"] == "pending"
    assert body["version"] == 1
    assert (storage_dir / knowledge_base_id / body["id"]).read_bytes() == content


@pytest.mark.parametrize("filename", ["runbook.txt", "manual.pdf", "notes.markdown", "GUIDE.MD"])
def test_upload_accepts_every_supported_format(
    client: TestClient, knowledge_base_id: str, filename: str
) -> None:
    response = _upload(client, knowledge_base_id, filename, b"data")

    assert response.status_code == 201
    assert response.json()["name"] == filename


@pytest.mark.parametrize("filename", ["archive.zip", "sheet.xlsx", "noextension"])
def test_upload_rejects_unsupported_formats(
    client: TestClient, knowledge_base_id: str, filename: str
) -> None:
    response = _upload(client, knowledge_base_id, filename, b"data")

    assert response.status_code == 415
    body = response.json()
    assert body["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert ".pdf" in body["error"]["details"]["supported_extensions"]


def test_upload_is_not_found_for_an_unknown_knowledge_base(client: TestClient) -> None:
    response = _upload(client, "does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_upload_rejects_a_document_above_the_size_limit(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        log_level="WARNING",
        database_url=f"sqlite:///{tmp_path / 'limit.db'}",
        storage_dir=str(tmp_path / "documents"),
        max_upload_size_bytes=16,
    )

    with TestClient(create_app(settings)) as client:
        knowledge_base_id = client.post(KB_BASE, json={"name": "Small"}).json()["id"]
        response = _upload(client, knowledge_base_id, "big.txt", b"x" * 17)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_upload_sanitises_a_client_supplied_path(
    client: TestClient, knowledge_base_id: str, storage_dir: Path
) -> None:
    response = _upload(client, knowledge_base_id, "../../escape.md", b"data")

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "escape.md"
    assert (storage_dir / knowledge_base_id / body["id"]).exists()


def test_list_returns_the_uploaded_documents(client: TestClient, knowledge_base_id: str) -> None:
    _upload(client, knowledge_base_id, "a.md", b"a")
    _upload(client, knowledge_base_id, "b.txt", b"b")

    response = client.get(_documents_url(knowledge_base_id))

    assert response.status_code == 200
    assert {document["name"] for document in response.json()} == {"a.md", "b.txt"}


def test_list_is_not_found_for_an_unknown_knowledge_base(client: TestClient) -> None:
    response = client.get(_documents_url("does-not-exist"))

    assert response.status_code == 404


def test_get_returns_document_metadata(client: TestClient, knowledge_base_id: str) -> None:
    uploaded = _upload(client, knowledge_base_id).json()

    response = client.get(f"{_documents_url(knowledge_base_id)}/{uploaded['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == uploaded["id"]


def test_get_is_not_found_for_an_unknown_document(
    client: TestClient, knowledge_base_id: str
) -> None:
    response = client.get(f"{_documents_url(knowledge_base_id)}/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_delete_removes_metadata_and_stored_content(
    client: TestClient, knowledge_base_id: str, storage_dir: Path
) -> None:
    uploaded = _upload(client, knowledge_base_id).json()
    stored = storage_dir / knowledge_base_id / uploaded["id"]
    assert stored.exists()

    response = client.delete(f"{_documents_url(knowledge_base_id)}/{uploaded['id']}")

    assert response.status_code == 204
    assert not stored.exists()
    assert client.get(f"{_documents_url(knowledge_base_id)}/{uploaded['id']}").status_code == 404


def test_deleting_a_knowledge_base_removes_its_documents(
    client: TestClient, storage_dir: Path
) -> None:
    knowledge_base_id = client.post(KB_BASE, json={"name": "Scratch"}).json()["id"]
    first = _upload(client, knowledge_base_id, "one.md", b"1").json()
    second = _upload(client, knowledge_base_id, "two.md", b"2").json()
    first_path = storage_dir / knowledge_base_id / first["id"]
    second_path = storage_dir / knowledge_base_id / second["id"]
    assert first_path.exists() and second_path.exists()

    response = client.delete(f"{KB_BASE}/{knowledge_base_id}")

    assert response.status_code == 204
    assert not first_path.exists()
    assert not second_path.exists()
    assert client.get(_documents_url(knowledge_base_id)).status_code == 404
