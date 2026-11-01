# SPDX-License-Identifier: AGPL-3.0-or-later
"""Importing an OpenChart export: how data moves between the desktop app and a server."""

from typing import Any

import httpx2
import pytest

from .conftest import Invite

pytestmark = pytest.mark.anyio


async def _fill(client: httpx2.AsyncClient) -> None:
    for iid in ("NASDAQ:NVDA", "LSE:BA."):
        await client.post("/api/watchlist", json={"instrument_id": iid})
    await client.post("/api/instruments/NASDAQ:NVDA/thesis", json={"summary": "First"})
    await client.post(
        "/api/instruments/NASDAQ:NVDA/thesis",
        json={"summary": "AI capex", "fair_value": "250", "conviction": "high"},
    )
    await client.put("/api/instruments/LSE:BA./research/notes", json={"body": "Order book"})
    research = (await client.get("/api/instruments/LSE:BA./research")).json()
    first = research["tasks"][0]["id"]
    await client.patch(f"/api/instruments/LSE:BA./research/tasks/{first}", json={"done": True})
    await client.post("/api/instruments/LSE:BA./research/tasks", json={"label": "Read the RNS"})
    await client.post(
        "/api/positions",
        json={
            "instrument_id": "LSE:BA.",
            "quantity": "10",
            "average_price": "20",
            "account": "isa",
        },
    )
    await client.post(
        "/api/alerts",
        json={"instrument_id": "CRYPTO:BTC-USD", "direction": "above", "price": "100000"},
    )
    await client.put("/api/preferences", json={"chart_type": "line", "compact": True})


def _comparable(export: dict[str, Any]) -> dict[str, Any]:
    """The parts of an export that should survive a move."""
    return {
        "watchlist": export["watchlist"],
        "theses": {
            iid: [
                {k: v[k] for k in ("summary", "fair_value", "conviction", "created_at")} for v in vs
            ]
            for iid, vs in export["theses"].items()
        },
        "research": export["research"],
        "positions": [
            (p["instrument"]["id"], p["quantity"], p["average_price"], p["account"])
            for p in export["positions"]
        ],
        "alerts": [(a["instrument"]["id"], a["direction"], a["price"]) for a in export["alerts"]],
        "preferences": export["preferences"],
    }


async def test_export_moves_to_another_account(
    owner: httpx2.AsyncClient, invite_user: Invite
) -> None:
    await _fill(owner)
    export = (await owner.get("/api/export")).json()

    other = await invite_user("member@example.com")
    result = await other.post("/api/import", json=export)
    assert result.status_code == 200, result.text
    assert result.json() == {
        "watchlist": 2,
        "theses": 2,
        "research": 1,
        "positions": 1,
        "alerts": 1,
        "preferences": True,
        "skipped_symbols": [],
    }
    moved = (await other.get("/api/export")).json()
    assert _comparable(moved) == _comparable(export)

    again = (await other.post("/api/import", json=export)).json()
    assert again["watchlist"] == again["theses"] == again["positions"] == again["alerts"] == 0
    assert again["research"] == 0
    assert _comparable((await other.get("/api/export")).json()) == _comparable(export)


async def test_import_merges_with_existing_data(owner: httpx2.AsyncClient) -> None:
    await owner.put("/api/instruments/LSE:BA./research/notes", json={"body": "Mine"})
    export = {
        "format": "openchart-export",
        "version": 1,
        "watchlist": ["LSE:BA.", "NOWHERE:XYZ"],
        "research": {
            "LSE:BA.": {"notes": "Theirs", "tasks": [{"label": "New task", "done": True}]}
        },
    }
    result = (await owner.post("/api/import", json=export)).json()
    assert result["skipped_symbols"] == ["NOWHERE:XYZ"]
    research = (await owner.get("/api/instruments/LSE:BA./research")).json()
    assert research["notes"].startswith("Mine")
    assert research["notes"].endswith("Theirs")
    assert {"label": "New task", "done": True}.items() <= research["tasks"][-1].items()


@pytest.mark.parametrize(
    "body",
    [
        {"format": "openchart-v4-preview"},
        {"format": "openchart-export", "version": 2},
        {"format": "openchart-export", "version": 1, "watchlist": ["not an id"]},
        {"format": "openchart-export", "version": 1, "watchlist": ["LSE:BA."] * 501},
        {
            "format": "openchart-export",
            "version": 1,
            "positions": [{"instrument": {"id": "LSE:BA."}, "quantity": "-1"}],
        },
        {"format": "openchart-export", "version": 1, "preferences": {"chart_type": "pie"}},
    ],
)
async def test_rejects_invalid_files(owner: httpx2.AsyncClient, body: dict[str, Any]) -> None:
    assert (await owner.post("/api/import", json=body)).status_code == 422
    assert (await owner.get("/api/watchlist")).json() == []


async def test_import_needs_sign_in(client: httpx2.AsyncClient) -> None:
    body = {"format": "openchart-export", "version": 1}
    assert (await client.post("/api/import", json=body)).status_code == 401
