"""Identity, authentication and authorization.

The port lives in :mod:`app.security.auth` and the Cognito implementation lives with
the other AWS adapters, so a service never imports either one.
"""

from __future__ import annotations

from app.security.auth import (
    ADMIN,
    EDITOR,
    ROLE_ORDER,
    VIEWER,
    AnonymousTokenVerifier,
    AuthenticationUnavailableError,
    ForbiddenError,
    Principal,
    TokenVerifier,
    UnauthenticatedError,
    anonymous_principal,
    authorize,
)

__all__ = [
    "ADMIN",
    "EDITOR",
    "ROLE_ORDER",
    "VIEWER",
    "AnonymousTokenVerifier",
    "AuthenticationUnavailableError",
    "ForbiddenError",
    "Principal",
    "TokenVerifier",
    "UnauthenticatedError",
    "anonymous_principal",
    "authorize",
]
