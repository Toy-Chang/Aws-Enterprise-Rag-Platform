"""Tests for the service metadata and health endpoints."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def test_root_returns_service_metadata(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "aws-enterprise-rag-platform"
    assert body["api_version"] == "v1"
    assert body["environment"] == "test"


def test_liveness_reports_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "aws-enterprise-rag-platform"
    assert body["environment"] == "test"


def test_readiness_reports_the_database_check(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert [check["name"] for check in body["checks"]] == ["database"]
    assert body["checks"][0]["status"] == "ok"


def test_response_reuses_inbound_request_id(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "trace-abc-123"})

    assert response.headers["X-Request-ID"] == "trace-abc-123"


def test_response_generates_request_id_when_absent(client: TestClient) -> None:
    response = client.get("/health")

    request_id = response.headers["X-Request-ID"]
    assert uuid.UUID(request_id).hex == request_id


def test_blank_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "   "})

    request_id = response.headers["X-Request-ID"]
    assert uuid.UUID(request_id).hex == request_id


def test_openapi_schema_is_served(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "AWS Enterprise RAG Platform"
    assert "/health" in schema["paths"]
    assert "/health/ready" in schema["paths"]
