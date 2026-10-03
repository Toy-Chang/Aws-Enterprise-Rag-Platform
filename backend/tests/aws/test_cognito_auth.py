"""Tests for the Cognito token verifier.

These drive the real adapter: the tokens are signed by a generated RSA key, and the key
document is served by a callable the test controls, so verification, issuer and audience
checks, key rotation and the failure mapping all run for real.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

import pytest

from app.aws.cognito_auth import CognitoTokenVerifier
from app.security.auth import (
    ADMIN,
    EDITOR,
    AuthenticationUnavailableError,
    TokenVerifier,
    UnauthenticatedError,
)
from tests.aws.token_builder import (
    CLIENT_ID,
    ISSUER,
    USERNAME,
    SigningKey,
    access_token_claims,
    id_token_claims,
    unsigned_token,
)


class KeyStore:
    """A controllable stand-in for the pool's JWKS endpoint."""

    def __init__(self, *keys: SigningKey) -> None:
        self.keys = list(keys)
        self.fetches = 0
        self.failure: Exception | None = None
        self.document: dict[str, Any] | None = None

    def __call__(self, uri: str) -> dict[str, Any]:
        self.fetches += 1
        if self.failure is not None:
            raise self.failure
        if self.document is not None:
            return self.document
        return {"keys": [key.jwk for key in self.keys]}


