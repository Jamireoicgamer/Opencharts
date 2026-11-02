# SPDX-License-Identifier: AGPL-3.0-or-later
"""Importing what the V4.1 prototype saved: its export file and raw localStorage."""

import json
from typing import Any

import httpx2
import pytest

pytestmark = pytest.mark.anyio

# The shape of the prototype's "Export workspace" file (legacy/index.html).
EXPORT: dict[str, Any] = {
    "format": "openchart-v4-preview",
    "exportedAt": "2026-10-20T10:00:00.000Z",
    "watchSymbols": ["BA.", "RR.", "GRAB", "MKS", "MYSTERY"],
    "positions": [{"symbol": "NVDA", "qty": 12.5}, {"symbol": "NVDA", "qty": "not a number"}],
    "riskApproach": "Aggressive",
    "alerts": [{"symbol": "BTC/USD", "direction": "above", "price": 70000}],
    "preferences": {"showGrid": False, "showOHLC": True, "compact": False},
    "theses": {
        "BA.": {
            "latest": {
                "text": "Rearmament cycle",
                "risk": "Budget cuts",
                "bull": "",
                "bear": "",
                "fairValue": "22",
                "entry": "",
                "conviction": "Moderate",
                "horizon": "1\u20133 years",
                "savedAt": "2026-10-19T09:00:00.000Z",
            },
            "history": [
                {
                    "text": "First idea",
                    "savedAt": "2026-10-01T09:00:00.000Z",
                    "conviction": "Low",
                    "horizon": "Not set",
                },
                {
                    "text": "Rearmament cycle",
                    "risk": "Budget cuts",
                    "fairValue": "22",
                    "conviction": "Moderate",
                    "horizon": "1\u20133 years",
                    "savedAt": "2026-10-19T09:00:00.000Z",
                },
            ],
        },
        "RR.": {"latest": {}, "history": []},
    },
    "research": {
        "MKS": {"notes": "Clothing margins improving", "tasks": [0, 2]},
        "GRAB": {"notes": "", "tasks": []},
    },
}


async def test_import_the_prototype_export(owner: httpx2.AsyncClient) -> None:
    result = await owner.post("/api/import/legacy", json=EXPORT)
    assert result.status_code == 200, result.text
    assert result.json() == {
        "watchlist": 4,
        "theses": 2,
        "research": 1,
        "positions": 1,
        "alerts": 1,
        "drawings": 0,
        "preferences": True,
        "skipped_symbols": ["MYSTERY"],
    }
    watch = [i["id"] for i in (await owner.get("/api/watchlist")).json()]
    assert watch == ["LSE:BA.", "LSE:RR.", "NASDAQ:GRAB", "LSE:MKS"]

    thesis = (await owner.get("/api/instruments/LSE:BA./thesis")).json()
    assert thesis["current"]["summary"] == "Rearmament cycle"
    assert thesis["current"]["conviction"] == "moderate"
    assert thesis["current"]["horizon"] == "1_3y"
    assert thesis["current"]["fair_value"] == "22.0000000000"
    assert thesis["current"]["created_at"].startswith("2026-10-19T09:00")
    assert len(thesis["history"]) == 2

    research = (await owner.get("/api/instruments/LSE:MKS/research")).json()
    assert research["notes"] == "Clothing margins improving"
    assert [t["done"] for t in research["tasks"]] == [True, False, True]

    positions = (await owner.get("/api/positions")).json()
    assert positions[0]["instrument"]["id"] == "NASDAQ:NVDA"
    assert positions[0]["quantity"] == "12.5000000000"
    alert = (await owner.get("/api/alerts")).json()[0]
    assert (alert["instrument"]["id"], alert["direction"], alert["price"]) == (
        "CRYPTO:BTC-USD",
        "above",
        "70000.0000000000",
    )
    prefs = (await owner.get("/api/preferences")).json()
    assert prefs["show_grid"] is False
    assert prefs["show_ohlc"] is True
    assert prefs["risk_profile"] == "aggressive"


async def test_importing_twice_adds_nothing(owner: httpx2.AsyncClient) -> None:
    await owner.post("/api/import/legacy", json=EXPORT)
    again = (await owner.post("/api/import/legacy", json=EXPORT)).json()
    assert again["watchlist"] == again["theses"] == again["positions"] == again["alerts"] == 0
    research = (await owner.get("/api/instruments/LSE:MKS/research")).json()
    assert research["notes"] == "Clothing margins improving"


async def test_import_raw_local_storage(owner: httpx2.AsyncClient) -> None:
    """What the import page sends when it finds the prototype's data in this browser."""
    items = {
        "oc-watch-symbols": json.dumps(["NVDA", "BTC/USD"]),
        "oc-positions": json.dumps([{"symbol": "BA.", "qty": 3}]),
        "oc-alerts": "[]",
        "oc-risk-profile": "Conservative",
        "oc-grid": "true",
        "oc-type": "line",
        "oc-period": "1Y",
        "oc-symbol": "NVDA",
        "oc-thesis-NVDA": json.dumps({"text": "Compute demand", "savedAt": "2026-10-10T00:00:00Z"}),
        "oc-research-notes-NVDA": "Watch gross margin",
        "oc-research-tasks-NVDA": "[1]",
        "unrelated-key": "ignored",
    }
    result = (
        await owner.post("/api/import/legacy", json={"format": "localstorage", "items": items})
    ).json()
    assert result["watchlist"] == 2
    assert result["theses"] == 1
    prefs = (await owner.get("/api/preferences")).json()
    assert (prefs["chart_type"], prefs["period"], prefs["last_instrument"]) == (
        "line",
        "1Y",
        "NASDAQ:NVDA",
    )
    research = (await owner.get("/api/instruments/NASDAQ:NVDA/research")).json()
    assert [t["done"] for t in research["tasks"]] == [False, True, False]


@pytest.mark.parametrize(
    "payload",
    [
        {"format": "something-else"},
        {"format": "localstorage", "items": "not a dict"},
        {},
    ],
)
async def test_other_data_is_refused(owner: httpx2.AsyncClient, payload: dict[str, Any]) -> None:
    assert (await owner.post("/api/import/legacy", json=payload)).status_code == 422


async def test_hostile_values_are_ignored_not_trusted(owner: httpx2.AsyncClient) -> None:
    hostile = {
        "format": "openchart-v4-preview",
        "watchSymbols": ["NVDA", 42, None, "x" * 500],
        "positions": [{"symbol": "NVDA", "qty": "1e999"}, {"symbol": "NVDA", "qty": -5}],
        "alerts": [{"symbol": "NVDA", "direction": "DROP TABLE", "price": 1}],
        "theses": {"NVDA": {"latest": {"text": "x" * 20000, "fairValue": "NaN"}}},
        "preferences": {"showGrid": "yes"},
        "riskApproach": "Reckless",
    }
    result = (await owner.post("/api/import/legacy", json=hostile)).json()
    assert result["watchlist"] == 1
    assert result["positions"] == 0
    assert result["alerts"] == 0
    assert result["preferences"] is False
    thesis = (await owner.get("/api/instruments/NASDAQ:NVDA/thesis")).json()["current"]
    assert len(thesis["summary"]) == 10000
    assert thesis["fair_value"] is None
