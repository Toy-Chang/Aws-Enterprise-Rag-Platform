"""Tests for reading the database URL out of Secrets Manager.

The ECS path resolves the same secret into ``APP_DATABASE_URL`` before the container
starts, so this module only has to cover the Lambda path: the deployed secret's shape and
every way reading it can go wrong.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import pytest

from app.aws.secrets import SecretResolutionError, resolve_database_url

SECRET_ARN = (
    "arn:aws:secretsmanager:eu-west-1:123456789012:secret:"
    "rag-platform-production-database-url-AbCdEf"
)

URL = "postgresql+psycopg://rag_admin:pw@db.example.internal:5432/rag"


class StubSecretsManager:
    """A Secrets Manager client that returns what the test tells it to."""

    def __init__(self, response: dict[str, Any] | None = None, failure: Exception | None = None):
        self.response = response
        self.failure = failure
        self.calls: list[dict[str, Any]] = []

    def get_secret_value(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return self.response if self.response is not None else {}


def _document(**overrides: Any) -> str:
    payload: dict[str, Any] = {
        "username": "rag_admin",
        "password": "pw",
        "host": "db.example.internal",
        "port": 5432,
        "dbname": "rag",
        "url": URL,
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_the_url_is_read_from_the_secret() -> None:
    client = StubSecretsManager({"SecretString": _document()})

    assert resolve_database_url(SECRET_ARN, client=client) == URL
    assert client.calls == [{"SecretId": SECRET_ARN}]


def test_the_other_entries_are_ignored() -> None:
    # The parts are there for a job that needs them; this process only consumes the URL.
    client = StubSecretsManager({"SecretString": json.dumps({"url": URL, "extra": "ignored"})})

    assert resolve_database_url(SECRET_ARN, client=client) == URL


def test_a_secret_that_cannot_be_read_names_the_secret() -> None:
    client = StubSecretsManager(failure=RuntimeError("AccessDeniedException"))

    with pytest.raises(SecretResolutionError) as caught:
        resolve_database_url(SECRET_ARN, client=client)

    # The ARN is in the message because "the secret could not be read" is not actionable
    # when a deployment has several.
    assert SECRET_ARN in caught.value.message
    assert caught.value.code == "SECRET_UNAVAILABLE"
    assert caught.value.status_code == 502


def test_a_binary_secret_is_refused() -> None:
    client = StubSecretsManager({"SecretBinary": b"not-a-string"})

    with pytest.raises(SecretResolutionError, match="no string value"):
        resolve_database_url(SECRET_ARN, client=client)


def test_a_secret_that_is_not_json_is_refused() -> None:
    client = StubSecretsManager({"SecretString": "postgresql+psycopg://user:pw@host:5432/db"})

    with pytest.raises(SecretResolutionError, match="not a JSON document"):
        resolve_database_url(SECRET_ARN, client=client)


def test_a_secret_that_is_not_an_object_is_refused() -> None:
    client = StubSecretsManager({"SecretString": json.dumps([URL])})

    with pytest.raises(SecretResolutionError, match="not a JSON object"):
        resolve_database_url(SECRET_ARN, client=client)


@pytest.mark.parametrize("document", [{}, {"url": ""}, {"url": None}, {"url": 42}])
def test_a_secret_without_a_usable_url_is_refused(document: dict[str, Any]) -> None:
    client = StubSecretsManager({"SecretString": json.dumps(document)})

    with pytest.raises(SecretResolutionError, match="no 'url' entry"):
        resolve_database_url(SECRET_ARN, client=client)


def test_the_client_is_only_built_when_one_is_not_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[tuple[str, str | None]] = []

    class FakeBoto3:
        @staticmethod
        def client(service: str, region_name: str | None = None) -> StubSecretsManager:
            built.append((service, region_name))
            return StubSecretsManager({"SecretString": _document()})

    monkeypatch.setitem(sys.modules, "boto3", FakeBoto3)

    assert resolve_database_url(SECRET_ARN, region="eu-west-1") == URL
    assert built == [("secretsmanager", "eu-west-1")]


def test_a_missing_sdk_names_the_extra_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    # A deployment that installed the base package gets told what to install, not an
    # opaque ImportError from inside an adapter.
    monkeypatch.setitem(sys.modules, "boto3", None)

    with pytest.raises(RuntimeError, match=r"pip install \"\.\[aws\]\""):
        resolve_database_url(SECRET_ARN)
