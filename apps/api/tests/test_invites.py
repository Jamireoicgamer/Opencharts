# SPDX-License-Identifier: AGPL-3.0-or-later
"""After setup, new accounts can only be created from an owner/admin invite."""

from typing import Any

import httpx2
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from .conftest import ClientFactory, Invite

pytestmark = pytest.mark.anyio


def _account(token: str, email: str = "new@example.com") -> dict[str, Any]:
    return {
        "invite_token": token,
        "email": email,
        "display_name": "New",
        "password": "a sufficiently long one",
    }


async def _create(client: httpx2.AsyncClient, **body: Any) -> dict[str, Any]:
    response = await client.post("/api/invites", json=body)
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


async def test_invite_creates_member_account(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    invite = await _create(owner)
    assert len(invite["token"]) >= 40
    joiner = new_client()
    response = await joiner.post("/api/auth/register", json=_account(invite["token"]))
    assert response.status_code == 201
    assert response.json()["role"] == "member"
    assert (await joiner.get("/api/auth/me")).json()["email"] == "new@example.com"

    listed = (await owner.get("/api/invites")).json()
    assert listed[0]["used_at"] is not None
    assert "token" not in listed[0]


async def test_invite_cannot_be_reused(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    token = (await _create(owner))["token"]
    assert (await new_client().post("/api/auth/register", json=_account(token))).status_code == 201
    again = await new_client().post("/api/auth/register", json=_account(token, "other@example.com"))
    assert again.status_code == 400


async def test_expired_and_unknown_invites_are_rejected(
    owner: httpx2.AsyncClient, new_client: ClientFactory, admin_engine: AsyncEngine
) -> None:
    token = (await _create(owner))["token"]
    async with admin_engine.begin() as conn:
        await conn.execute(text("UPDATE invites SET expires_at = now() - interval '1 second'"))
    assert (await new_client().post("/api/auth/register", json=_account(token))).status_code == 400
    unknown = await new_client().post("/api/auth/register", json=_account("made-up"))
    assert unknown.status_code == 400


async def test_email_bound_invite(owner: httpx2.AsyncClient, new_client: ClientFactory) -> None:
    token = (await _create(owner, email="friend@example.com"))["token"]
    wrong = await new_client().post(
        "/api/auth/register", json=_account(token, "someone@example.com")
    )
    assert wrong.status_code == 400
    right = await new_client().post(
        "/api/auth/register", json=_account(token, "Friend@Example.com")
    )
    assert right.status_code == 201


async def test_duplicate_email_is_rejected(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    token = (await _create(owner))["token"]
    taken = await new_client().post("/api/auth/register", json=_account(token, "OWNER@example.com"))
    assert taken.status_code == 409
    # The invite is still usable after the failed attempt.
    assert (await new_client().post("/api/auth/register", json=_account(token))).status_code == 201


async def test_members_cannot_invite(invite_user: Invite) -> None:
    member = await invite_user("member@example.com")
    assert (await member.post("/api/invites", json={})).status_code == 403
    assert (await member.get("/api/invites")).status_code == 403


async def test_only_owner_can_invite_admins(invite_user: Invite) -> None:
    admin = await invite_user("admin@example.com", role="admin")
    assert (await admin.post("/api/invites", json={"role": "member"})).status_code == 201
    assert (await admin.post("/api/invites", json={"role": "admin"})).status_code == 403


async def test_revoke_invite(owner: httpx2.AsyncClient, new_client: ClientFactory) -> None:
    invite = await _create(owner)
    assert (await owner.delete(f"/api/invites/{invite['id']}")).status_code == 204
    response = await new_client().post("/api/auth/register", json=_account(invite["token"]))
    assert response.status_code == 400
