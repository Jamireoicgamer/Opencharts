# SPDX-License-Identifier: AGPL-3.0-or-later
"""Google sign-in: ID-token checks, and the link / sign-in / invite flows
against a fake Google."""

import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from pydantic import SecretStr

from openchart_api.config import Settings
from openchart_api.main import create_app
from openchart_api.oidc import Identity, OidcError, verify_id_token

from .conftest import ORIGIN, OWNER, SETUP_TOKEN
from .test_mfa import enable_totp

pytestmark = pytest.mark.anyio

CLIENT_ID = "test-client.apps.googleusercontent.com"

# ID token verification --------------------------------------------------------------

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(**overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": "Person@Example.com",
        "email_verified": True,
        "name": "Person",
        "nonce": "n-123",
        "iat": now,
        "exp": now + 300,
        **overrides,
    }
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, _KEY, algorithm="RS256", headers={"kid": "k1"})


def _verify(token: str, nonce: str = "n-123", key: Any = None) -> Identity:
    public = (key or _KEY).public_key()
    return verify_id_token(token, client_id=CLIENT_ID, nonce=nonce, signing_key=lambda _: public)


def test_valid_token_gives_identity() -> None:
    identity = _verify(_token())
    assert identity == Identity(subject="1234567890", email="person@example.com", name="Person")


@pytest.mark.parametrize(
    ("token", "why"),
    [
        (lambda: _token(aud="someone-else"), "audience"),
        (lambda: _token(iss="https://evil.example"), "issuer"),
        (lambda: _token(exp=int(time.time()) - 3600), "expired"),
        (lambda: _token(email_verified=False), "unverified email"),
        (lambda: _token(email_verified=None), "missing email_verified"),
        (lambda: _token(nonce="other"), "nonce"),
        (lambda: _token(sub=None), "no subject"),
    ],
)
def test_bad_tokens_are_rejected(token: Any, why: str) -> None:
    with pytest.raises(OidcError):
        _verify(token())


def test_token_signed_by_another_key_is_rejected() -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(OidcError):
        _verify(_token(), key=other)


def test_unsigned_token_is_rejected() -> None:
    unsigned = jwt.encode({"sub": "x"}, key="", algorithm="none")
    with pytest.raises(OidcError):
        _verify(unsigned)


# Flows against a fake Google -------------------------------------------------------------


class FakeGoogle:
    """Stands in for Google: ``code`` names which identity signs in."""

    def __init__(self) -> None:
        self.people = {
            "owner-code": Identity("google-owner", "owner@example.com", "Owner"),
            "new-code": Identity("google-new", "newcomer@example.com", "Newcomer"),
        }
        self.last_auth: dict[str, list[str]] = {}

    def authorization_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str:
        assert redirect_uri == f"{ORIGIN}/api/auth/google/callback"
        assert len(code_challenge) >= 43  # S256 PKCE challenge
        return f"https://accounts.google.test/auth?state={state}&nonce={nonce}"

    async def identify(
        self, *, code: str, code_verifier: str, redirect_uri: str, nonce: str
    ) -> Identity:
        assert len(code_verifier) >= 43
        if code not in self.people:
            raise OidcError("Google refused the sign-in code (HTTP 400)")
        return self.people[code]


@pytest.fixture
async def google_app(settings: Settings) -> AsyncIterator[FastAPI]:
    configured = settings.model_copy(
        update={
            "google_client_id": CLIENT_ID,
            "google_client_secret": SecretStr("secret"),
            "public_origin": ORIGIN,
        }
    )
    app = create_app(configured)
    async with app.router.lifespan_context(app):
        app.state.oidc = FakeGoogle()
        yield app


@pytest.fixture
def browser_factory(google_app: FastAPI) -> Any:
    clients: list[httpx2.AsyncClient] = []

    def make() -> httpx2.AsyncClient:
        client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=google_app),
            base_url=ORIGIN,
            headers={"Origin": ORIGIN},
        )
        clients.append(client)
        return client

    return make


@pytest.fixture
async def google_owner(browser_factory: Any) -> httpx2.AsyncClient:
    client: httpx2.AsyncClient = browser_factory()
    response = await client.post("/api/setup", json={**OWNER, "setup_token": SETUP_TOKEN})
    assert response.status_code == 201
    return client