class Clock:
    """A clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def key() -> SigningKey:
    return SigningKey()


@pytest.fixture
def store(key: SigningKey) -> KeyStore:
    return KeyStore(key)


@pytest.fixture
def clock() -> Clock:
    return Clock()


def _verifier(store: KeyStore, clock: Clock, **overrides: Any) -> CognitoTokenVerifier:
    options: dict[str, Any] = {
        "user_pool_id": "eu-west-1_TESTPOOL",
        "client_id": CLIENT_ID,
        "region": "eu-west-1",
        "fetch": store,
        "clock": clock,
    }
    options.update(overrides)
    return CognitoTokenVerifier(**options)


def test_the_verifier_satisfies_the_port(store: KeyStore, clock: Clock) -> None:
    assert isinstance(_verifier(store, clock), TokenVerifier)


def test_the_issuer_and_key_document_are_derived_from_the_pool(
    store: KeyStore, clock: Clock
) -> None:
    verifier = _verifier(store, clock)

    assert verifier.issuer == ISSUER
    assert verifier.jwks_uri == f"{ISSUER}/.well-known/jwks.json"


def test_an_explicit_issuer_and_key_document_are_honoured(store: KeyStore, clock: Clock) -> None:
    verifier = _verifier(
        store,
        clock,
        issuer="https://login.example.com/pool",
        jwks_uri="https://login.example.com/pool/keys",
    )

    assert verifier.issuer == "https://login.example.com/pool"
    assert verifier.jwks_uri == "https://login.example.com/pool/keys"


def test_an_explicit_issuer_does_not_need_a_pool_id(store: KeyStore, clock: Clock) -> None:
    verifier = _verifier(store, clock, user_pool_id=None, issuer="https://login.example.com/pool")

    assert verifier.issuer == "https://login.example.com/pool"


def test_a_pool_without_a_region_cannot_build_an_issuer(store: KeyStore, clock: Clock) -> None:
    with pytest.raises(ValueError, match="region is required"):
        _verifier(store, clock, region=None)


def test_a_pool_is_required_when_no_issuer_is_given(store: KeyStore, clock: Clock) -> None:
    with pytest.raises(ValueError, match="user_pool_id"):
        _verifier(store, clock, user_pool_id=None)


def test_a_client_id_is_required(store: KeyStore, clock: Clock) -> None:
    # Without it, a token issued for any other application in the same pool would be
    # accepted; that is a privilege problem, not a convenience.
    with pytest.raises(ValueError, match="client_id is required"):
        _verifier(store, clock, client_id=None)


def test_a_valid_access_token_becomes_a_principal(
    key: SigningKey, store: KeyStore, clock: Clock
) -> None:
    token = key.sign(access_token_claims())

    principal = _verifier(store, clock).verify(token)

    assert principal.authenticated is True
    assert principal.subject == access_token_claims()["sub"]
    assert principal.username == USERNAME
    assert principal.groups == frozenset({EDITOR})
    assert principal.roles == frozenset({EDITOR})
    assert principal.scopes == frozenset({"openid", "email", "profile"})
    assert principal.claims["token_use"] == "access"


def test_a_valid_id_token_becomes_a_principal(
    key: SigningKey, store: KeyStore, clock: Clock
) -> None:
    # An ID token names the client in ``aud`` instead of ``client_id``; both are accepted
    # because both are what a browser client holds.
    token = key.sign(id_token_claims())

    principal = _verifier(store, clock).verify(token)

    assert principal.authenticated is True
    assert principal.username == USERNAME


def test_groups_are_read_from_a_group_claim_only(
    key: SigningKey, store: KeyStore, clock: Clock
) -> None:
    token = key.sign(access_token_claims(**{"cognito:groups": [ADMIN]}))

    principal = _verifier(store, clock).verify(token)

    assert principal.roles == frozenset({ADMIN})
    assert principal.is_admin is True


def test_a_token_without_groups_has_no_roles(
    key: SigningKey, store: KeyStore, clock: Clock
) -> None:
    claims = access_token_claims()
    claims.pop("cognito:groups")

    principal = _verifier(store, clock).verify(key.sign(claims))

    assert principal.roles == frozenset()


def test_a_single_group_given_as_a_string_is_still_read(
    key: SigningKey, store: KeyStore, clock: Clock
) -> None:
    token = key.sign(access_token_claims(**{"cognito:groups": "editor"}))

    assert _verifier(store, clock).verify(token).roles == frozenset({EDITOR})


def test_no_token_is_refused(store: KeyStore, clock: Clock) -> None:
    with pytest.raises(UnauthenticatedError, match="Authorization header"):
        _verifier(store, clock).verify(None)


def test_an_expired_token_is_refused(key: SigningKey, store: KeyStore, clock: Clock) -> None:
    now = int(time.time())
    token = key.sign(access_token_claims(iat=now - 7200, exp=now - 3600))

    with pytest.raises(UnauthenticatedError, match="expired"):
        _verifier(store, clock).verify(token)


def test_clock_skew_within_the_leeway_is_tolerated(
    key: SigningKey, store: KeyStore, clock: Clock
) -> None:
    now = int(time.time())
    token = key.sign(access_token_claims(iat=now - 3700, exp=now - 30))

    # A service whose clock is a few seconds behind the pool must not reject tokens that
    # the pool still considers valid.
    assert _verifier(store, clock, leeway_seconds=120).verify(token).authenticated is True


def test_a_token_from_another_issuer_is_refused(
    key: SigningKey, store: KeyStore, clock: Clock
) -> None:
    token = key.sign(access_token_claims(iss="https://cognito-idp.eu-west-1.amazonaws.com/other"))

    with pytest.raises(UnauthenticatedError, match="not valid"):
        _verifier(store, clock).verify(token)


def test_a_token_for_another_application_is_refused(
    key: SigningKey, store: KeyStore, clock: Clock
) -> None:
    token = key.sign(access_token_claims(client_id="someone-elses-client"))

    with pytest.raises(UnauthenticatedError, match="another application"):
        _verifier(store, clock).verify(token)


def test_an_id_token_for_another_application_is_refused(
    key: SigningKey, store: KeyStore, clock: Clock
) -> None:
    token = key.sign(id_token_claims(aud="someone-elses-client"))

    with pytest.raises(UnauthenticatedError, match="another application"):
        _verifier(store, clock).verify(token)


def test_a_refresh_token_is_refused(key: SigningKey, store: KeyStore, clock: Clock) -> None:
    # A refresh token can mint new tokens; presenting it to the API must not work.
    token = key.sign(access_token_claims(token_use="refresh"))

    with pytest.raises(UnauthenticatedError, match="neither an access token nor an ID token"):
        _verifier(store, clock).verify(token)


def test_a_token_without_an_expiry_is_refused(
    key: SigningKey, store: KeyStore, clock: Clock
) -> None:
    claims = access_token_claims()
    claims.pop("exp")

    with pytest.raises(UnauthenticatedError, match="not valid"):
        _verifier(store, clock).verify(key.sign(claims))


def test_a_tampered_token_is_refused(key: SigningKey, store: KeyStore, clock: Clock) -> None:
    token = key.sign(access_token_claims())
    header, payload, signature = token.split(".")
    forged = json.loads(_decode(payload))
    forged["cognito:groups"] = [ADMIN]

    from tests.aws.token_builder import _segment

    with pytest.raises(UnauthenticatedError, match="not valid"):
        _verifier(store, clock).verify(f"{header}.{_segment(forged)}.{signature}")


def test_an_unsigned_token_is_refused_before_any_key_is_looked_up(
    store: KeyStore, clock: Clock
) -> None:
    with pytest.raises(UnauthenticatedError, match="RS256"):
        _verifier(store, clock).verify(unsigned_token(access_token_claims()))

    assert store.fetches == 0


def test_an_hmac_token_signed_with_the_public_key_is_refused(
    key: SigningKey, store: KeyStore, clock: Clock
) -> None:
    # The classic confusion attack: the verifier's public key is not a shared secret, and
    # a token that treats it as one must never verify.
    forged = key.sign(
        access_token_claims(**{"cognito:groups": [ADMIN]}),
        algorithm="HS256",
        key=_public_key_material(key),
    )

    with pytest.raises(UnauthenticatedError, match="RS256"):
        _verifier(store, clock).verify(forged)


def test_a_token_without_a_key_identifier_is_refused(
    key: SigningKey, store: KeyStore, clock: Clock
) -> None:
    token = key.sign(access_token_claims(), headers={"kid": ""})

    with pytest.raises(UnauthenticatedError, match="key identifier"):
        _verifier(store, clock).verify(token)


def test_garbage_is_refused(store: KeyStore, clock: Clock) -> None:
    with pytest.raises(UnauthenticatedError, match="not a valid JWT"):
        _verifier(store, clock).verify("this-is-not-a-token")


def test_an_unknown_key_is_refused_after_one_refresh(store: KeyStore, clock: Clock) -> None:
    # The pool rotated: the first document did not have the key, and the miss is what
    # makes the verifier fetch again.
    other = SigningKey(kid="rotated-in")
    token = other.sign(access_token_claims(), kid="rotated-in")

    verifier = _verifier(store, clock)
    with pytest.raises(UnauthenticatedError, match="does not publish"):
        verifier.verify(token)

    assert store.fetches == 2


def test_a_rotation_is_picked_up(key: SigningKey, store: KeyStore, clock: Clock) -> None:
    rotated = SigningKey(kid="rotated-in")
    token = rotated.sign(access_token_claims(), kid="rotated-in")
    verifier = _verifier(store, clock)
    store.keys.append(rotated)

    assert verifier.verify(token).subject == access_token_claims()["sub"]


def test_the_miss_path_is_rate_limited(store: KeyStore, clock: Clock) -> None:
    # The key identifier comes from the caller, so an unknown one must not let anyone make
    # the service fetch the key document on every request.
    verifier = _verifier(store, clock)
    unknown = SigningKey(kid="never-published")
    token = unknown.sign(access_token_claims(), kid="never-published")

    for _ in range(3):
        with pytest.raises(UnauthenticatedError):
            verifier.verify(token)

    assert store.fetches == 2


def test_the_key_document_is_cached(key: SigningKey, store: KeyStore, clock: Clock) -> None:
    verifier = _verifier(store, clock, cache_seconds=3600)
    token = key.sign(access_token_claims())

    verifier.verify(token)
    verifier.verify(token)

    assert store.fetches == 1


def test_the_key_document_is_refreshed_after_its_lifespan(
    key: SigningKey, store: KeyStore, clock: Clock
) -> None:
    verifier = _verifier(store, clock, cache_seconds=300)
    token = key.sign(access_token_claims())
    verifier.verify(token)

    clock.advance(301)
    verifier.verify(token)

    assert store.fetches == 2


def test_the_key_document_can_be_uncached(key: SigningKey, store: KeyStore, clock: Clock) -> None:
    verifier = _verifier(store, clock, cache_seconds=0)
    token = key.sign(access_token_claims())

    verifier.verify(token)
    verifier.verify(token)

    assert store.fetches == 2


def test_an_unreachable_key_document_is_an_upstream_failure(store: KeyStore, clock: Clock) -> None:
    # Whatever a key source throws -- HTTPS, a proxy, an injected client -- an unreachable
    # key set is an upstream failure and not an unhandled error in this process.
    store.failure = OSError("connection refused")

    with pytest.raises(AuthenticationUnavailableError, match="could not be reached"):
        _verifier(store, clock).verify(SigningKey().sign(access_token_claims()))


class FakeResponse:
    """The bit of an HTTP response the default key fetch uses."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> bool:
        return False


