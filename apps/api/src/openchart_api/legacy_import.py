# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read data saved by the V4.1 prototype (``legacy/index.html``).

The prototype kept everything in the browser's localStorage under ``oc-*``
keys, and could export it as ``openchart-workspace.json``. Both shapes are
accepted. The input is untrusted: everything is size-capped, validated and
mapped to the instrument catalogue; anything unrecognised is skipped and
reported rather than failing the whole import.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from openchart_api.migrations.data.instruments_2026_10 import LEGACY_SYMBOLS

MAX_LIST = 1000
MAX_VERSIONS = 50

_CONVICTION = {"not assessed": "not_assessed", "low": "low", "moderate": "moderate", "high": "high"}
_HORIZON = {
    "not set": "not_set",
    "less than 1 year": "under_1y",
    "1–3 years": "1_3y",  # noqa: RUF001 (the prototype used an en dash)
    "1-3 years": "1_3y",
    "3–5 years": "3_5y",  # noqa: RUF001
    "3-5 years": "3_5y",
    "5+ years": "over_5y",
}
_RISK = {"conservative": "conservative", "balanced": "balanced", "aggressive": "aggressive"}


@dataclass
class ThesisVersion:
    summary: str
    key_risk: str
    bull_case: str
    bear_case: str
    fair_value: Decimal | None
    entry_price: Decimal | None
    conviction: str
    horizon: str
    created_at: datetime


@dataclass
class LegacyData:
    """The prototype's data, mapped to catalogue instrument ids."""

    watchlist: list[str] = field(default_factory=list)
    positions: list[tuple[str, Decimal]] = field(default_factory=list)
    alerts: list[tuple[str, str, Decimal]] = field(default_factory=list)
    theses: dict[str, list[ThesisVersion]] = field(default_factory=dict)
    research_notes: dict[str, str] = field(default_factory=dict)
    research_done: dict[str, list[int]] = field(default_factory=dict)
    preferences: dict[str, Any] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)

    def instrument(self, symbol: object, catalogue: dict[str, str]) -> str | None:
        """Map a prototype symbol to a catalogue id, remembering misses."""
        if not isinstance(symbol, str) or not symbol or len(symbol) > 20:
            return None
        found = LEGACY_SYMBOLS.get(symbol) or catalogue.get(symbol.upper())
        if found is None:
            self.skipped.add(symbol)
        return found


class LegacyFormatError(ValueError):
    """The upload is not data from the prototype."""


