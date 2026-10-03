"""Helpers shared by the HTTP tests."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

KB_BASE = "/api/v1/knowledge-bases"

POLICY_MD = b"""# Encryption policy

Customer data is encrypted at rest with KMS customer managed keys.

## Credential rotation

Database credentials rotate every ninety days through Secrets Manager.
"""

MANUAL_TXT = b"""Office seating is booked through the facilities portal.
"""


def documents_url(knowledge_base_id: str) -> str:
    """Return the collection URL of a knowledge base's documents."""
    return f"{KB_BASE}/{knowledge_base_id}/documents"


def chunks_url(knowledge_base_id: str, document_id: str) -> str:
    """Return the URL of a document's indexed passages."""
    return f"{documents_url(knowledge_base_id)}/{document_id}/chunks"


def document_url(knowledge_base_id: str, document_id: str) -> str:
    """Return the metadata URL of one document."""
    return f"{documents_url(knowledge_base_id)}/{document_id}"


def upload(
    client: TestClient,
    knowledge_base_id: str,
    filename: str = "policy.md",
    content: bytes = POLICY_MD,
) -> dict[str, Any]:
    """Upload a document and return its metadata."""
    response = client.post(
        documents_url(knowledge_base_id),
        files={"file": (filename, content, "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def ask(
    client: TestClient,
    knowledge_base_id: str,
    question: str,
    **overrides: Any,
) -> dict[str, Any]:
    """Ask a question and return the response body."""
    response = client.post(
        f"{KB_BASE}/{knowledge_base_id}/query",
        json={"question": question, **overrides},
    )
    assert response.status_code == 200, response.text
    return response.json()


def long_document(sections: int = 4, repeats: int = 120) -> bytes:
    """Build a Markdown document that is long enough to chunk into several passages."""
    body = "\n\n".join(
        f"## Section {index}\n\n" + (f"procedure{index} " * repeats)
        for index in range(1, sections + 1)
    )
    return f"# Operations manual\n\n{body}\n".encode()
