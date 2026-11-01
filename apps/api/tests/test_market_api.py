# SPDX-License-Identifier: AGPL-3.0-or-later
"""Market endpoints, the price WebSocket and data-source settings."""

import asyncio
import json
from collections.abc import MutableMapping
from typing import Any
from uuid import UUID

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from openchart_api.db import set_rls_context
from openchart_api.market.hub import Hub
from openchart_api.market.sources import SourceConfig
from openchart_api.tables import data_sources

from .conftest import ORIGIN, Invite
from .test_market_hub import BAE, BTC, FakeProvider

pytestmark = pytest.mark.anyio


@pytest.fixture
async def fake(app: FastAPI) -> FakeProvider:
    """Replace the app's providers with one fake crypto source."""
    provider = FakeProvider()
    hub: Hub = app.state.hub
    hub._factory = lambda c: provider
    hub._poll = {"fake": 0.01}
    hub._retry_delay = lambda failures: 0.01
    await hub.reload_sources([SourceConfig("fake", 1, True, None)])
    return provider


async def test_quotes(owner: httpx2.AsyncClient, fake: FakeProvider) -> None:
    result = (await owner.get("/api/market/quotes", params={"ids": f"{BTC},{BAE}"})).json()
    assert result[0]["quote"]["price"] == "100"
    assert result[0]["quote"]["change_pct"] == "11.11"
    assert result[0]["quote"]["source"] == "fake"
    assert result[1] == {"instrument_id": BAE, "quote": None, "reason": "no_source"}
    bad = await owner.get("/api/market/quotes", params={"ids": "not valid"})
    assert bad.status_code == 422


async def test_quotes_and_candles_need_sign_in(
    client: httpx2.AsyncClient, fake: FakeProvider
) -> None:
    assert (await client.get("/api/market/quotes", params={"ids": BTC})).status_code == 401
    assert (await client.get(f"/api/market/candles/{BTC}")).status_code == 401


async def test_candles(owner: httpx2.AsyncClient, fake: FakeProvider) -> None:
    body = (await owner.get(f"/api/market/candles/{BTC}", params={"period": "1W"})).json()
    assert body["interval"] == "1h" and body["sources"] == ["fake"] and not body["stale"]
    assert body["candles"][0]["open"] == "1.0000000000"
    missing = await owner.get(f"/api/market/candles/{BAE}", params={"period": "1W"})
    assert (missing.status_code, missing.json()["detail"]) == (404, "no_source")
    assert (await owner.get("/api/market/candles/NOPE:X")).status_code == 404
    assert (
        await owner.get(f"/api/market/candles/{BTC}", params={"period": "5Y"})
    ).status_code == 422


# WebSocket ---------------------------------------------------------------------


class Socket:
    """Drives the app's WebSocket endpoint with raw ASGI messages."""

    def __init__(self, app: FastAPI, headers: dict[str, str]) -> None:
        self.inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.outbox: asyncio.Queue[MutableMapping[str, Any]] = asyncio.Queue()
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "ws",
            "path": "/api/market/stream",
            "raw_path": b"/api/market/stream",
            "query_string": b"",
            "root_path": "",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "subprotocols": [],
            "state": {},
        }
        self.seen: list[dict[str, Any]] = []
        self.inbox.put_nowait({"type": "websocket.connect"})
        self.task = asyncio.create_task(app(scope, self.inbox.get, self.outbox.put))

    async def first(self) -> MutableMapping[str, Any]:
        return await asyncio.wait_for(self.outbox.get(), 3)

    async def send(self, message: dict[str, Any]) -> None:
        await self.inbox.put({"type": "websocket.receive", "text": json.dumps(message)})

    async def receive(self, kind: str) -> dict[str, Any]:
        """The next message of this kind; every message is kept in ``seen``."""

        async def find() -> dict[str, Any]:
            while True:
                message = await self.outbox.get()
                if message["type"] == "websocket.close":
                    raise ConnectionError(f"closed: {message.get('code')}")
                data: dict[str, Any] = json.loads(message["text"])
                self.seen.append(data)
                if data["type"] == kind:
                    return data

        return await asyncio.wait_for(find(), 3)

    async def close(self) -> None:
        await self.inbox.put({"type": "websocket.disconnect", "code": 1000})
        await asyncio.wait_for(self.task, 3)


def cookie_header(client: httpx2.AsyncClient) -> str:
    return "; ".join(f"{name}={value}" for name, value in client.cookies.items())


async def test_socket_rejects_other_origins_and_strangers(
    app: FastAPI, owner: httpx2.AsyncClient, fake: FakeProvider
) -> None:
    hijack = Socket(
        app,
        {"host": "testserver", "origin": "https://evil.example", "cookie": cookie_header(owner)},
    )
    assert (await hijack.first()) == {"type": "websocket.close", "code": 1008, "reason": ""}
    stranger = Socket(app, {"host": "testserver", "origin": ORIGIN})
    assert (await stranger.first())["type"] == "websocket.close"


