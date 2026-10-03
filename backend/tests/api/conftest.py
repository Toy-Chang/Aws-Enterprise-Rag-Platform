"""Fixtures shared by the HTTP tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.api.support import KB_BASE


@pytest.fixture
def knowledge_base_id(client: TestClient) -> str:
    """A knowledge base to work inside."""
    response = client.post(KB_BASE, json={"name": "Security"})
    assert response.status_code == 201
    return response.json()["id"]