def _text(value: object, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _amount(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount <= 0 or amount >= Decimal("1e18"):
        return None
    return amount.quantize(Decimal("1e-10"))


def _when(value: object) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _thesis(raw: object) -> ThesisVersion | None:
    if not isinstance(raw, dict):
        return None
    version = ThesisVersion(
        summary=_text(raw.get("text"), 10000),
        key_risk=_text(raw.get("risk"), 5000),
        bull_case=_text(raw.get("bull"), 5000),
        bear_case=_text(raw.get("bear"), 5000),
        fair_value=_amount(raw.get("fairValue")),
        entry_price=_amount(raw.get("entry")),
        conviction=_CONVICTION.get(_text(raw.get("conviction"), 40).lower(), "not_assessed"),
        horizon=_HORIZON.get(_text(raw.get("horizon"), 40).lower(), "not_set"),
        created_at=_when(raw.get("savedAt")),
    )
    has_content = any(
        (
            version.summary,
            version.key_risk,
            version.bull_case,
            version.bear_case,
            version.fair_value,
            version.entry_price,
        )
    )
    return version if has_content else None


def _json(value: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def parse(payload: dict[str, Any], catalogue: dict[str, str]) -> LegacyData:
    """Accept the prototype's export file or its raw localStorage items.

    ``catalogue`` maps upper-case tickers to instrument ids, for symbols the
    prototype did not know about.
    """
    fmt = payload.get("format")
    if fmt == "openchart-v4-preview":
        export = payload
    elif fmt == "localstorage" and isinstance(payload.get("items"), dict):
        export = _from_local_storage(payload["items"])
    else:
        raise LegacyFormatError("This is not data saved by the OpenChart prototype")

    data = LegacyData()
    for symbol in _list(export.get("watchSymbols")):
        if (iid := data.instrument(symbol, catalogue)) and iid not in data.watchlist:
            data.watchlist.append(iid)
    for item in _list(export.get("positions")):
        if (
            isinstance(item, dict)
            and (iid := data.instrument(item.get("symbol"), catalogue))
            and (qty := _amount(item.get("qty"))) is not None
        ):
            data.positions.append((iid, qty))
    for item in _list(export.get("alerts")):
        if isinstance(item, dict) and (iid := data.instrument(item.get("symbol"), catalogue)):
            direction = item.get("direction")
            if direction in ("above", "below") and (price := _amount(item.get("price"))):
                data.alerts.append((iid, direction, price))

    theses = export.get("theses")
    for symbol, entry in theses.items() if isinstance(theses, dict) else []:
        if not isinstance(entry, dict) or not (iid := data.instrument(symbol, catalogue)):
            continue
        raw = [*_list(entry.get("history"))[-MAX_VERSIONS:], entry.get("latest")]
        versions: dict[datetime, ThesisVersion] = {}
        for item in raw:
            if version := _thesis(item):
                versions[version.created_at] = version
        if versions:
            data.theses[iid] = sorted(versions.values(), key=lambda v: v.created_at)

    research = export.get("research")
    for symbol, entry in research.items() if isinstance(research, dict) else []:
        if not isinstance(entry, dict) or not (iid := data.instrument(symbol, catalogue)):
            continue
        if notes := _text(entry.get("notes"), 50000):
            data.research_notes[iid] = notes
        done = [i for i in _list(entry.get("tasks")) if isinstance(i, int) and 0 <= i < 3]
        if done:
            data.research_done[iid] = sorted(set(done))

    prefs = export.get("preferences")
    if isinstance(prefs, dict):
        for source, target in (
            ("showGrid", "show_grid"),
            ("showOHLC", "show_ohlc"),
            ("compact", "compact"),
        ):
            if isinstance(prefs.get(source), bool):
                data.preferences[target] = prefs[source]
    if (risk := _RISK.get(_text(export.get("riskApproach"), 20).lower())) is not None:
        data.preferences["risk_profile"] = risk
    if export.get("chartType") in ("candle", "line"):
        data.preferences["chart_type"] = export["chartType"]
    if export.get("period") in ("1D", "1W", "1M", "3M", "1Y", "ALL"):
        data.preferences["period"] = export["period"]
    if (iid := data.instrument(export.get("symbol"), catalogue)) is not None:
        data.preferences["last_instrument"] = iid
    return data


def _list(value: object) -> list[Any]:
    return list(value[:MAX_LIST]) if isinstance(value, list) else []


def _bool(value: object) -> bool | None:
    return {"true": True, "false": False}.get(value) if isinstance(value, str) else None


def _from_local_storage(items: dict[str, Any]) -> dict[str, Any]:
    """Turn raw ``oc-*`` localStorage items into the export file's shape."""
    export: dict[str, Any] = {
        "watchSymbols": _json(items.get("oc-watch-symbols")),
        "positions": _json(items.get("oc-positions")),
        "alerts": _json(items.get("oc-alerts")),
        "riskApproach": items.get("oc-risk-profile"),
        "chartType": items.get("oc-type"),
        "period": items.get("oc-period"),
        "symbol": items.get("oc-symbol"),
        "preferences": {
            k: v
            for k, v in (
                ("showGrid", _bool(items.get("oc-grid"))),
                ("showOHLC", _bool(items.get("oc-ohlc"))),
                ("compact", _bool(items.get("oc-compact"))),
            )
            if v is not None
        },
        "theses": {},
        "research": {},
    }
    for key, value in list(items.items())[: MAX_LIST * 4]:
        if not isinstance(key, str):
            continue
        if key.startswith("oc-thesis-history-"):
            export["theses"].setdefault(key.removeprefix("oc-thesis-history-"), {})["history"] = (
                _json(value)
            )
        elif key.startswith("oc-thesis-"):
            export["theses"].setdefault(key.removeprefix("oc-thesis-"), {})["latest"] = _json(value)
        elif key.startswith("oc-research-notes-"):
            export["research"].setdefault(key.removeprefix("oc-research-notes-"), {})["notes"] = (
                value
            )
        elif key.startswith("oc-research-tasks-"):
            export["research"].setdefault(key.removeprefix("oc-research-tasks-"), {})["tasks"] = (
                _json(value)
            )
    return export
