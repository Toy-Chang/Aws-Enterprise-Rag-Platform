"""Tests for the uniform API error contract."""

from __future__ import annotations

import io
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ConflictError, GenerationFailedError, NotFoundError
from app.core.logging import configure_logging
from app.main import create_app


def test_unmatched_route_returns_error_envelope(client: TestClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"] == "Not Found"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_wrong_method_returns_error_envelope(client: TestClient) -> None:
    response = client.post("/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_app_error_maps_to_declared_status_and_code(app: FastAPI, client: TestClient) -> None:
    @app.get("/_probe/conflict")
    async def _conflict() -> None:
        raise ConflictError("Knowledge base name already exists.", details={"field": "name"})

    response = client.get("/_probe/conflict")

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "CONFLICT"
    assert body["error"]["message"] == "Knowledge base name already exists."
    assert body["error"]["details"] == {"field": "name"}
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_app_error_default_message_is_used(app: FastAPI, client: TestClient) -> None:
    @app.get("/_probe/missing")
    async def _missing() -> None:
        raise NotFoundError()

    response = client.get("/_probe/missing")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"] == "The requested resource was not found."


def test_validation_failure_reports_field_details(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/_probe/validated")
    async def _validated(limit: int) -> dict[str, int]:
        return {"limit": limit}

    with TestClient(app) as client:
        response = client.get("/_probe/validated", params={"limit": "not-a-number"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "UNPROCESSABLE_ENTITY"
    assert body["error"]["details"]["errors"]
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_unhandled_exception_is_not_leaked(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/_probe/boom")
    async def _boom() -> None:
        raise RuntimeError("internal-detail-that-must-not-leak")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_probe/boom")

    assert response.status_code == 500
    assert "internal-detail-that-must-not-leak" not in response.text
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["message"] == "An unexpected error occurred."
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_a_server_side_failure_is_logged_with_its_cause(settings: Settings) -> None:
    """An upstream refusal has to reach the logs, even though the caller sees a summary."""
    app = create_app(settings)

    @app.get("/_probe/upstream")
    async def _upstream() -> None:
        try:
            raise RuntimeError("upstream-refused-the-call")
        except RuntimeError as cause:
            raise GenerationFailedError("the model could not be reached") from cause

    stream = io.StringIO()
    configure_logging(settings, stream=stream)
    with TestClient(app) as client:
        response = client.get("/_probe/upstream")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "GENERATION_FAILED"
    assert "upstream-refused-the-call" not in response.text

    records = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    failure = next(record for record in records if record["event"] == "application_error")
    assert failure["error_code"] == "GENERATION_FAILED"
    assert failure["error_type"] == "GenerationFailedError"
    assert failure["http_status"] == 502
    assert "upstream-refused-the-call" in failure["exception"]


def test_a_client_side_failure_is_logged_without_a_traceback(
    app: FastAPI, client: TestClient
) -> None:
    @app.get("/_probe/conflict-logged")
    async def _conflict() -> None:
        raise ConflictError("already exists")

    stream = io.StringIO()
    configure_logging(app.state.settings, stream=stream)
    client.get("/_probe/conflict-logged")

    records = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    failure = next(record for record in records if record["event"] == "application_error")
    assert failure["error_code"] == "CONFLICT"
    assert "exception" not in failure
