# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression tests for the October 2026 security audit.

Finding IDs refer to docs/security/AUDIT-2026-10.md.
"""

import base64
import os
import threading
import time
from uuid import UUID

import anyio
import httpx2
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from openchart_api import security
from openchart_api.config import Settings
from openchart_api.db import set_rls_context
from openchart_api.security import FailureLimiter

from .conftest import OWNER, SETUP_TOKEN, ClientFactory

pytestmark = pytest.mark.anyio

LOGIN = {"email": OWNER["email"], "password": OWNER["password"]}


# A2: password hashes are not readable by the app role --------------------------


async def test_app_role_cannot_read_password_hashes(
    owner: httpx2.AsyncClient, app_engine: AsyncEngine
) -> None:
    owner_id = UUID((await owner.get("/api/auth/me")).json()["id"])
    async with app_engine.begin() as conn:
        await set_rls_context(conn, owner_id, "owner")
        # Ordinary profile columns stay readable...
        assert await conn.scalar(text("SELECT count(email) FROM users")) == 1
        # ...but the hash column is not, even for the owner.
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text("SELECT password_hash FROM users"))


# A3: the failure limiter's memory stays bounded --------------------------------


def test_limiter_forgets_expired_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    limiter = FailureLimiter(window_seconds=60)
    limiter.record_failure("1.2.3.4", "a@example.com")
    assert len(limiter._failures) == 2
    clock[0] += 61
    assert limiter.retry_after("1.2.3.4", "a@example.com") == 0
    assert limiter._failures == {}


def test_limiter_caps_tracked_keys() -> None:
    limiter = FailureLimiter(max_keys=50)
    for i in range(500):
        limiter.record_failure(f"10.0.{i // 250}.{i % 250}", f"user{i}@example.com")
    assert len(limiter._failures) <= 50


def test_limiter_does_not_create_keys_when_reading() -> None:
    limiter = FailureLimiter()
    for i in range(100):
        assert limiter.retry_after("1.2.3.4", f"user{i}@example.com") == 0
    assert limiter._failures == {}


# A5: the setup token is protected against guessing ----------------------------


def test_configured_setup_token_must_be_long() -> None:
    with pytest.raises(ValidationError, match="setup_token"):
        Settings(
            database_url="postgresql+asyncpg://a:b@h/d",
            master_key=base64.b64encode(os.urandom(32)).decode(),
            setup_token="short",
        )


async def test_wrong_setup_tokens_are_rate_limited(client: httpx2.AsyncClient) -> None:
    body = {**OWNER, "setup_token": "x" * 20}
    for _ in range(5):
        assert (await client.post("/api/setup", json=body)).status_code == 403
    blocked = await client.post("/api/setup", json={**body, "setup_token": SETUP_TOKEN})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0


# A6: signing in again ends the browser's previous session ---------------------


async def test_signing_in_again_revokes_the_previous_session(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    browser = new_client()
    await browser.post("/api/auth/login", json=LOGIN)
    first = browser.cookies["oc_session"]
    await browser.post("/api/auth/login", json=LOGIN)
    assert browser.cookies["oc_session"] != first

    replay = new_client()
    replay.cookies.set("oc_session", first)
    assert (await replay.get("/api/auth/me")).status_code == 401
    assert (await browser.get("/api/auth/me")).status_code == 200


# A7: over HTTPS the cookie uses the __Host- prefix -----------------------------


async def test_https_cookie_is_host_prefixed_and_secure(
    app: FastAPI, owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    origin = "https://charts.example.com"
    app.state.settings = app.state.settings.model_copy(update={"public_origin": origin})
    browser = new_client()
    response = await browser.post(
        "/api/auth/login",
        json=LOGIN,
        headers={"Origin": origin, "Host": "charts.example.com"},
    )
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-oc_session=")
    assert "Secure" in cookie
    assert "Domain" not in cookie
    assert "Path=/" in cookie


# A9: with a public origin set, other Host headers are refused ------------------


async def test_unknown_host_is_rejected_when_public_origin_is_set(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    app.state.settings = app.state.settings.model_copy(
        update={"public_origin": "https://charts.example.com"}
    )
    rebinding = await client.get("/api/health", headers={"Host": "attacker.example"})
    assert rebinding.status_code == 400
    for host in ("charts.example.com", "127.0.0.1:8000", "localhost"):
        assert (await client.get("/api/health", headers={"Host": host})).status_code == 200


# B1: password hashing cannot be used to exhaust memory ------------------------


async def test_bad_invites_are_rate_limited_before_hashing(
    owner: httpx2.AsyncClient, new_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    attacker = new_client()
    body = {
        "invite_token": "guess",
        "email": "x@example.com",
        "display_name": "X",
        "password": "long enough password",
    }
    for _ in range(5):
        assert (await attacker.post("/api/auth/register", json=body)).status_code == 400

    hashed: list[str] = []

    async def counting_hash(password: str) -> str:
        hashed.append(password)
        return "never-used"

    monkeypatch.setattr("openchart_api.routes.auth.hash_password", counting_hash)
    assert (await attacker.post("/api/auth/register", json=body)).status_code == 429
    assert hashed == []


async def test_password_hashing_concurrency_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    running = peak = 0
    lock = threading.Lock()

    def slow_hash(password: str) -> str:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return "hash"

    class SlowHasher:
        hash = staticmethod(slow_hash)

    monkeypatch.setattr(security, "_hasher", SlowHasher())
    async with anyio.create_task_group() as tg:
        for _ in range(10):
            tg.start_soon(security.hash_password, "pw")
    assert peak == security.HASH_CONCURRENCY


# B2: API responses are never cached ---------------------------------------------


async def test_api_responses_are_not_cacheable(owner: httpx2.AsyncClient) -> None:
    for path in ("/api/auth/me", "/api/auth/sessions", "/api/audit", "/api/health"):
        assert (await owner.get(path)).headers["cache-control"] == "no-store", path