async def test_socket_streams_quotes_and_alerts(
    app: FastAPI, owner: httpx2.AsyncClient, fake: FakeProvider
) -> None:
    socket = Socket(app, {"host": "testserver", "origin": ORIGIN, "cookie": cookie_header(owner)})
    assert (await socket.first())["type"] == "websocket.accept"
    await socket.send({"type": "watch", "ids": [BTC, "bad id", BAE]})
    assert (await socket.receive("watching"))["ids"] == [BTC, BAE]
    quote = await socket.receive("quote")
    assert (quote["instrument_id"], quote["price"], quote["delay"]) == (BTC, "100", "realtime")

    await owner.post(
        "/api/alerts", json={"instrument_id": BTC, "direction": "above", "price": "99"}
    )
    await app.state.hub.refresh_alerts()
    alert = await socket.receive("alert")
    assert (alert["instrument_id"], alert["level"], alert["price"]) == (
        BTC,
        "99.0000000000",
        "100",
    )
    statuses = {(m["instrument_id"], m["state"]) for m in socket.seen if m["type"] == "status"}
    assert {(BTC, "live"), (BAE, "no_source")} <= statuses
    await socket.close()


async def test_socket_closes_when_the_session_ends(
    app: FastAPI, owner: httpx2.AsyncClient, fake: FakeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("openchart_api.routes.market.SESSION_RECHECK_SECONDS", 0.05)
    socket = Socket(app, {"host": "testserver", "origin": ORIGIN, "cookie": cookie_header(owner)})
    assert (await socket.first())["type"] == "websocket.accept"
    await owner.post("/api/auth/logout")
    with pytest.raises(ConnectionError, match="1008"):
        await socket.receive("quote-never")


# Data sources -------------------------------------------------------------------


async def test_members_see_which_sources_are_on_but_nothing_else(
    owner: httpx2.AsyncClient, invite_user: Invite, app_engine: AsyncEngine
) -> None:
    member = await invite_user("member@example.com")
    sources = (await member.get("/api/data-sources")).json()
    assert {s["provider"] for s in sources} == {"coinbase", "kraken", "yahoo", "twelvedata"}
    assert all(s["enabled"] is None and s["key_hint"] is None for s in sources)
    refused = await member.put("/api/admin/data-sources/yahoo", json={"enabled": True})
    assert refused.status_code == 403

    member_id = UUID((await member.get("/api/auth/me")).json()["id"])
    async with app_engine.begin() as conn:
        await set_rls_context(conn, member_id, "member")
        assert (await conn.execute(select(data_sources))).all() == []


async def test_owner_turns_on_yahoo_and_sets_a_key(
    owner: httpx2.AsyncClient, app: FastAPI, admin_engine: AsyncEngine
) -> None:
    hub: Hub = app.state.hub
    seen: list[list[SourceConfig]] = []
    reload = hub.reload_sources

    async def spy(configs: list[SourceConfig] | None = None) -> None:
        seen.append(list(configs or []))
        await reload(configs)

    hub.reload_sources = spy  # type: ignore[method-assign]

    # Enabling alone is not enough: the terms must be accepted.
    after = (await owner.put("/api/admin/data-sources/yahoo", json={"enabled": True})).json()
    yahoo = next(s for s in after if s["provider"] == "yahoo")
    assert (yahoo["enabled"], yahoo["terms_accepted"], yahoo["active"]) == (True, False, False)
    after = (await owner.put("/api/admin/data-sources/yahoo", json={"accept_terms": True})).json()
    assert next(s for s in after if s["provider"] == "yahoo")["active"] is True

    no_terms = await owner.put("/api/admin/data-sources/coinbase", json={"accept_terms": True})
    assert no_terms.status_code == 422

    key = "td-secret-abcdef123456"
    after = (
        await owner.put(
            "/api/admin/data-sources/twelvedata", json={"api_key": key, "enabled": True}
        )
    ).json()
    twelve = next(s for s in after if s["provider"] == "twelvedata")
    assert (twelve["key_hint"], twelve["active"]) == ("…3456", True)
    assert key not in json.dumps(after)
    assert seen[-1][-1] == SourceConfig("twelvedata", 40, False, key)

    async with admin_engine.connect() as conn:
        stored = (
            await conn.execute(
                text("SELECT key_ciphertext FROM data_sources WHERE provider = 'twelvedata'")
            )
        ).scalar_one()
        assert key.encode() not in bytes(stored)
        actions = list(
            await conn.scalars(
                text("SELECT action FROM audit_log WHERE action = 'data_source.changed'")
            )
        )
        assert len(actions) == 3  # the refused change is not recorded

    removed = (
        await owner.put("/api/admin/data-sources/twelvedata", json={"remove_key": True})
    ).json()
    assert next(s for s in removed if s["provider"] == "twelvedata")["key_hint"] is None


async def test_changing_sources_needs_a_recent_sign_in(
    owner: httpx2.AsyncClient, admin_engine: AsyncEngine
) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(text("UPDATE sessions SET reauth_at = now() - interval '1 hour'"))
    response = await owner.put("/api/admin/data-sources/kraken", json={"enabled": False})
    assert (response.status_code, response.json()["detail"]) == (403, "reauth_required")
