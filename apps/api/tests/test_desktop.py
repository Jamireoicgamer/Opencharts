# SPDX-License-Identifier: AGPL-3.0-or-later
"""Desktop sign-in: the app's launch token signs in as the owner, without a
password. Servers have no token, so the endpoint does not exist there."""

import logging
from collections.abc import AsyncIterator

import httpx2
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from openchart_api.config import Settings
from openchart_api.main import create_app

from .conftest import ORIGIN, OWNER, SETUP_TOKEN, ClientFactory

pytestmark = pytest.mark.anyio

DESKTOP_TOKEN = "d" * 43


@pytest.fixture
async def desktop_app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(
        settings.model_copy(update={"desktop_token": SecretStr(DESKTOP_TOKEN), "setup_token": None})
    )
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def desktop(desktop_app: FastAPI) -> AsyncIterator[ClientFactory]:
    clients: list[httpx2.AsyncClient] = []

    def make() -> httpx2.AsyncClient:
        client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=desktop_app),
            base_url=ORIGIN,
            headers={"Origin": ORIGIN},
        )
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


async def actions(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        return list((await conn.scalars(text("SELECT action FROM audit_log ORDER BY id"))).all())


async def test_servers_have_no_desktop_sign_in(client: httpx2.AsyncClient) -> None:
    response = await client.post("/api/auth/desktop", json={"token": DESKTOP_TOKEN})
    assert response.status_code == 404
    assert (await client.get("/api/setup/status")).json()["desktop"] is False


async def test_first_launch_creates_a_passwordless_owner(
    desktop: ClientFactory, admin_engine: AsyncEngine
) -> None:
    window = desktop()
    status = (await window.get("/api/setup/status")).json()
    assert status == {"needs_setup": True, "desktop": True}

    response = await window.post("/api/auth/desktop", json={"token": DESKTOP_TOKEN})
    assert response.status_code == 200, response.text
    me = response.json()
    assert me["role"] == "owner"
    assert me["display_name"] == "Me"
    assert (await window.get("/api/auth/me")).json()["id"] == me["id"]
    assert (await window.get("/api/setup/status")).json()["needs_setup"] is False
    async with admin_engine.connect() as conn:
        password = await conn.scalar(text("SELECT password_hash FROM users"))
    assert password is None
    assert await actions(admin_engine) == ["auth.desktop_owner_created"]

    # Later launches sign in as the same owner rather than creating another.
    again = await desktop().post("/api/auth/desktop", json={"token": DESKTOP_TOKEN})
    assert again.json()["id"] == me["id"]
    async with admin_engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM users")) == 1


async def test_setup_by_password_is_off_on_desktop(
    desktop: ClientFactory, desktop_app: FastAPI
) -> None:
    assert desktop_app.state.setup_token is None
    response = await desktop().post("/api/setup", json={**OWNER, "setup_token": SETUP_TOKEN})
    assert response.status_code == 409


async def test_existing_owner_is_signed_in(
    owner: httpx2.AsyncClient, desktop: ClientFactory
) -> None:
    """An account made with a password (older desktop installs) keeps working."""
    created = (await owner.get("/api/auth/me")).json()
    window = desktop()
    response = await window.post("/api/auth/desktop", json={"token": DESKTOP_TOKEN})
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["email"] == OWNER["email"]


async def test_wrong_token_is_refused_audited_and_limited(
    desktop: ClientFactory, admin_engine: AsyncEngine
) -> None:
    window = desktop()
    response = await window.post("/api/auth/desktop", json={"token": "x" * 43})
    assert response.status_code == 403
    assert (await window.get("/api/auth/me")).status_code == 401
    assert await actions(admin_engine) == ["auth.desktop_rejected"]
    async with admin_engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM users")) == 0

    for _ in range(20):
        last = await window.post("/api/auth/desktop", json={"token": "y" * 43})
        if last.status_code == 429:
            break
    assert last.status_code == 429
    # Once limited, even the right token waits.
    right = await window.post("/api/auth/desktop", json={"token": DESKTOP_TOKEN})
    assert right.status_code == 429


async def test_disabled_owner_is_refused(
    owner: httpx2.AsyncClient, desktop: ClientFactory, admin_engine: AsyncEngine
) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET disabled_at = now()"))
    response = await desktop().post("/api/auth/desktop", json={"token": DESKTOP_TOKEN})
    assert response.status_code == 403
    async with admin_engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM users")) == 1


async def test_confirms_it_is_you_without_a_password(
    desktop: ClientFactory, admin_engine: AsyncEngine
) -> None:
    window = desktop()
    await window.post("/api/auth/desktop", json={"token": DESKTOP_TOKEN})
    async with admin_engine.begin() as conn:
        await conn.execute(text("UPDATE sessions SET reauth_at = now() - interval '11 minutes'"))
    body = {"new_password": "a brand new password"}
    refused = await window.post("/api/account/security/password", json=body)
    assert refused.json()["detail"] == "reauth_required"

    confirmed = await window.post("/api/auth/desktop", json={"token": DESKTOP_TOKEN})
    assert confirmed.status_code == 200
    # The same session is refreshed; no second one is created.
    async with admin_engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM sessions")) == 1
    assert (await window.post("/api/account/security/password", json=body)).status_code == 204
    assert (await actions(admin_engine))[-2:] == ["auth.desktop_confirmed", "auth.password_changed"]


async def test_a_member_cannot_use_it_without_the_token(
    owner: httpx2.AsyncClient, desktop: ClientFactory
) -> None:
    created = await owner.post("/api/invites", json={"role": "member"})
    member = desktop()
    await member.post(
        "/api/auth/register",
        json={
            "invite_token": created.json()["token"],
            "email": "member@example.com",
            "display_name": "member",
            "password": "another long password",
        },
    )
    response = await member.post("/api/auth/desktop", json={"token": "z" * 43})
    assert response.status_code == 403
    assert (await member.get("/api/auth/me")).json()["role"] == "member"


async def test_short_desktop_tokens_are_rejected(settings: Settings) -> None:
    with pytest.raises(ValueError, match="desktop_token"):
        Settings.model_validate({**settings.model_dump(), "desktop_token": "short"})


async def test_no_setup_token_is_logged_on_desktop(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app(
        settings.model_copy(update={"desktop_token": SecretStr(DESKTOP_TOKEN), "setup_token": None})
    )
    with caplog.at_level(logging.WARNING, logger="openchart_api"):
        async with app.router.lifespan_context(app):
            assert app.state.setup_token is None
    assert "setup token" not in caplog.text
