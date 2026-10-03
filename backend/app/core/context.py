"""Request-scoped context shared across the application.

The request identifier lives in a :mod:`contextvars` variable so that any layer
(middleware, services, integrations) can attach it to log records without
threading it through every function signature.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

_REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_request_id() -> str:
    """Return a new opaque correlation identifier."""
    return uuid.uuid4().hex


def get_request_id() -> str | None:
    """Return the identifier of the request currently being handled, if any."""
    return _REQUEST_ID.get()


def set_request_id(request_id: str) -> Token[str | None]:
    """Bind ``request_id`` to the current context and return a reset token."""
    return _REQUEST_ID.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous identifier using a token from :func:`set_request_id`."""
    _REQUEST_ID.reset(token)
