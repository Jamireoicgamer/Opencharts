# SPDX-License-Identifier: AGPL-3.0-or-later
"""Authenticator-app two-factor, recovery codes, re-authentication and the
owner's "require two-factor" switch."""

import time
from typing import Any
from uuid import UUID

import httpx2
import pyotp
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from openchart_api import mfa
from openchart_api.db import set_rls_context

from .conftest import OWNER, ClientFactory, Invite

pytestmark = pytest.mark.anyio

LOGIN = {"email": OWNER["email"], "password": OWNER["password"]}


# A fixed moment, 5 seconds into a 30-second step, so codes never roll over mid-test.
NOW = (int(time.time()) // 30) * 30 + 5


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mfa, "clock", lambda: NOW)


def code_at(secret: str, offset_steps: int = 0) -> str:
    return pyotp.TOTP(secret).at(NOW + 30 * offset_steps)


async def enable_totp(client: httpx2.AsyncClient) -> tuple[str, list[str]]:
    """Set up an authenticator app; returns the secret and recovery codes."""
    setup = await client.post("/api/account/security/totp/setup")
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    confirmed = await client.post(
        "/api/account/security/totp/confirm", json={"code": code_at(secret)}
    )
    assert confirmed.status_code == 200, confirmed.text
    return secret, confirmed.json()["recovery_codes"]


