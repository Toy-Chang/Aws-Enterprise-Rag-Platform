"""Reading configuration out of Secrets Manager.

The API never calls this: an ECS task definition resolves ``secrets.valueFrom`` before the
container starts, so the process sees a plain ``APP_DATABASE_URL``. A Lambda has no such
mechanism, so the ingestion consumer is given the secret's *ARN* and resolves the same URL
itself on cold start. Both processes end up with the identical value, which is what makes
"a document is ingested the same way whoever asked" true in a deployment and not only in a
test.

The secret carries a JSON document with the parts (``username``, ``password``, ``host``,
``port``, ``dbname``) and the assembled ``url``. Only the URL is read here, because that is
what the application consumes.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.errors import AppError

#: Key in the secret document that holds the assembled SQLAlchemy URL.
SECRET_URL_KEY = "url"


class SecretResolutionError(AppError):
    """The process cannot read the configuration it was pointed at.

    An upstream failure rather than a caller error: the deployed secret may be missing,
    the role may lack ``secretsmanager:GetSecretValue``, or Secrets Manager may be
    unreachable. A Lambda that raises this fails its invocation, so the message is
    retried and the failure shows up in the error alarm instead of starting a process
    with a wrong database.
    """

    status_code = 502
    code = "SECRET_UNAVAILABLE"
    default_message = "The configuration secret could not be read."


def resolve_database_url(
    secret_arn: str,
    *,
    region: str | None = None,
    client: Any | None = None,
) -> str:
    """Return the database URL stored in ``secret_arn``.

    Args:
        secret_arn: Identifier of the secret, with or without a version or stage suffix.
        region: Region of the secret. Defaults to the SDK's ambient region, which both
            Lambda and ECS set from the environment.
        client: An injected Secrets Manager client. Tests pass a stub; production passes
            nothing and gets a real one.
    """
    secrets = client if client is not None else _secrets_client(region)

    try:
        response = secrets.get_secret_value(SecretId=secret_arn)
    except SecretResolutionError:
        raise
    except Exception as exc:
        # Whatever the SDK throws -- an access denial, a missing secret, a timeout -- the
        # process cannot continue, and the message has to name the secret to be actionable.
        raise SecretResolutionError(
            f"The secret '{secret_arn}' could not be read: {exc}"
        ) from exc

    payload = response.get("SecretString")
    if payload is None:
        raise SecretResolutionError(
            f"The secret '{secret_arn}' holds no string value; the database URL is expected in a JSON document."
        )

    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SecretResolutionError(
            f"The secret '{secret_arn}' is not a JSON document."
        ) from exc

    if not isinstance(document, dict):
        raise SecretResolutionError(
            f"The secret '{secret_arn}' is not a JSON object."
        )

    url = document.get(SECRET_URL_KEY)
    if not isinstance(url, str) or not url.strip():
        raise SecretResolutionError(
            f"The secret '{secret_arn}' has no '{SECRET_URL_KEY}' entry with a database URL."
        )

    return url


def _secrets_client(region: str | None) -> Any:
    """Build a Secrets Manager client, or explain what is missing."""
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - depends on the installation
        raise RuntimeError(
            "Reading the database URL from Secrets Manager needs the AWS dependencies. "
            'Install them with: pip install ".[aws]"'
        ) from exc

    return boto3.client("secretsmanager", region_name=region)
