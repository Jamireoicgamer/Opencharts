# SPDX-License-Identifier: AGPL-3.0-or-later
"""Passkeys: registration, passwordless sign-in, and use as a second factor."""

from typing import Any

import httpx2
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from .conftest import OWNER, ClientFactory, Invite
from .soft_authenticator import SoftAuthenticator

pytestmark = pytest.mark.anyio

LOGIN = {"email": OWNER["email"], "password": OWNER["password"]}


async def add_passkey(
    client: httpx2.AsyncClient, authenticator: SoftAuthenticator, name: str = "Laptop"
) -> dict[str, object]:
    options = (await client.post("/api/account/security/passkeys/options")).json()
    response = await client.post(
        "/api/account/security/passkeys",
        json={"name": name, "credential": authenticator.create(options)},
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


async def passkey_sign_in(
    client: httpx2.AsyncClient, authenticator: SoftAuthenticator, **misbehave: Any
) -> httpx2.Response:
    options = (await client.post("/api/auth/passkey/options")).json()
    return await client.post(
        "/api/auth/passkey", json={"credential": authenticator.get(options, **misbehave)}
    )


async def test_register_then_sign_in_without_a_password(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    key = SoftAuthenticator()
    added = await add_passkey(owner, key)
    codes = added["recovery_codes"]
    assert isinstance(codes, list) and len(codes) == 10  # first second factor
    status = (await owner.get("/api/account/security")).json()
    assert [p["name"] for p in status["passkeys"]] == ["Laptop"]

    browser = new_client()
    signed_in = await passkey_sign_in(browser, key)
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["email"] == OWNER["email"]
    assert (await browser.get("/api/auth/me")).status_code == 200


async def test_passkey_as_second_factor_after_password(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    key = SoftAuthenticator()
    await add_passkey(owner, key)
    browser = new_client()
    step = (await browser.post("/api/auth/login", json=LOGIN)).json()
    assert step == {"mfa_required": True, "methods": ["passkey", "recovery"]}
    options = (await browser.post("/api/auth/mfa/passkey/options")).json()
    assert [c["id"] for c in options["allowCredentials"]]
    # As a second factor, a touch is enough (no PIN or biometric required).
    done = await browser.post(
        "/api/auth/mfa/passkey", json={"credential": key.get(options, uv=False)}
    )
    assert done.status_code == 200, done.text


@pytest.mark.parametrize(
    "misbehave",
    [
        {"origin": "https://evil.example"},
        {"rp_id": "evil.example"},
        {"uv": False},  # passwordless needs user verification
    ],
)
async def test_bad_assertions_are_rejected(
    owner: httpx2.AsyncClient, new_client: ClientFactory, misbehave: dict[str, Any]
) -> None:
    key = SoftAuthenticator()
    await add_passkey(owner, key)
    response = await passkey_sign_in(new_client(), key, **misbehave)
    assert response.status_code == 401


async def test_cloned_authenticator_is_detected(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    key = SoftAuthenticator()
    await add_passkey(owner, key)
    assert (await passkey_sign_in(new_client(), key)).status_code == 200
    # A copy of the key that has fallen behind the real one's counter.
    key.sign_count = 0
    assert (await passkey_sign_in(new_client(), key)).status_code == 401


async def test_an_assertion_cannot_be_replayed(
    owner: httpx2.AsyncClient, new_client: ClientFactory
) -> None:
    key = SoftAuthenticator()
    await add_passkey(owner, key)
    browser = new_client()
    options = (await browser.post("/api/auth/passkey/options")).json()
    assertion = key.get(options)
    assert (
        await browser.post("/api/auth/passkey", json={"credential": assertion})
    ).status_code == 200
    attacker = new_client()
    await attacker.post("/api/auth/passkey/options")
    replay = await attacker.post("/api/auth/passkey", json={"credential": assertion})
    assert replay.status_code == 401


async def test_someone_elses_passkey_is_no_second_factor(
    owner: httpx2.AsyncClient, invite_user: Invite, new_client: ClientFactory
) -> None:
    await add_passkey(owner, SoftAuthenticator())
    member = await invite_user("member@example.com")
    member_key = SoftAuthenticator()
    await add_passkey(member, member_key)

    browser = new_client()
    await browser.post("/api/auth/login", json=LOGIN)
    options = (await browser.post("/api/auth/mfa/passkey/options")).json()
    wrong = await browser.post(
        "/api/auth/mfa/passkey", json={"credential": member_key.get(options)}
    )
    assert wrong.status_code == 401


async def test_registration_needs_recent_sign_in_and_rename_remove_work(
    owner: httpx2.AsyncClient, admin_engine: AsyncEngine
) -> None:
    key = SoftAuthenticator()
    added = await add_passkey(owner, key)
    passkey_id = added["id"]
    renamed = await owner.patch(
        f"/api/account/security/passkeys/{passkey_id}", json={"name": "Work laptop"}
    )
    assert renamed.status_code == 204
    async with admin_engine.begin() as conn:
        await conn.execute(text("UPDATE sessions SET reauth_at = now() - interval '1 hour'"))
    assert (await owner.post("/api/account/security/passkeys/options")).status_code == 403
    assert (await owner.delete(f"/api/account/security/passkeys/{passkey_id}")).status_code == 403

    options = (await owner.post("/api/auth/reauth/passkey/options")).json()
    reauth = await owner.post("/api/auth/reauth/passkey", json={"credential": key.get(options)})
    assert reauth.status_code == 204
    assert (await owner.delete(f"/api/account/security/passkeys/{passkey_id}")).status_code == 204
    status = (await owner.get("/api/account/security")).json()
    assert status["passkeys"] == []
    assert status["recovery_codes_left"] == 0  # no second factor left
