# SPDX-License-Identifier: AGPL-3.0-or-later
"""The workspace API: instruments, watchlist, theses, research, positions,
alerts, preferences and export."""

from uuid import UUID

import httpx2
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from openchart_api.db import set_rls_context

from .conftest import Invite

pytestmark = pytest.mark.anyio


async def test_instrument_search(owner: httpx2.AsyncClient) -> None:
    hits = (await owner.get("/api/instruments", params={"q": "nvda"})).json()
    assert hits[0]["id"] == "NASDAQ:NVDA"
    assert hits[0]["currency"] == "USD"
    by_name = (await owner.get("/api/instruments", params={"q": "rolls"})).json()
    assert [h["id"] for h in by_name] == ["LSE:RR."]
    assert by_name[0]["currency"] == "GBX"
    # LIKE wildcards are matched literally, not as patterns.
    assert (await owner.get("/api/instruments", params={"q": "%"})).json() == []
    one = await owner.get("/api/instruments/CRYPTO:BTC-USD")
    assert one.json()["name"] == "Bitcoin"
    assert (await owner.get("/api/instruments/NOPE:XYZ")).status_code == 404
    assert (await owner.get("/api/instruments/not valid")).status_code == 422


async def test_watchlist_add_order_remove(owner: httpx2.AsyncClient) -> None:
    for iid in ("LSE:BA.", "NASDAQ:NVDA", "CRYPTO:BTC-USD"):
        assert (await owner.post("/api/watchlist", json={"instrument_id": iid})).status_code == 201
    # Adding twice is harmless.
    again = (await owner.post("/api/watchlist", json={"instrument_id": "LSE:BA."})).json()
    assert [i["id"] for i in again] == ["LSE:BA.", "NASDAQ:NVDA", "CRYPTO:BTC-USD"]
    reordered = await owner.put(
        "/api/watchlist/order",
        json={"instrument_ids": ["CRYPTO:BTC-USD", "LSE:BA.", "NASDAQ:NVDA"]},
    )
    assert [i["id"] for i in reordered.json()] == ["CRYPTO:BTC-USD", "LSE:BA.", "NASDAQ:NVDA"]
    bad_order = await owner.put("/api/watchlist/order", json={"instrument_ids": ["LSE:BA."]})
    assert bad_order.status_code == 409
    left = (await owner.delete("/api/watchlist/LSE:BA.")).json()
    assert [i["id"] for i in left] == ["CRYPTO:BTC-USD", "NASDAQ:NVDA"]
    unknown = await owner.post("/api/watchlist", json={"instrument_id": "LSE:NOPE"})
    assert unknown.status_code == 404


async def test_thesis_versions_form_a_journal(owner: httpx2.AsyncClient) -> None:
    url = "/api/instruments/LSE:BA./thesis"
    assert (await owner.get(url)).json() == {"current": None, "history": []}
    first = await owner.post(
        url,
        json={"summary": "Defence spending rises", "fair_value": "21.50", "conviction": "moderate"},
    )
    assert first.status_code == 201
    assert first.json()["fair_value"] == "21.5000000000"
    await owner.post(url, json={"summary": "Defence spending rises faster", "conviction": "high"})
    thesis = (await owner.get(url)).json()
    assert thesis["current"]["summary"] == "Defence spending rises faster"
    assert [v["summary"] for v in thesis["history"]] == [
        "Defence spending rises faster",
        "Defence spending rises",
    ]
    invalid = await owner.post(url, json={"fair_value": "-3"})
    assert invalid.status_code == 422
    assert (await owner.delete(url)).status_code == 204
    assert (await owner.get(url)).json()["history"] == []


async def test_research_checklist_and_notes(owner: httpx2.AsyncClient) -> None:
    url = "/api/instruments/NASDAQ:NVDA/research"
    research = (await owner.get(url)).json()
    assert [t["label"] for t in research["tasks"]] == [
        "Review the latest company financial results",
        "Check company guidance and regulatory filings",
        "Compare new evidence against your thesis",
    ]
    first = research["tasks"][0]["id"]
    toggled = (await owner.patch(f"/api/research/tasks/{first}", json={"done": True})).json()
    assert toggled["tasks"][0]["done"] is True
    added = (await owner.post(f"{url}/tasks", json={"label": "  Read the 10-K  "})).json()
    assert added["tasks"][-1]["label"] == "Read the 10-K"
    noted = (await owner.put(f"{url}/notes", json={"body": "Data-centre demand"})).json()
    assert noted["notes"] == "Data-centre demand"
    # Deleting every task does not bring the defaults back.
    for task in noted["tasks"]:
        await owner.delete(f"/api/research/tasks/{task['id']}")
    assert (await owner.get(url)).json()["tasks"] == []


async def test_positions_and_alerts(owner: httpx2.AsyncClient) -> None:
    made = await owner.post(
        "/api/positions",
        json={
            "instrument_id": "LSE:RR.",
            "quantity": "120",
            "average_price": "4.215",
            "account": "isa",
        },
    )
    assert made.status_code == 201
    position = made.json()
    assert position["instrument"]["name"] == "Rolls-Royce Holdings"
    assert position["quantity"] == "120.0000000000"
    changed = await owner.patch(f"/api/positions/{position['id']}", json={"quantity": "150"})
    assert changed.json()["quantity"] == "150.0000000000"
    zero = await owner.patch(f"/api/positions/{position['id']}", json={"quantity": "0"})
    assert zero.status_code == 422
    assert len((await owner.get("/api/positions")).json()) == 1
    assert (await owner.delete(f"/api/positions/{position['id']}")).status_code == 204

    alert = (
        await owner.post(
            "/api/alerts",
            json={"instrument_id": "CRYPTO:BTC-USD", "direction": "above", "price": "100000"},
        )
    ).json()
    assert alert["active"] is True
    assert alert["triggered_at"] is None
    paused = await owner.patch(f"/api/alerts/{alert['id']}", json={"active": False})
    assert paused.json()["active"] is False
    sideways = await owner.post(
        "/api/alerts",
        json={"instrument_id": "CRYPTO:BTC-USD", "direction": "sideways", "price": "1"},
    )
    assert sideways.status_code == 422


