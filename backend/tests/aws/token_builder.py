"""Build real Cognito-shaped tokens for the verifier tests.

The tokens are signed with a locally generated RSA key, so the verifier exercises its real
code path -- signature verification, issuer, audience and purpose checks -- with no
network and no AWS account. A stub that returned a claims dictionary would test the
verifier's own branches and nothing else.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_TESTPOOL"
CLIENT_ID = "1a2b3c4d5e6f7g8h9i0jklmnop"
USERNAME = "alice"
SUBJECT = "6f0d1f4e-4b1a-4c8f-9c1a-2b3c4d5e6f70"


class SigningKey:
    """A generated RSA key pair and the JWKS entry that publishes the public half."""

    def __init__(self, kid: str = "test-key-1") -> None:
        self.kid = kid
        self._private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.private_pem = self._private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self.public_pem = self._private.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.jwk: dict[str, Any] = json.loads(
            jwt.algorithms.RSAAlgorithm.to_jwk(self._private.public_key())
        )
        self.jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})

    @property
    def jwks(self) -> dict[str, Any]:
        """The key document the pool would publish."""
        return {"keys": [self.jwk]}

    def sign(
        self,
        claims: dict[str, Any],
        *,
        kid: str | None = None,
        algorithm: str = "RS256",
        key: Any = None,
        headers: dict[str, Any] | None = None,
    ) -> str:
        """Sign claims into a token, defaulting to this key and RS256."""
        merged = {"kid": kid if kid is not None else self.kid}
        merged.update(headers or {})
        return jwt.encode(
            claims,
            self.private_pem if key is None else key,
            algorithm=algorithm,
            headers=merged,
        )


def access_token_claims(**overrides: Any) -> dict[str, Any]:
    """The claims of a Cognito *access* token: the client is in ``client_id``."""
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": SUBJECT,
        "iss": ISSUER,
        "client_id": CLIENT_ID,
        "token_use": "access",
        "username": USERNAME,
        "cognito:username": USERNAME,
        "cognito:groups": ["editor"],
        "scope": "openid email profile",
        "iat": now,
        "exp": now + 3600,
        "jti": "0d3d4e0a-4a4a-4a4a-9a9a-1b1b1b1b1b1b",
        "auth_time": now,
        "origin_jti": "b1b1b1b1-2c2c-2c2c-8d8d-3e3e3e3e3e3e",
    }
    claims.update(overrides)
    return claims


def id_token_claims(**overrides: Any) -> dict[str, Any]:
    """The claims of a Cognito *ID* token: the client is in ``aud``."""
    claims = access_token_claims()
    claims.pop("client_id")
    claims.update(
        {
            "aud": CLIENT_ID,
            "token_use": "id",
            "email": "alice@example.com",
            "email_verified": True,
        }
    )
    claims.update(overrides)
    return claims


def unsigned_token(claims: dict[str, Any], *, algorithm: str = "none") -> str:
    """An alg=none token, which nothing may accept."""
    header = {"alg": algorithm, "typ": "JWT", "kid": "test-key-1"}
    return f"{_segment(header)}.{_segment(claims)}."


def _segment(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")
