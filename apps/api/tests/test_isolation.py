# SPDX-License-Identifier: AGPL-3.0-or-later
"""Users can never see or change each other's data — through the API or directly in SQL."""

from uuid import UUID

import httpx2
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from openchart_api.db import set_rls_context

from .conftest import Invite

pytestmark = pytest.mark.anyio


async def _ids(alice: httpx2.AsyncClient, bob: httpx2.AsyncClient) -> tuple[UUID, UUID]:
    a = (await alice.get("/api/auth/me")).json()["id"]
    b = (await bob.get("/api/auth/me")).json()["id"]
    return UUID(a), UUID(b)


async def test_api_does_not_leak_between_users(invite_user: Invite) -> None:
    alice = await invite_user("alice@example.com")
    bob = await invite_user("bob@example.com")
    await alice.put("/api/secrets/finnhub", json={"value": "alice-secret-value-123"})

    assert (await bob.get("/api/secrets")).json() == []
    assert (await bob.delete("/api/secrets/finnhub")).status_code == 404
    assert len((await alice.get("/api/secrets")).json()) == 1

    alice_session = (await alice.get("/api/auth/sessions")).json()[0]["id"]
    assert (await bob.delete(f"/api/auth/sessions/{alice_session}")).status_code == 404
    assert (await alice.get("/api/auth/me")).status_code == 200

    bob_events = (await bob.get("/api/audit")).json()
    assert {e["user_id"] for e in bob_events} == {(await bob.get("/api/auth/me")).json()["id"]}


async def test_owner_sees_all_audit_events_members_do_not(
    owner: httpx2.AsyncClient, invite_user: Invite
) -> None:
    member = await invite_user("member@example.com")
    owner_view = {e["action"] for e in (await owner.get("/api/audit")).json()}
    member_view = {e["action"] for e in (await member.get("/api/audit")).json()}
    assert {"setup.owner_created", "invite.created", "auth.registered"} <= owner_view
    assert member_view == {"auth.registered"}


async def test_row_level_security_in_raw_sql(invite_user: Invite, app_engine: AsyncEngine) -> None:
    alice = await invite_user("alice@example.com")
    bob = await invite_user("bob@example.com")
    await alice.put("/api/secrets/one", json={"value": "alice-secret-value-123"})
    await bob.put("/api/secrets/two", json={"value": "bob-secret-value-4567"})
    alice_id, bob_id = await _ids(alice, bob)

    async with app_engine.begin() as conn:
        # No user context: the app role sees nothing at all.
        for table in ("users", "sessions", "invites", "vault_secrets", "audit_log"):
            assert await conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0, table  # noqa: S608

    async with app_engine.begin() as conn:
        await set_rls_context(conn, bob_id, "member")
        names = (await conn.scalars(text("SELECT name FROM vault_secrets"))).all()
        assert names == ["two"]
        assert await conn.scalar(text("SELECT count(*) FROM users")) == 1
        # Deleting another user's rows silently matches nothing.
        deleted = await conn.execute(
            text("DELETE FROM vault_secrets WHERE user_id = :a"), {"a": alice_id}
        )
        assert deleted.rowcount == 0

    async with app_engine.begin() as conn:
        await set_rls_context(conn, bob_id, "member")
        with pytest.raises(DBAPIError, match="row-level security"):
            await conn.execute(
                text(
                    "INSERT INTO vault_secrets (user_id, name, ciphertext, nonce, wrapped_dek, "
                    "dek_nonce, key_version) VALUES (:a, 'planted', '', '', '', '', 1)"
                ),
                {"a": alice_id},
            )


async def test_users_cannot_change_their_own_role(
    invite_user: Invite, app_engine: AsyncEngine
) -> None:
    bob = await invite_user("bob@example.com")
    bob_id = UUID((await bob.get("/api/auth/me")).json()["id"])
    async with app_engine.begin() as conn:
        await set_rls_context(conn, bob_id, "member")
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(
                text("UPDATE users SET role = 'owner' WHERE id = :id"), {"id": bob_id}
            )
