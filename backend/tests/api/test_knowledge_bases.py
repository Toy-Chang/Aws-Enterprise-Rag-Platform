"""Tests for the knowledge base endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

BASE = "/api/v1/knowledge-bases"


def _create(client: TestClient, name: str, description: str | None = None):
    payload: dict[str, object] = {"name": name}
    if description is not None:
        payload["description"] = description
    return client.post(BASE, json=payload)


def test_create_returns_the_new_knowledge_base(client: TestClient) -> None:
    response = _create(client, "Platform Runbooks", "Operational procedures.")

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Platform Runbooks"
    assert body["description"] == "Operational procedures."
    assert body["id"]
    assert body["created_at"] == body["updated_at"]


def test_create_trims_the_name_and_drops_a_blank_description(client: TestClient) -> None:
    response = _create(client, "  Security Policies  ", "   ")

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Security Policies"
    assert body["description"] is None


def test_create_rejects_a_duplicate_name(client: TestClient) -> None:
    assert _create(client, "Duplicate").status_code == 201

    response = _create(client, "Duplicate")

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "CONFLICT"
    assert body["error"]["details"] == {"field": "name"}


def test_create_rejects_a_blank_name(client: TestClient) -> None:
    response = client.post(BASE, json={"name": "   "})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNPROCESSABLE_ENTITY"


def test_create_rejects_a_missing_name(client: TestClient) -> None:
    response = client.post(BASE, json={})

    assert response.status_code == 422
    assert response.json()["error"]["details"]["errors"]


def test_list_is_empty_before_anything_is_created(client: TestClient) -> None:
    response = client.get(BASE)

    assert response.status_code == 200
    assert response.json() == []


def test_list_returns_every_knowledge_base(client: TestClient) -> None:
    _create(client, "Alpha")
    _create(client, "Beta")

    names = {item["name"] for item in client.get(BASE).json()}

    assert names == {"Alpha", "Beta"}


def test_get_returns_a_knowledge_base(client: TestClient) -> None:
    created = _create(client, "Reports").json()

    response = client.get(f"{BASE}/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_is_not_found_for_an_unknown_id(client: TestClient) -> None:
    response = client.get(f"{BASE}/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_delete_removes_the_knowledge_base(client: TestClient) -> None:
    created = _create(client, "Temporary").json()

    assert client.delete(f"{BASE}/{created['id']}").status_code == 204
    assert client.get(f"{BASE}/{created['id']}").status_code == 404


def test_delete_is_not_found_for_an_unknown_id(client: TestClient) -> None:
    response = client.delete(f"{BASE}/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
