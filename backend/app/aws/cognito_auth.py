"""Cognito user-pool tokens, verified against the pool's published signing keys.

A Cognito token is a signed JWT, so the API verifies the signature against the pool's
JWKS document and then checks the issuer, the application it was issued for and what
the token is for. The key document is fetched over HTTPS rather than through ``boto3``:
verification needs no AWS credentials and no AWS SDK, only the ``auth`` extra for JWT
parsing and RSA verification.

The imports of that extra are deferred, like every other adapter here, so a deployment
that runs with ``auth_backend=none`` never needs it installed.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from functools import lru_cache
from typing import Any

from app.security.auth import (
    AuthenticationUnavailableError,
    Principal,
    UnauthenticatedError,
)

#: Cognito signs with RS256. Anything else is refused before a key is looked up, which
#: is what stops the classic confusion attack: an ``HS256`` token "signed" with the
#: pool's public key as if it were a shared secret must never verify.
ALGORITHMS: tuple[str, ...] = ("RS256",)

#: An access token is what an API should be called with; an ID token is accepted too,
#: because a browser client has one and the difference matters less than rejecting a
#: refresh token, which cannot be used against the API at all.
TOKEN_USES: tuple[str, ...] = ("access", "id")

JWKS_PATH = "/.well-known/jwks.json"
FETCH_TIMEOUT_SECONDS = 5.0
#: The key identifier comes from the caller, so an unknown one must not turn every
#: request into an outbound fetch.
MISS_REFRESH_SECONDS = 30.0


@lru_cache(maxsize=1)
def _jwt() -> Any:
    """Import PyJWT on first use, with a failure that names the fix."""
    try:
        import jwt
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on the install
        raise RuntimeError(
            "the Cognito token verifier needs a JWT library: install the 'auth' extra "
            "(pip install -e '.[auth]') or set APP_AUTH_BACKEND=none"
        ) from exc
    return jwt


@lru_cache(maxsize=1)
def _rsa_algorithm() -> Any:
    """Return the RSA key parser of the JWT library."""
    _jwt()
    from jwt.algorithms import RSAAlgorithm

    return RSAAlgorithm


class CognitoTokenVerifier:
    """Verifies the tokens of one user pool and app client."""

    def __init__(
        self,
        *,
        user_pool_id: str | None = None,
        client_id: str | None = None,
        region: str | None = None,
        issuer: str | None = None,
        jwks_uri: str | None = None,
        cache_seconds: float = 3600.0,
        leeway_seconds: float = 60.0,
        fetch: Callable[[str], Mapping[str, Any]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._user_pool_id = (user_pool_id or "").strip()
        self._client_id = (client_id or "").strip()
        self._region = (region or "").strip()

        configured_issuer = (issuer or "").strip()
        if not configured_issuer:
            if not self._user_pool_id:
                raise ValueError("a user_pool_id or an explicit issuer is required")
            if not self._region:
                raise ValueError("a region is required to derive the issuer of a user pool")
            configured_issuer = (
                f"https://cognito-idp.{self._region}.amazonaws.com/{self._user_pool_id}"
            )
        if not self._client_id:
            raise ValueError(
                "a client_id is required: without it a token issued for any other "
                "application in the pool would be accepted"
            )

        self._issuer = configured_issuer
        self._jwks_uri = (jwks_uri or "").strip() or f"{self._issuer}{JWKS_PATH}"
        self._leeway = leeway_seconds
        self._keys = _JwksCache(
            self._jwks_uri,
            lifespan_seconds=cache_seconds,
            fetch=fetch,
            clock=clock,
        )

    @property
    def issuer(self) -> str:
        """The issuer every accepted token has to carry."""
        return self._issuer

    @property
    def jwks_uri(self) -> str:
        """Where the pool publishes its signing keys."""
        return self._jwks_uri

    def verify(self, token: str | None) -> Principal:
        """Return the principal ``token`` identifies, or raise a deliberate error."""
        if not token:
            raise UnauthenticatedError("An Authorization header with a bearer token is required.")

        jwt = _jwt()
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise UnauthenticatedError("The access token is not a valid JWT.") from exc

        if header.get("alg") not in ALGORITHMS:
            raise UnauthenticatedError(
                "The access token is not signed with RS256, the only algorithm this "
                "user pool signs with."
            )
        kid = str(header.get("kid") or "")
        if not kid:
            raise UnauthenticatedError("The access token carries no key identifier.")

        key = self._keys.signing_key(kid)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=list(ALGORITHMS),
                issuer=self._issuer,
                # The audience is checked by hand below: a Cognito *access* token names
                # the client in ``client_id`` and carries no ``aud`` at all, so the
                # library's audience check would reject every access token.
                options={
                    "require": ["exp", "iat", "iss", "sub"],
                    "verify_aud": False,
                },
                leeway=self._leeway,
            )
        except jwt.ExpiredSignatureError as exc:
            raise UnauthenticatedError("The access token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise UnauthenticatedError("The access token is not valid.") from exc

        self._check_purpose(claims)
        self._check_application(claims)
        return _principal_from_claims(claims)

    def _check_purpose(self, claims: Mapping[str, Any]) -> None:
        """Refuse a token that was not issued to be presented to an API."""
        if claims.get("token_use") not in TOKEN_USES:
            raise UnauthenticatedError("The token is neither an access token nor an ID token.")

    def _check_application(self, claims: Mapping[str, Any]) -> None:
        """Refuse a token issued for another application in the same pool."""
        audiences = claims.get("aud") or []
        if isinstance(audiences, str):
            audiences = [audiences]
        issued_for = {str(audience) for audience in audiences}
        issued_for.add(str(claims.get("client_id") or ""))
        if self._client_id not in issued_for:
            raise UnauthenticatedError("The access token was issued for another application.")


def _principal_from_claims(claims: Mapping[str, Any]) -> Principal:
    """Build the principal a verified token describes."""
    groups = claims.get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [groups]
    subject = str(claims.get("sub") or "")
    return Principal(
        subject=subject,
        # Cognito puts the user name in ``username`` on an ID token and in
        # ``cognito:username`` on an access token.
        username=str(claims.get("cognito:username") or claims.get("username") or subject),
        groups=frozenset(str(group) for group in groups),
        scopes=frozenset(str(claims.get("scope") or "").split()),
        claims=dict(claims),
        authenticated=True,
    )


class _JwksCache:
    """The pool's signing keys, fetched once and refreshed when a key is unknown.

    Two refreshes are deliberately different things. The lifespan refresh keeps a
    long-running process aware of a rotation it has not seen a token for; the key-miss
    refresh is what makes the first request after a rotation work. Only the second one
    is rate limited, because it is triggered by a value the caller controls.
    """

    def __init__(
        self,
        uri: str,
        *,
        lifespan_seconds: float,
        fetch: Callable[[str], Mapping[str, Any]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        miss_interval_seconds: float = MISS_REFRESH_SECONDS,
    ) -> None:
        self._uri = uri
        self._lifespan = max(0.0, float(lifespan_seconds))
        self._miss_interval = max(0.0, float(miss_interval_seconds))
        self._fetch = fetch or _fetch_jwks
        self._clock = clock
        self._keys: dict[str, Any] = {}
        self._fetched_at: float | None = None
        self._missed_at: float | None = None

    def signing_key(self, kid: str) -> Any:
        """Return the public key for ``kid``, or raise when the pool has no such key."""
        if self._expired():
            self._refresh()

        jwk = self._keys.get(kid)
        if jwk is None and self._may_refresh_after_miss():
            self._refresh()
            jwk = self._keys.get(kid)
        if jwk is None:
            raise UnauthenticatedError(
                "The access token was signed with a key this user pool does not publish."
            )
        return _public_key(jwk)

    def _expired(self) -> bool:
        if self._fetched_at is None:
            return True
        return (self._clock() - self._fetched_at) >= self._lifespan

    def _may_refresh_after_miss(self) -> bool:
        now = self._clock()
        if self._missed_at is not None and (now - self._missed_at) < self._miss_interval:
            return False
        self._missed_at = now
        return True

    def _refresh(self) -> None:
        try:
            document = self._fetch(self._uri)
        except AuthenticationUnavailableError:
            raise
        except Exception as exc:
            # A key source is I/O: the default one is HTTPS, and a deployment can inject
            # its own. Whatever it throws, an unreachable key set is an upstream failure
            # rather than an unhandled error in this process.
            raise AuthenticationUnavailableError(
                "The identity provider could not be reached."
            ) from exc
        keys = document.get("keys") if isinstance(document, Mapping) else None
        if not isinstance(keys, list):
            raise AuthenticationUnavailableError(
                "The identity provider published no usable key set."
            )
        refreshed: dict[str, Any] = {}
        for jwk in keys:
            if isinstance(jwk, Mapping) and jwk.get("kid"):
                refreshed[str(jwk["kid"])] = jwk
        self._keys = refreshed
        self._fetched_at = self._clock()


def _public_key(jwk: Mapping[str, Any]) -> Any:
    """Turn one published JWK into a verification key."""
    try:
        return _rsa_algorithm().from_jwk(json.dumps(dict(jwk)))
    except Exception as exc:
        # The library raises a handful of unrelated types for an unusable key, and none
        # of them tells the caller anything useful.
        raise AuthenticationUnavailableError(
            "The identity provider published a key that cannot be used."
        ) from exc


def _fetch_jwks(uri: str) -> Mapping[str, Any]:
    """Fetch the pool's key document: the only network call this adapter makes."""
    try:
        with urllib.request.urlopen(uri, timeout=FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310
            payload = response.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AuthenticationUnavailableError(f"The key set at {uri} could not be fetched.") from exc

    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AuthenticationUnavailableError(
            "The identity provider published a key set that is not JSON."
        ) from exc
    if not isinstance(document, Mapping):
        raise AuthenticationUnavailableError(
            "The identity provider published a key set that is not a JSON object."
        )
    return document