async def password_step(client: httpx2.AsyncClient) -> dict[str, Any]:
    response = await client.post("/api/auth/login", json=LOGIN)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_totp_enrolment_and_two_step_sign_in(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    setup = await owner.post("/api/account/security/totp/setup")
    assert setup.json()["qr_svg"].startswith("data:image/svg+xml")
    assert setup.json()["uri"].startswith("otpauth://totp/OpenChart%20AI:")
    wrong = await owner.post("/api/account/security/totp/confirm", json={"code": "000000"})
    assert wrong.status_code == 400
    secret = setup.json()["secret"]
    confirmed = await owner.post(
        "/api/account/security/totp/confirm", json={"code": code_at(secret)}
    )
    codes = confirmed.json()["recovery_codes"]
    assert len(codes) == 10
    assert len(set(codes)) == 10
    status = (await owner.get("/api/account/security")).json()
    assert status["totp"] is True
    assert status["recovery_codes_left"] == 10

    browser = new_client()
    step = await password_step(browser)
    assert step == {"mfa_required": True, "methods": ["totp", "recovery"]}
    # The password alone gives no session.
    assert "oc_session" not in browser.cookies
    assert (await browser.get("/api/auth/me")).status_code == 401

    done = await browser.post("/api/auth/mfa/totp", json={"code": code_at(secret, 1)})
    assert done.status_code == 200, done.text
    assert done.json()["email"] == OWNER["email"]
    assert (await browser.get("/api/auth/me")).status_code == 200


async def test_a_totp_code_cannot_be_replayed(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    secret, _ = await enable_totp(owner)
    used = code_at(secret)  # consumed by enrolment
    browser = new_client()
    await password_step(browser)
    replay = await browser.post("/api/auth/mfa/totp", json={"code": used})
    assert replay.status_code == 401
    fresh = await browser.post("/api/auth/mfa/totp", json={"code": code_at(secret, 1)})
    assert fresh.status_code == 200

    other = new_client()
    await password_step(other)
    again = await other.post("/api/auth/mfa/totp", json={"code": code_at(secret, 1)})
    assert again.status_code == 401


async def test_recovery_codes_work_once(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    _, codes = await enable_totp(owner)
    first = new_client()
    await password_step(first)
    assert (
        await first.post("/api/auth/mfa/recovery", json={"code": codes[0].upper()})
    ).status_code == 200

    second = new_client()
    await password_step(second)
    assert (await second.post("/api/auth/mfa/recovery", json={"code": codes[0]})).status_code == 401
    assert (await second.post("/api/auth/mfa/recovery", json={"code": codes[1]})).status_code == 200
    left = (await owner.get("/api/account/security")).json()["recovery_codes_left"]
    assert left == 8


async def test_regenerating_recovery_codes_invalidates_old_ones(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    _, old = await enable_totp(owner)
    new = (await owner.post("/api/account/security/recovery-codes")).json()["recovery_codes"]
    assert not set(old) & set(new)
    browser = new_client()
    await password_step(browser)
    assert (await browser.post("/api/auth/mfa/recovery", json={"code": old[0]})).status_code == 401
    assert (await browser.post("/api/auth/mfa/recovery", json={"code": new[0]})).status_code == 200


async def test_wrong_codes_end_the_sign_in_attempt(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    secret, _ = await enable_totp(owner)
    browser = new_client()
    await password_step(browser)
    for _ in range(4):
        response = await browser.post("/api/auth/mfa/totp", json={"code": "123456"})
        assert response.json()["detail"] == "That code is not right. Try again."
    last = await browser.post("/api/auth/mfa/totp", json={"code": "123456"})
    assert last.json()["detail"] == "Too many wrong codes. Sign in again."
    # Even the right code no longer works for this attempt.
    late = await browser.post("/api/auth/mfa/totp", json={"code": code_at(secret, 1)})
    assert late.status_code == 401


async def test_sensitive_changes_need_a_recent_sign_in(
    owner: httpx2.AsyncClient, admin_engine: AsyncEngine
) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(text("UPDATE sessions SET reauth_at = now() - interval '11 minutes'"))
    for method, path in (
        ("POST", "/api/account/security/totp/setup"),
        ("POST", "/api/account/security/password"),
        ("POST", "/api/account/security/passkeys/options"),
        ("PUT", "/api/admin/settings"),
    ):
        body: dict[str, object] = (
            {"new_password": "a brand new password"} if path.endswith("password") else {}
        )
        if path.endswith("settings"):
            body = {"require_mfa": False}
        response = await owner.request(method, path, json=body)
        assert response.status_code == 403, path
        assert response.json()["detail"] == "reauth_required", path

    assert (await owner.post("/api/auth/reauth", json={"password": "wrong"})).status_code == 401
    assert (
        await owner.post("/api/auth/reauth", json={"password": OWNER["password"]})
    ).status_code == 204
    assert (await owner.post("/api/account/security/totp/setup")).status_code == 200


async def test_owner_can_require_two_factor_for_everyone(
    owner: httpx2.AsyncClient, invite_user: Invite
) -> None:
    member = await invite_user("member@example.com")
    refused = await owner.put("/api/admin/settings", json={"require_mfa": True})
    assert refused.status_code == 409  # the owner needs two-factor first
    await enable_totp(owner)
    assert (await owner.put("/api/admin/settings", json={"require_mfa": True})).status_code == 200
    assert (await member.put("/api/admin/settings", json={"require_mfa": False})).status_code == 403

    me = (await member.get("/api/auth/me")).json()
    assert me["mfa_setup_required"] is True
    blocked = await member.get("/api/secrets")
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "mfa_setup_required"
    # The security settings stay reachable so the member can comply.
    assert (await member.get("/api/account/security")).status_code == 200
    await enable_totp(member)
    assert (await member.get("/api/secrets")).status_code == 200
    assert (await member.get("/api/auth/me")).json()["mfa_setup_required"] is False


async def test_last_second_factor_cannot_be_removed_while_required(
    owner: httpx2.AsyncClient,
) -> None:
    await enable_totp(owner)
    await owner.put("/api/admin/settings", json={"require_mfa": True})
    assert (await owner.delete("/api/account/security/totp")).status_code == 409
    await owner.put("/api/admin/settings", json={"require_mfa": False})
    assert (await owner.delete("/api/account/security/totp")).status_code == 204
    status = (await owner.get("/api/account/security")).json()
    assert status["totp"] is False
    assert status["recovery_codes_left"] == 0


async def test_changing_password_signs_out_other_devices(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    other = new_client()
    await other.post("/api/auth/login", json=LOGIN)
    changed = await owner.post(
        "/api/account/security/password", json={"new_password": "a brand new password"}
    )
    assert changed.status_code == 204
    assert (await other.get("/api/auth/me")).status_code == 401
    assert (await owner.get("/api/auth/me")).status_code == 200
    fresh = new_client()
    assert (await fresh.post("/api/auth/login", json=LOGIN)).status_code == 401
    ok = await fresh.post("/api/auth/login", json={**LOGIN, "password": "a brand new password"})
    assert ok.status_code == 200


async def test_new_tables_are_isolated_and_flows_unreachable(
    owner: httpx2.AsyncClient, invite_user: Invite, app_engine: AsyncEngine
) -> None:
    await enable_totp(owner)
    member = await invite_user("member@example.com")
    member_id = UUID((await member.get("/api/auth/me")).json()["id"])
    async with app_engine.begin() as conn:
        await set_rls_context(conn, member_id, "member")
        for table in ("mfa_totp", "mfa_recovery_codes", "webauthn_credentials", "oauth_identities"):
            assert await conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0, table  # noqa: S608
    async with app_engine.begin() as conn:
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text("SELECT * FROM auth_flows"))


async def test_sign_in_responses_say_when_two_factor_setup_is_due(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    await enable_totp(owner)
    await owner.put("/api/admin/settings", json={"require_mfa": True})
    invite = (await owner.post("/api/invites", json={})).json()
    joined = await new_client().post(
        "/api/auth/register",
        json={
            "invite_token": invite["token"],
            "email": "late@example.com",
            "display_name": "Late",
            "password": "another long password",
        },
    )
    assert joined.status_code == 201
    assert joined.json()["mfa_setup_required"] is True
    again = await new_client().post(
        "/api/auth/login", json={"email": "late@example.com", "password": "another long password"}
    )
    assert again.json()["mfa_setup_required"] is True