async def test_preferences_merge_and_validate(owner: httpx2.AsyncClient) -> None:
    defaults = (await owner.get("/api/preferences")).json()
    assert defaults["chart_type"] == "candle"
    assert defaults["risk_profile"] == "balanced"
    changed = (await owner.put("/api/preferences", json={"chart_type": "line"})).json()
    assert changed["chart_type"] == "line"
    assert changed["period"] == "1M"  # untouched
    assert (await owner.put("/api/preferences", json={"theme": "pink"})).status_code == 422
    assert (await owner.put("/api/preferences", json={"period": "5Y"})).status_code == 422
    assert (await owner.get("/api/preferences")).json()["chart_type"] == "line"


async def test_export_contains_the_workspace(owner: httpx2.AsyncClient) -> None:
    await owner.post("/api/watchlist", json={"instrument_id": "NASDAQ:NVDA"})
    await owner.post("/api/instruments/NASDAQ:NVDA/thesis", json={"summary": "AI capex"})
    await owner.put("/api/instruments/NASDAQ:NVDA/research/notes", json={"body": "note"})
    exported = (await owner.get("/api/export")).json()
    assert exported["format"] == "openchart-export"
    assert exported["watchlist"] == ["NASDAQ:NVDA"]
    assert exported["theses"]["NASDAQ:NVDA"][0]["summary"] == "AI capex"
    assert exported["research"]["NASDAQ:NVDA"]["notes"] == "note"
    assert "password" not in str(exported).lower()


async def test_workspace_is_private_to_each_user(
    owner: httpx2.AsyncClient, invite_user: Invite, app_engine: AsyncEngine
) -> None:
    await owner.post("/api/watchlist", json={"instrument_id": "LSE:BA."})
    await owner.post("/api/instruments/LSE:BA./thesis", json={"summary": "secret plan"})
    await owner.get("/api/instruments/LSE:BA./research")
    await owner.post("/api/positions", json={"instrument_id": "LSE:BA.", "quantity": "10"})
    alert = await owner.post(
        "/api/alerts", json={"instrument_id": "LSE:BA.", "direction": "below", "price": "15"}
    )
    await owner.put("/api/preferences", json={"compact": True})

    member = await invite_user("member@example.com")
    assert (await member.get("/api/watchlist")).json() == []
    assert (await member.get("/api/instruments/LSE:BA./thesis")).json()["history"] == []
    assert (await member.get("/api/positions")).json() == []
    assert (await member.get("/api/alerts")).json() == []
    assert (await member.get("/api/preferences")).json()["compact"] is False
    assert (await member.delete(f"/api/alerts/{alert.json()['id']}")).status_code == 404

    member_id = UUID((await member.get("/api/auth/me")).json()["id"])
    async with app_engine.begin() as conn:
        await set_rls_context(conn, member_id, "member")
        for table in (
            "watchlist_items",
            "thesis_versions",
            "research_notes",
            "research_tasks",
            "positions",
            "alerts",
            "user_preferences",
        ):
            assert await conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0, table  # noqa: S608
        # Everyone can read the shared catalogue, nobody can change it.
        assert await conn.scalar(text("SELECT count(*) FROM instruments")) > 60
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text("UPDATE instruments SET name = 'x'"))


async def test_thesis_history_cannot_be_rewritten(
    owner: httpx2.AsyncClient, app_engine: AsyncEngine
) -> None:
    await owner.post("/api/instruments/LSE:BA./thesis", json={"summary": "original"})
    owner_id = UUID((await owner.get("/api/auth/me")).json()["id"])
    async with app_engine.begin() as conn:
        await set_rls_context(conn, owner_id, "owner")
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text("UPDATE thesis_versions SET summary = 'rewritten'"))


async def test_indicator_preferences(owner: httpx2.AsyncClient) -> None:
    chosen = [
        {"kind": "ema", "period": 20},
        {"kind": "ema", "period": 50},
        {"kind": "rsi"},
        {"kind": "macd"},
        {"kind": "volume"},
    ]
    saved = (await owner.put("/api/preferences", json={"indicators": chosen})).json()
    assert saved["indicators"][2] == {"kind": "rsi", "period": 14}  # default period filled in
    assert saved["indicators"][3] == {"kind": "macd", "period": None}
    assert (await owner.get("/api/preferences")).json()["indicators"] == saved["indicators"]
    # Other changes leave them alone.
    after = (await owner.put("/api/preferences", json={"compact": True})).json()
    assert after["indicators"] == saved["indicators"]

    for bad in (
        [{"kind": "sma", "period": 1}],
        [{"kind": "sma", "period": 401}],
        [{"kind": "macd", "period": 9}],
        [{"kind": "ichimoku"}],
        [{"kind": "ema", "period": 20}, {"kind": "ema", "period": 20}],
        [{"kind": "sma", "period": p} for p in range(2, 13)],
        [{"kind": "sma", "period": 20, "colour": "red"}],
    ):
        response = await owner.put("/api/preferences", json={"indicators": bad})
        assert response.status_code == 422, bad
    assert (await owner.get("/api/preferences")).json()["indicators"] == saved["indicators"]
