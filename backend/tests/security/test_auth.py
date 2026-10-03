"""Tests for the identity port: principals, the role hierarchy and the policy."""

from __future__ import annotations

import pytest

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


def _principal(*groups: str) -> Principal:
    return Principal(subject="sub-1", username="alice", groups=frozenset(groups))


@pytest.mark.parametrize(
    ("held", "required", "allowed"),
    [
        (ADMIN, ADMIN, True),
        (ADMIN, EDITOR, True),
        (ADMIN, VIEWER, True),
        (EDITOR, EDITOR, True),
        (EDITOR, VIEWER, True),
        (EDITOR, ADMIN, False),
        (VIEWER, VIEWER, True),
        (VIEWER, EDITOR, False),
        (VIEWER, ADMIN, False),
        ("unrelated-group", VIEWER, False),
        ("", VIEWER, False),
    ],
)
def test_a_higher_role_satisfies_a_lower_requirement(
    held: str, required: str, allowed: bool
) -> None:
    assert _principal(held).has_role(required) is allowed


def test_only_the_known_groups_are_roles() -> None:
    principal = _principal(VIEWER, "aws-admins", "some-other-group")

    # A pool can carry groups the platform knows nothing about; they must not become
    # privileges just because they are in the token.
    assert principal.roles == frozenset({VIEWER})
    assert principal.has_role("aws-admins") is False


def test_an_unknown_role_is_never_satisfied() -> None:
    assert _principal(ADMIN).has_role("superuser") is False


def test_only_an_admin_is_an_admin() -> None:
    assert _principal(ADMIN).is_admin is True
    assert _principal(EDITOR).is_admin is False
    assert _principal(VIEWER).is_admin is False


def test_authorize_allows_an_empty_requirement() -> None:
    # An endpoint that only needs an authenticated caller states no role.
    authorize(_principal(), required=frozenset())


def test_authorize_allows_a_satisfied_requirement() -> None:
    authorize(_principal(EDITOR), required=frozenset({EDITOR, ADMIN}))


def test_authorize_refuses_an_unsatisfied_requirement() -> None:
    with pytest.raises(ForbiddenError) as caught:
        authorize(_principal(VIEWER), required=frozenset({EDITOR, ADMIN}))

    assert caught.value.status_code == 403
    assert caught.value.code == "FORBIDDEN"
    # The caller is told what would work, and what it actually holds: a 403 that says
    # nothing is a support ticket.
    assert caught.value.details["required_roles"] == sorted([EDITOR, ADMIN])
    assert caught.value.details["held_roles"] == [VIEWER]


def test_the_anonymous_principal_holds_every_role_but_is_not_authenticated() -> None:
    principal = anonymous_principal()

    assert principal.roles == frozenset(ROLE_ORDER)
    assert principal.authenticated is False
    assert principal.subject == "anonymous"


def test_the_anonymous_verifier_satisfies_the_port() -> None:
    verifier = AnonymousTokenVerifier()

    assert isinstance(verifier, TokenVerifier)
    # No token and a token both resolve to the same unauthenticated principal: with
    # authentication switched off there is nothing to verify.
    assert verifier.verify(None) == anonymous_principal()
    assert verifier.verify("anything-at-all") == anonymous_principal()


def test_a_401_carries_a_challenge_header() -> None:
    error = UnauthenticatedError()

    assert error.status_code == 401
    assert error.code == "UNAUTHENTICATED"
    assert error.headers == {"WWW-Authenticate": 'Bearer realm="api"'}
    # The header belongs to the instance, not to the class: a subclass that adds detail
    # must not be able to mutate what every other instance sends.
    error.headers["X-Added"] = "1"
    assert "X-Added" not in UnauthenticatedError().headers


def test_an_unreachable_identity_provider_is_an_upstream_failure() -> None:
    error = AuthenticationUnavailableError()

    # Not a 401: the caller's token may be perfectly good, and telling it to sign in
    # again would send it to fix something that is not broken.
    assert error.status_code == 502
    assert error.code == "AUTH_UNAVAILABLE"