def _serve(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> list[str]:
    """Point the real fetch at a canned response and record what it asked for."""
    requested: list[str] = []

    def fake_urlopen(uri: str, timeout: float | None = None) -> FakeResponse:
        requested.append(uri)
        return FakeResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return requested


def test_the_default_key_fetch_reads_the_published_document(
    key: SigningKey, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The default fetch is the only code in this adapter that touches the network, so it
    # is exercised for real here against a canned HTTP response.
    requested = _serve(monkeypatch, json.dumps(key.jwks).encode())
    verifier = CognitoTokenVerifier(
        user_pool_id="eu-west-1_TESTPOOL",
        client_id=CLIENT_ID,
        region="eu-west-1",
        clock=clock,
    )

    principal = verifier.verify(key.sign(access_token_claims()))

    assert principal.username == USERNAME
    assert requested == [f"{ISSUER}/.well-known/jwks.json"]


def test_a_key_document_that_is_not_json_is_an_upstream_failure(
    key: SigningKey, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, b"<html>not a key set</html>")
    verifier = CognitoTokenVerifier(
        user_pool_id="eu-west-1_TESTPOOL",
        client_id=CLIENT_ID,
        region="eu-west-1",
        clock=clock,
    )

    with pytest.raises(AuthenticationUnavailableError, match="not JSON"):
        verifier.verify(key.sign(access_token_claims()))


def test_a_key_document_that_is_a_list_is_an_upstream_failure(
    key: SigningKey, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, b'[{"kid": "test-key-1"}]')
    verifier = CognitoTokenVerifier(
        user_pool_id="eu-west-1_TESTPOOL",
        client_id=CLIENT_ID,
        region="eu-west-1",
        clock=clock,
    )

    with pytest.raises(AuthenticationUnavailableError, match="not a JSON object"):
        verifier.verify(key.sign(access_token_claims()))


def test_an_unreachable_host_is_an_upstream_failure(
    key: SigningKey, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(uri: str, timeout: float | None = None) -> FakeResponse:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    verifier = CognitoTokenVerifier(
        user_pool_id="eu-west-1_TESTPOOL",
        client_id=CLIENT_ID,
        region="eu-west-1",
        clock=clock,
    )

    with pytest.raises(AuthenticationUnavailableError, match="could not be fetched"):
        verifier.verify(key.sign(access_token_claims()))


def test_a_key_document_that_is_not_a_document_is_an_upstream_failure(
    key: SigningKey, store: KeyStore, clock: Clock
) -> None:
    store.document = {"not": "a jwks"}

    with pytest.raises(AuthenticationUnavailableError, match="no usable key set"):
        _verifier(store, clock).verify(key.sign(access_token_claims()))


def test_a_key_that_cannot_be_parsed_is_an_upstream_failure(
    key: SigningKey, store: KeyStore, clock: Clock
) -> None:
    store.document = {"keys": [{"kid": "test-key-1", "kty": "oct", "k": "c2VjcmV0"}]}

    with pytest.raises(AuthenticationUnavailableError, match="cannot be used"):
        _verifier(store, clock).verify(key.sign(access_token_claims()))


def _public_key_material(key: SigningKey) -> str:
    """The public key as plain base64, which is what an attacker can fetch and reuse."""
    return "".join(key.public_pem.decode().splitlines()[1:-1])


def _decode(segment: str) -> str:
    import base64

    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding).decode()
