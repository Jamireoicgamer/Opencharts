# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chart drawings: saved per user and instrument, validated, private."""

from typing import Any
from uuid import UUID

import httpx2
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from openchart_api.db import set_rls_context
from openchart_api.routes.workspace import drawings as module

from .conftest import Invite

pytestmark = pytest.mark.anyio

BTC = "/api/instruments/CRYPTO:BTC-USD/drawings"
T0 = 1_793_500_000


def trend(**over: Any) -> dict[str, Any]:
    return {
        "kind": "trend",
        "points": [{"t": T0, "price": 70000}, {"t": T0 + 3600, "price": 71000.5}],
        **over,
    }


async def test_add_change_and_delete(owner: httpx2.AsyncClient) -> None:
    created = await owner.post(BTC, json=trend(color="amber"))
    assert created.status_code == 201, created.text
    drawing = created.json()
    assert drawing["color"] == "amber" and drawing["text"] == ""
    level = (
        await owner.post(
            BTC, json={"kind": "hline", "points": [{"t": T0, "price": 69000}], "text": "support"}
        )
    ).json()
    assert [d["id"] for d in (await owner.get(BTC)).json()] == [drawing["id"], level["id"]]

    moved = await owner.patch(
        f"{BTC}/{drawing['id']}",
        json={"points": [{"t": T0, "price": 70100}, {"t": T0 + 7200, "price": 72000}]},
    )
    assert moved.status_code == 200
    assert moved.json()["points"][1] == {"t": T0 + 7200, "price": 72000}
    assert moved.json()["color"] == "amber"  # untouched
    # A trend line keeps two points.
    wrong = await owner.patch(f"{BTC}/{drawing['id']}", json={"points": [{"t": T0, "price": 1}]})
    assert wrong.status_code == 422

    assert (await owner.delete(f"{BTC}/{drawing['id']}")).status_code == 204
    assert (await owner.delete(f"{BTC}/{drawing['id']}")).status_code == 404
    assert (await owner.delete(BTC)).status_code == 204
    assert (await owner.get(BTC)).json() == []


@pytest.mark.parametrize(
    "body",
    [
        trend(kind="circle"),
        trend(points=[{"t": T0, "price": 1}]),  # a trend line needs two points
        {"kind": "hline", "points": [{"t": T0, "price": 1}, {"t": T0, "price": 2}]},
        trend(points=[{"t": T0, "price": -5}, {"t": T0, "price": 1}]),
        trend(points=[{"t": T0, "price": "NaN"}, {"t": T0, "price": 1}]),
        trend(points=[{"t": -1, "price": 1}, {"t": T0, "price": 1}]),
        trend(color="#ff0000"),  # theme colours only, never raw CSS
        trend(text="x" * 201),
        trend(extra=True),
    ],
)
async def test_rejects_invalid_drawings(owner: httpx2.AsyncClient, body: dict[str, Any]) -> None:
    assert (await owner.post(BTC, json=body)).status_code == 422


async def test_unknown_instrument_and_limit(
    owner: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (await owner.get("/api/instruments/NOWHERE:XYZ/drawings")).status_code == 404
    monkeypatch.setattr(module, "MAX_DRAWINGS", 2)
    for _ in range(2):
        assert (await owner.post(BTC, json=trend())).status_code == 201
    assert (await owner.post(BTC, json=trend())).status_code == 409


async def test_drawings_are_private(
    owner: httpx2.AsyncClient, invite_user: Invite, app_engine: AsyncEngine
) -> None:
    mine = (await owner.post(BTC, json=trend())).json()
    member = await invite_user("member@example.com")
    assert (await member.get(BTC)).json() == []
    assert (await member.patch(f"{BTC}/{mine['id']}", json={"color": "red"})).status_code == 404
    assert (await member.delete(f"{BTC}/{mine['id']}")).status_code == 404
    await member.delete(BTC)  # clears only their own
    assert len((await owner.get(BTC)).json()) == 1

    member_id = UUID((await member.get("/api/auth/me")).json()["id"])
    async with app_engine.begin() as conn:
        await set_rls_context(conn, member_id, "member")
        assert await conn.scalar(text("SELECT count(*) FROM drawings")) == 0


async def test_drawings_move_with_the_workspace(
    owner: httpx2.AsyncClient, invite_user: Invite
) -> None:
    await owner.post(BTC, json=trend(color="blue", text="breakout"))
    await owner.post(
        "/api/instruments/LSE:BA./drawings",
        json={"kind": "note", "points": [{"t": T0, "price": 2000}], "text": "results day"},
    )
    export = (await owner.get("/api/export")).json()
    assert set(export["drawings"]) == {"CRYPTO:BTC-USD", "LSE:BA."}

    other = await invite_user("other@example.com")
    first = (await other.post("/api/import", json=export)).json()
    assert first["drawings"] == 2
    again = (await other.post("/api/import", json=export)).json()
    assert again["drawings"] == 0
    copied = (await other.get(BTC)).json()
    assert [(d["kind"], d["color"], d["text"]) for d in copied] == [("trend", "blue", "breakout")]
    assert copied[0]["points"] == export["drawings"]["CRYPTO:BTC-USD"][0]["points"]
