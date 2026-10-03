"""Tests for authentication and authorization over HTTP.

The verifier is replaced with one the test controls, so the role matrix and the failure
mapping are exercised without a user pool. The Cognito adapter itself is covered in
``tests/aws/test_cognito_auth.py``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security.auth import (
    ADMIN,
    EDITOR,
    VIEWER,
    Principal,
    UnauthenticatedError,
)
from tests.api.support import KB_BASE, documents_url

ADMIN_TOKEN = "token-admin"
EDITOR_TOKEN = "token-editor"
VIEWER_TOKEN = "token-viewer"

PRINCIPALS: dict[str, Principal] = {
    ADMIN_TOKEN: Principal(
        subject="sub-admin",
        username="admin",
        groups=frozenset({ADMIN}),
        scopes=frozenset({"openid"}),
    ),
    EDITOR_TOKEN: Principal(subject="sub-editor", username="editor", groups=frozenset({EDITOR})),
    VIEWER_TOKEN: Principal(subject="sub-viewer", username="viewer", groups=frozenset({VIEWER})),
}


class StubVerifier:
    """Accepts the three test tokens and refuses everything else."""

    def __init__(self, principals: Mapping[str, Principal]) -> None:
        self._principals = dict(principals)

    def verify(self, token: str | None) -> Principal:
        if not token:
            raise UnauthenticatedError("An Authorization header with a bearer token is required.")
        principal = self._principals.get(token)
        if principal is None:
            raise UnauthenticatedError("The access token is not valid.")
        return principal


@pytest.fixture
def secured(app: FastAPI) -> FastAPI:
    """Install a verifier that demands one of the test tokens."""
    app.state.token_verifier = StubVerifier(PRINCIPALS)
    return app


@pytest.fixture
def secured_client(secured: FastAPI) -> Iterator[TestClient]:
    with TestClient(secured) as client:
        yield client


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_a_request_without_a_token_is_challenged(secured_client: TestClient) -> None:
    response = secured_client.get(KB_BASE)

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert body["request_id"]
    # Without the challenge header a client knows it failed but not how to succeed.
    assert response.headers["www-authenticate"] == 'Bearer realm="api"'


@pytest.mark.parametrize(
    "header",
    ["Token abc", "Bearer", "Bearer   ", "abc", "Basic dXNlcjpwYXNz"],
)
def test_a_malformed_authorization_header_is_refused(
    secured_client: TestClient, header: str
) -> None:
    response = secured_client.get(KB_BASE, headers={"Authorization": header})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_an_unknown_token_is_refused(secured_client: TestClient) -> None:
    response = secured_client.get(KB_BASE, headers=_auth("not-a-real-token"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_a_viewer_can_read(secured_client: TestClient) -> None:
    response = secured_client.get(KB_BASE, headers=_auth(VIEWER_TOKEN))

    assert response.status_code == 200


def test_a_viewer_cannot_create_a_knowledge_base(secured_client: TestClient) -> None:
    response = secured_client.post(KB_BASE, json={"name": "Security"}, headers=_auth(VIEWER_TOKEN))

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "FORBIDDEN"
    assert body["error"]["details"]["required_roles"] == [EDITOR]
    assert body["error"]["details"]["held_roles"] == [VIEWER]


def test_an_editor_can_create_a_knowledge_base(secured_client: TestClient) -> None:
    response = secured_client.post(KB_BASE, json={"name": "Security"}, headers=_auth(EDITOR_TOKEN))

    assert response.status_code == 201


def test_deleting_a_knowledge_base_needs_an_admin(secured_client: TestClient) -> None:
    created = secured_client.post(KB_BASE, json={"name": "Security"}, headers=_auth(ADMIN_TOKEN))
    assert created.status_code == 201
    knowledge_base_id = created.json()["id"]

    refused = secured_client.delete(f"{KB_BASE}/{knowledge_base_id}", headers=_auth(EDITOR_TOKEN))
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["required_roles"] == [ADMIN]

    deleted = secured_client.delete(f"{KB_BASE}/{knowledge_base_id}", headers=_auth(ADMIN_TOKEN))
    assert deleted.status_code == 204


def test_uploading_a_document_needs_an_editor(secured_client: TestClient, secured: FastAPI) -> None:
    knowledge_base_id = secured_client.post(
        KB_BASE, json={"name": "Security"}, headers=_auth(EDITOR_TOKEN)
    ).json()["id"]

    refused = secured_client.post(
        documents_url(knowledge_base_id),
        files={"file": ("policy.md", b"# Policy\n", "text/markdown")},
        headers=_auth(VIEWER_TOKEN),
    )
    assert refused.status_code == 403

    accepted = secured_client.post(
        documents_url(knowledge_base_id),
        files={"file": ("policy.md", b"# Policy\n", "text/markdown")},
        headers=_auth(EDITOR_TOKEN),
    )
    assert accepted.status_code == 201


def test_the_role_is_checked_before_the_payload(secured_client: TestClient) -> None:
    # An evaluation is admin-only and its body is invalid. A viewer must learn that it is
    # not allowed rather than that its JSON was wrong: otherwise the error tells an
    # unauthorized caller how the schema looks.
    response = secured_client.post(
        "/api/v1/evaluations", json={"k": 1}, headers=_auth(VIEWER_TOKEN)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_metrics_need_a_token(secured_client: TestClient) -> None:
    assert secured_client.get("/api/v1/metrics").status_code == 401
    assert secured_client.get("/api/v1/metrics", headers=_auth(VIEWER_TOKEN)).status_code == 200


@pytest.mark.parametrize("path", ["/health", "/health/ready", "/"])
def test_platform_probes_stay_public(secured_client: TestClient, path: str) -> None:
    # A load balancer has to be able to ask whether the task is alive without holding a
    # token, and these endpoints expose nothing but liveness.
    assert secured_client.get(path).status_code == 200


def test_auth_disabled_serves_requests_without_a_token(client: TestClient) -> None:
    # The default backend treats every request as the anonymous principal, which is what
    # keeps the local and container stacks usable; production refuses this backend.
    assert client.get(KB_BASE).status_code == 200


def test_every_api_route_requires_authentication(secured_client: TestClient) -> None:
    """Sweep the OpenAPI document: nothing under the API prefix may answer anonymously.

    This is the test that keeps the baseline honest. A new router that forgets the role
    dependency would be reachable without a token, and this fails instead of the
    deployment failing.
    """
    paths = secured_client.get("/openapi.json").json()["paths"]
    checked = 0

    for path, operations in paths.items():
        if not path.startswith("/api/"):
            continue
        concrete = path.replace("{knowledge_base_id}", "kb-1").replace("{document_id}", "doc-1")
        for method in operations:
            response = secured_client.request(method.upper(), concrete, json={})
            assert response.status_code == 401, f"{method.upper()} {path} answered anonymously"
            checked += 1

    assert checked >= 10, (
        "the sweep found fewer routes than the API has; it is not testing anything"
    )