async def google_round_trip(
    client: httpx2.AsyncClient, purpose: str, code: str, **extra: str
) -> str:
    """Start a Google sign-in, 'approve' it at Google, return where we land."""
    started = await client.post("/api/auth/google/start", json={"purpose": purpose, **extra})
    assert started.status_code == 200, started.text
    state = parse_qs(urlsplit(started.json()["url"]).query)["state"][0]
    callback = await client.get("/api/auth/google/callback", params={"state": state, "code": code})
    assert callback.status_code == 303
    return callback.headers["location"]


async def test_not_configured_means_not_offered(client: httpx2.AsyncClient) -> None:
    assert (await client.get("/api/auth/providers")).json() == {"google": False}
    response = await client.post("/api/auth/google/start", json={"purpose": "login"})
    assert response.status_code == 404


async def test_unlinked_google_account_cannot_sign_in(
    browser_factory: Any, google_owner: Any
) -> None:
    assert (
        await google_round_trip(browser_factory(), "login", "owner-code")
        == "/login#error=not_linked"
    )


async def test_link_then_sign_in_with_google(browser_factory: Any, google_owner: Any) -> None:
    assert (await google_owner.get("/api/auth/providers")).json() == {"google": True}
    assert (
        await google_round_trip(google_owner, "link", "owner-code")
        == "/account/security#google=linked"
    )
    status = (await google_owner.get("/api/account/security")).json()
    assert status["google_email"] == "owner@example.com"

    browser = browser_factory()
    assert await google_round_trip(browser, "login", "owner-code") == "/#signed-in"
    me = await browser.get("/api/auth/me")
    assert me.json()["email"] == OWNER["email"]


async def test_google_sign_in_still_asks_for_the_second_factor(
    browser_factory: Any, google_owner: Any
) -> None:
    await google_round_trip(google_owner, "link", "owner-code")
    await enable_totp(google_owner)
    browser = browser_factory()
    assert await google_round_trip(browser, "login", "owner-code") == "/login#mfa"
    assert (await browser.get("/api/auth/me")).status_code == 401
    assert (await browser.get("/api/auth/mfa")).json()["methods"] == ["totp", "recovery"]


async def test_join_by_invite_with_google(browser_factory: Any, google_owner: Any) -> None:
    invite = (await google_owner.post("/api/invites", json={})).json()
    newcomer = browser_factory()
    landed = await google_round_trip(newcomer, "register", "new-code", invite_token=invite["token"])
    assert landed == "/#welcome"
    me = (await newcomer.get("/api/auth/me")).json()
    assert me["email"] == "newcomer@example.com"
    status = (await newcomer.get("/api/account/security")).json()
    assert status["has_password"] is False
    # Google is this account's only way in, so it cannot be unlinked.
    assert (await newcomer.delete("/api/account/security/google")).status_code == 409


async def test_invalid_invite_and_reused_google_account(
    browser_factory: Any, google_owner: Any
) -> None:
    landed = await google_round_trip(
        browser_factory(), "register", "new-code", invite_token="not-a-real-invite"
    )
    assert landed == "/register#error=invite_invalid"

    await google_round_trip(google_owner, "link", "owner-code")
    invite = (await google_owner.post("/api/invites", json={})).json()
    landed = await google_round_trip(
        browser_factory(), "register", "owner-code", invite_token=invite["token"]
    )
    assert landed == "/register#error=already_registered"


async def test_callback_from_another_browser_is_rejected(
    browser_factory: Any, google_owner: Any
) -> None:
    """Login CSRF: an attacker starts a flow and tricks the victim into finishing it."""
    await google_round_trip(google_owner, "link", "owner-code")
    attacker = browser_factory()
    started = await attacker.post("/api/auth/google/start", json={"purpose": "login"})
    state = parse_qs(urlsplit(started.json()["url"]).query)["state"][0]
    victim = browser_factory()
    landed = await victim.get(
        "/api/auth/google/callback", params={"state": state, "code": "owner-code"}
    )
    assert landed.headers["location"] == "/login#error=expired"
    assert (await victim.get("/api/auth/me")).status_code == 401


async def test_google_errors_are_reported_not_trusted(
    browser_factory: Any, google_owner: Any
) -> None:
    landed = await google_round_trip(browser_factory(), "login", "forged-code")
    assert landed == "/login#error=google"
    events = (await google_owner.get("/api/audit")).json()
    assert "oauth.failed" in {e["action"] for e in events}
