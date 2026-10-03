"""Authentication and authorization, expressed as a port.

The API needs two things from an identity provider: proof that a bearer token was
issued by it, and the roles that token carries. Both arrive through
:class:`TokenVerifier`, so the web layer never imports a JWT library and the local
stack can run with authentication switched off entirely.

Roles are groups in the identity provider. The platform understands three, in
increasing order of privilege, and a caller holding a higher role satisfies a
requirement for a lower one: that keeps the policy readable as "this is the least
privilege that can perform the action" instead of an enumeration of every role that
is allowed to.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.core.errors import AppError

#: Read the platform: knowledge bases, documents, passages, metrics and queries.
VIEWER = "viewer"
#: Change the corpus: upload, reprocess and delete documents.
EDITOR = "editor"
#: Change the platform itself: create and delete knowledge bases, run evaluations.
ADMIN = "admin"

#: Every role the platform knows, ordered from least to most privileged.
ROLE_ORDER: tuple[str, ...] = (VIEWER, EDITOR, ADMIN)


class UnauthenticatedError(AppError):
    """The request carried no usable credentials.

    The challenge header is part of the response, not a nicety: a 401 without
    ``WWW-Authenticate`` tells a client that it failed but not how to succeed.
    """

    status_code = 401
    code = "UNAUTHENTICATED"
    message = "A valid access token is required."
    headers = {"WWW-Authenticate": 'Bearer realm="api"'}


class ForbiddenError(AppError):
    """The caller is authenticated but does not hold the required role."""

    status_code = 403
    code = "FORBIDDEN"
    message = "The authenticated principal is not allowed to perform this action."


class AuthenticationUnavailableError(AppError):
    """The identity provider could not be reached or answered with nonsense.

    An unreachable key set is not the caller's fault and not a defect here, so it is
    reported as the upstream failure it is. Answering 401 instead would tell a caller
    with a perfectly good token to go and get a new one.
    """

    status_code = 502
    code = "AUTH_UNAVAILABLE"
    message = "The identity provider could not be reached."


@dataclass(frozen=True)
class Principal:
    """Who is making the request.

    ``claims`` is kept whole so that an audit trail can record the token's contents
    without every consumer having to know which claim it needed.
    """

    subject: str
    username: str
    groups: frozenset[str] = field(default_factory=frozenset)
    scopes: frozenset[str] = field(default_factory=frozenset)
    claims: Mapping[str, Any] = field(default_factory=dict)
    authenticated: bool = True

    @property
    def roles(self) -> frozenset[str]:
        """The platform roles this principal holds, ignoring any other group."""
        return frozenset(group for group in self.groups if group in ROLE_ORDER)

    def has_role(self, role: str) -> bool:
        """Return whether this principal's roles satisfy ``role``."""
        if role not in ROLE_ORDER:
            return False
        floor = ROLE_ORDER.index(role)
        return any(ROLE_ORDER.index(held) >= floor for held in self.roles)

    @property
    def is_admin(self) -> bool:
        """Return whether this principal may change the platform itself."""
        return self.has_role(ADMIN)


def anonymous_principal() -> Principal:
    """The principal used when authentication is switched off.

    It holds every role, so a deployment with ``auth_backend=none`` behaves exactly as
    it did before authorization existed, and it is marked unauthenticated so that
    nothing can mistake it for a verified identity. The configuration refuses this
    backend in production for the same reason it exists at all.
    """
    return Principal(
        subject="anonymous",
        username="anonymous",
        groups=frozenset(ROLE_ORDER),
        authenticated=False,
    )


@runtime_checkable
class TokenVerifier(Protocol):
    """Turns the bearer token a request carried into the principal it identifies.

    ``token`` is ``None`` when the request carried no credentials at all, because a
    verifier that accepts unauthenticated requests has to be able to say so. Any
    verifier that requires a token raises :class:`UnauthenticatedError` for it.
    """

    def verify(self, token: str | None) -> Principal: ...


class AnonymousTokenVerifier:
    """The verifier used when ``auth_backend`` is ``none``.

    Every request is the anonymous principal, including one that carried no token.
    """

    def verify(self, token: str | None) -> Principal:
        return anonymous_principal()


def authorize(principal: Principal, *, required: frozenset[str]) -> None:
    """Raise :class:`ForbiddenError` unless the principal satisfies ``required``.

    An empty requirement means the action only needs an authenticated caller, which
    the dependency has already established.
    """
    if not required or any(principal.has_role(role) for role in required):
        return
    raise ForbiddenError(
        "This action requires one of these roles: " + ", ".join(sorted(required)) + ".",
        details={
            "required_roles": sorted(required),
            "held_roles": sorted(principal.roles),
        },
    )
