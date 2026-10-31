# SPDX-License-Identifier: AGPL-3.0-or-later
"""Google sign-in (OpenID Connect, authorization code flow with PKCE).

Network access sits behind :class:`OidcClient` so tests can replace it. ID
tokens are verified locally against Google's published signing keys:
signature, issuer, audience, expiry and the nonce from our own request, and
the email address must be verified by Google.
"""

import base64
import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx2
import jwt
from anyio import to_thread

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 (a URL, not a password)
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")


class OidcError(Exception):
    """Google sign-in could not be completed. The message is safe to log."""


@dataclass(frozen=True)
class Identity:
    subject: str
    email: str
    name: str


def pkce_pair() -> tuple[str, str]:
    """A PKCE code verifier and its S256 challenge."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def verify_id_token(
    token: str,
    *,
    client_id: str,
    nonce: str,
    signing_key: Callable[[str], Any],
    leeway: int = 60,
) -> Identity:
    """Check a Google ID token and return who it identifies.

    ``signing_key`` maps the raw token to the public key that should have
    signed it (normally looked up by ``kid`` in Google's JWKS).
    """
    try:
        claims = jwt.decode(
            token,
            key=signing_key(token),
            algorithms=["RS256"],
            audience=client_id,
            issuer=list(ISSUERS),
            leeway=leeway,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise OidcError(f"ID token rejected: {exc}") from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OidcError("ID token nonce does not match this sign-in")
    if claims.get("email_verified") is not True or not claims.get("email"):
        raise OidcError("Google account email is not verified")
    return Identity(
        subject=str(claims["sub"]),
        email=str(claims["email"]).lower(),
        name=str(claims.get("name") or claims["email"]).strip()[:100],
    )


class OidcClient(Protocol):
    def authorization_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str: ...

    async def identify(
        self, *, code: str, code_verifier: str, redirect_uri: str, nonce: str
    ) -> Identity: ...


class GoogleClient:
    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        # Caches Google's keys and refetches when an unknown key id appears.
        self._jwks = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600)

    def authorization_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str:
        query = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    async def identify(
        self, *, code: str, code_verifier: str, redirect_uri: str, nonce: str
    ) -> Identity:
        try:
            async with httpx2.AsyncClient(timeout=10) as http:
                response = await http.post(
                    TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "code_verifier": code_verifier,
                        "redirect_uri": redirect_uri,
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                )
        except httpx2.HTTPError as exc:
            raise OidcError(f"could not reach Google: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise OidcError(f"Google refused the sign-in code (HTTP {response.status_code})")
        id_token = response.json().get("id_token")
        if not isinstance(id_token, str):
            raise OidcError("Google returned no ID token")

        def key_for(token: str) -> Any:
            return self._jwks.get_signing_key_from_jwt(token).key

        # PyJWKClient fetches keys with blocking I/O.
        return await to_thread.run_sync(
            lambda: verify_id_token(
                id_token, client_id=self._client_id, nonce=nonce, signing_key=key_for
            )
        )
