# SPDX-License-Identifier: AGPL-3.0-or-later
"""First-run setup creates exactly one owner, and only with the setup token."""

import logging

import httpx2
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from openchart_api.config import Settings
from openchart_api.main import create_app

from .conftest import OWNER, SETUP_TOKEN, ClientFactory

pytestmark = pytest.mark.anyio


async def test_needs_setup_until_owner_exists(client: httpx2.AsyncClient) -> None:
    assert (await client.get("/api/setup/status")).json() == {"needs_setup": True}
    response = await client.post("/api/setup", json={**OWNER, "setup_token": SETUP_TOKEN})
    assert response.status_code == 201
    assert response.json()["role"] == "owner"
    assert (await client.get("/api/setup/status")).json() == {"needs_setup": False}
    me = await client.get("/api/auth/me")
    assert me.json()["email"] == OWNER["email"]


async def test_wrong_setup_token_is_rejected_and_audited(
    client: httpx2.AsyncClient, admin_engine: AsyncEngine
) -> None:
    response = await client.post("/api/setup", json={**OWNER, "setup_token": "guess"})
    assert response.status_code == 403
    assert (await client.get("/api/setup/status")).json() == {"needs_setup": True}
    async with admin_engine.connect() as conn:
        actions = (await conn.scalars(text("SELECT action FROM audit_log"))).all()
    assert actions == ["setup.token_rejected"]


async def test_setup_only_works_once(owner: httpx2.AsyncClient, new_client: ClientFactory) -> None:
    second = await new_client().post(
        "/api/setup",
        json={**OWNER, "email": "intruder@example.com", "setup_token": SETUP_TOKEN},
    )
    assert second.status_code == 409


async def test_weak_password_is_rejected(client: httpx2.AsyncClient) -> None:
    response = await client.post(
        "/api/setup", json={**OWNER, "password": "short", "setup_token": SETUP_TOKEN}
    )
    assert response.status_code == 422


async def test_generates_and_logs_token_when_not_configured(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app(settings.model_copy(update={"setup_token": None}))
    with caplog.at_level(logging.WARNING, logger="openchart_api"):
        async with app.router.lifespan_context(app):
            token = app.state.setup_token
    assert token
    assert token in caplog.text
