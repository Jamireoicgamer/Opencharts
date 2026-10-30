# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signing in and out, sessions, rate limiting and CSRF protection."""

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from openchart_api.auth import SESSION_COOKIE

from .conftest import ORIGIN, OWNER, ClientFactory

pytestmark = pytest.mark.anyio

LOGIN = {"email": OWNER["email"], "password": OWNER["password"]}


async def test_login_sets_http_only_cookie(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    browser = new_client()
    response = await browser.post("/api/auth/login", json=LOGIN)
    assert response.status_code == 200
    assert response.json()["email"] == OWNER["email"]
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie  # plain-HTTP test server; Secure when public_origin is https
    assert (await browser.get("/api/auth/me")).status_code == 200


async def test_email_is_case_insensitive(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    response = await new_client().post(
        "/api/auth/login", json={**LOGIN, "email": OWNER["email"].upper()}
    )
    assert response.status_code == 200


async def test_wrong_password_and_unknown_email_look_the_same(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    wrong = await new_client().post("/api/auth/login", json={**LOGIN, "password": "nope"})
    unknown = await new_client().post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "nope"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_failed_logins_are_rate_limited(
    owner: httpx2.AsyncClient, new_client: ClientFactory, admin_engine: AsyncEngine
) -> None:
    attacker = new_client()
    for _ in range(5):
        assert (
            await attacker.post("/api/auth/login", json={**LOGIN, "password": "x"})
        ).status_code == 401
    blocked = await attacker.post("/api/auth/login", json=LOGIN)
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0
    async with admin_engine.connect() as conn:
        actions = (await conn.scalars(text("SELECT action FROM audit_log ORDER BY id"))).all()
    assert actions.count("auth.login_failed") == 5
    assert actions[-1] == "auth.login_rate_limited"


async def test_requests_without_session_are_rejected(client: httpx2.AsyncClient) -> None:
    for path in ("/api/auth/me", "/api/auth/sessions", "/api/secrets", "/api/audit"):
        assert (await client.get(path)).status_code == 401, path


async def test_logout_revokes_the_session_server_side(owner: httpx2.AsyncClient) -> None:
    token = owner.cookies[SESSION_COOKIE]
    assert (await owner.post("/api/auth/logout")).status_code == 204
    # Replaying the old cookie must not work.
    owner.cookies.set(SESSION_COOKIE, token)
    assert (await owner.get("/api/auth/me")).status_code == 401


async def test_list_and_revoke_sessions(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    laptop, phone = new_client(), new_client()
    for device in (laptop, phone):
        assert (await device.post("/api/auth/login", json=LOGIN)).status_code == 200

    listed = (await owner.get("/api/auth/sessions")).json()
    assert len(listed) == 3
    assert sum(s["current"] for s in listed) == 1

    laptop_id = next(
        s["id"] for s in (await laptop.get("/api/auth/sessions")).json() if s["current"]
    )
    assert (await owner.delete(f"/api/auth/sessions/{laptop_id}")).status_code == 204
    assert (await laptop.get("/api/auth/me")).status_code == 401

    revoked = await owner.post("/api/auth/sessions/revoke-others")
    assert revoked.json() == {"revoked": 1}
    assert (await phone.get("/api/auth/me")).status_code == 401
    assert (await owner.get("/api/auth/me")).status_code == 200


async def test_expired_session_is_rejected(
    owner: httpx2.AsyncClient, admin_engine: AsyncEngine
) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(text("UPDATE sessions SET expires_at = now() - interval '1 second'"))
    assert (await owner.get("/api/auth/me")).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"},
        {"Origin": ORIGIN, "Sec-Fetch-Site": "same-site"},
        {"Origin": ""},
    ],
)
async def test_cross_site_writes_are_blocked(
    owner: httpx2.AsyncClient, headers: dict[str, str]
) -> None:
    owner.headers.pop("Origin")
    response = await owner.post("/api/auth/sessions/revoke-others", headers=headers)
    assert response.status_code == 403
    # Reads stay possible; the session still works.
    assert (await owner.get("/api/auth/me")).status_code == 200


async def test_public_origin_is_enforced(app: FastAPI, owner: httpx2.AsyncClient) -> None:
    app.state.settings = app.state.settings.model_copy(
        update={"public_origin": "https://charts.example.com"}
    )
    blocked = await owner.post("/api/auth/sessions/revoke-others")
    allowed = await owner.post(
        "/api/auth/sessions/revoke-others", headers={"Origin": "https://charts.example.com"}
    )
    assert blocked.status_code == 403
    assert allowed.status_code == 200
