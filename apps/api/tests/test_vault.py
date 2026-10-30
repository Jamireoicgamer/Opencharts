# SPDX-License-Identifier: AGPL-3.0-or-later
"""Secrets are encrypted at rest, bound to their owner, and never returned."""

import os
from dataclasses import replace
from uuid import UUID, uuid4

import httpx2
import pytest
from cryptography.exceptions import InvalidTag
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from openchart_api import vault
from openchart_api.db import set_rls_context

pytestmark = pytest.mark.anyio

KEY = os.urandom(32)
VALUE = "sk-live-0123456789abcdef"


def _flip_first_bit(data: bytes) -> bytes:
    return bytes([data[0] ^ 1]) + data[1:]


def test_seal_round_trip() -> None:
    user = uuid4()
    assert vault.unseal(KEY, user, "finnhub", vault.seal(KEY, user, "finnhub", VALUE)) == VALUE


def test_each_seal_uses_fresh_key_and_nonce() -> None:
    user = uuid4()
    a, b = vault.seal(KEY, user, "x", VALUE), vault.seal(KEY, user, "x", VALUE)
    assert a.ciphertext != b.ciphertext
    assert a.wrapped_dek != b.wrapped_dek


@pytest.mark.parametrize("change", ["user", "name", "master_key", "ciphertext", "wrapped_dek"])
def test_tampering_is_detected(change: str) -> None:
    user, name, key = uuid4(), "finnhub", KEY
    sealed = vault.seal(key, user, name, VALUE)
    if change == "user":
        user = uuid4()
    elif change == "name":
        name = "polygon"
    elif change == "master_key":
        key = os.urandom(32)
    elif change == "ciphertext":
        sealed = replace(sealed, ciphertext=_flip_first_bit(sealed.ciphertext))
    else:
        sealed = replace(sealed, wrapped_dek=_flip_first_bit(sealed.wrapped_dek))
    with pytest.raises(InvalidTag):
        vault.unseal(key, user, name, sealed)


def test_hint_only_for_long_values() -> None:
    assert vault.hint(VALUE) == "…cdef"
    assert vault.hint("short-key") == ""


async def test_api_never_returns_the_value(
    owner: httpx2.AsyncClient, admin_engine: AsyncEngine
) -> None:
    saved = await owner.put("/api/secrets/finnhub", json={"value": VALUE, "provider": "Finnhub"})
    assert saved.status_code == 204
    listed = await owner.get("/api/secrets")
    assert listed.json() == [
        {
            "name": "finnhub",
            "provider": "Finnhub",
            "hint": "…cdef",
            "created_at": listed.json()[0]["created_at"],
            "updated_at": listed.json()[0]["updated_at"],
        }
    ]
    for path in ("/api/secrets", "/api/audit", "/api/auth/me", "/api/auth/sessions"):
        assert VALUE not in (await owner.get(path)).text

    async with admin_engine.connect() as conn:
        dump = await conn.scalar(text("SELECT string_agg(t::text, '|') FROM vault_secrets t"))
        audit = await conn.scalar(text("SELECT string_agg(a::text, '|') FROM audit_log a"))
    assert dump is not None
    assert VALUE not in dump
    assert VALUE.encode().hex() not in dump
    assert VALUE not in (audit or "")


async def test_replace_and_delete(owner: httpx2.AsyncClient) -> None:
    await owner.put("/api/secrets/finnhub", json={"value": VALUE})
    await owner.put("/api/secrets/finnhub", json={"value": "replacement-value-9999"})
    listed = (await owner.get("/api/secrets")).json()
    assert [s["hint"] for s in listed] == ["…9999"]
    assert (await owner.delete("/api/secrets/finnhub")).status_code == 204
    assert (await owner.get("/api/secrets")).json() == []
    assert (await owner.delete("/api/secrets/finnhub")).status_code == 404


async def test_invalid_names_are_rejected(owner: httpx2.AsyncClient) -> None:
    for name in ("UPPER", "-leading", "a" * 65, "with space"):
        response = await owner.put(f"/api/secrets/{name}", json={"value": VALUE})
        assert response.status_code == 422, name


async def test_server_side_reveal(owner: httpx2.AsyncClient, app: FastAPI) -> None:
    await owner.put("/api/secrets/finnhub", json={"value": VALUE})
    user_id = UUID((await owner.get("/api/auth/me")).json()["id"])
    async with app.state.engine.begin() as conn:
        await set_rls_context(conn, user_id, "owner")
        revealed = await vault.reveal(conn, app.state.settings.master_key_bytes, user_id, "finnhub")
    assert revealed == VALUE
