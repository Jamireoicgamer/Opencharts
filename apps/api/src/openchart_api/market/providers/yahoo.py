# SPDX-License-Identifier: AGPL-3.0-or-later
"""Yahoo Finance chart data: keyless, delayed stocks, ETFs, indices and FX.

This is an unofficial endpoint (``/v8/finance/chart``). Yahoo's terms allow
personal, non-commercial use only and the endpoint can change without
notice, so it is **off until the server owner accepts those terms** in
Settings, and it is never used to redistribute data.

Quotes are labelled "delayed" with the time Yahoo priced them; Yahoo's chart
data does not state the exact delay, so none is claimed.

LSE prices: Yahoo reports most LSE shares in pence ("GBp"), like our
catalogue (GBX). If Yahoo and the catalogue disagree between pence and
pounds the value is converted; any other currency mismatch is refused.
"""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar

import httpx2

from openchart_api.market.models import Candle, InstrumentRef, Interval, MarketState, Quote
from openchart_api.market.providers.base import (
    ProviderError,
    amount,
    candle,
    from_unix,
    get_json,
    new_client,
    optional_amount,
)

REST = "https://query1.finance.yahoo.com/v8/finance/chart"
_INTERVAL: dict[Interval, str] = {"5m": "5m", "1h": "60m", "1d": "1d"}
# Yahoo keeps intraday history only for a while.
_MAX_AGE: dict[Interval, timedelta] = {
    "5m": timedelta(days=59),
    "1h": timedelta(days=729),
    "1d": timedelta(days=365 * 40),
}
_INDEX = {"UKX": "^FTSE", "SPX": "^GSPC", "NDX": "^NDX", "DJI": "^DJI"}
_EQUITY_EXCHANGES = {"NASDAQ", "NYSE", "NYSEARCA"}


def _currency(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ProviderError("missing currency")
    return "GBX" if raw in ("GBp", "GBX") else raw.upper()


def _scale(source: str, wanted: str) -> Decimal:
    """Multiplier from the source currency to the catalogue's."""
    if source == wanted:
        return Decimal(1)
    if (source, wanted) == ("GBP", "GBX"):
        return Decimal(100)
    if (source, wanted) == ("GBX", "GBP"):
        return Decimal("0.01")
    raise ProviderError(f"currency mismatch: {source} vs {wanted}")


def _chart(payload: Any) -> dict[str, Any]:
    chart = payload.get("chart") if isinstance(payload, dict) else None
    if not isinstance(chart, dict):
        raise ProviderError("unexpected response")
    if chart.get("error"):
        raise ProviderError(f"Yahoo error: {str(chart['error'])[:200]}")
    results = chart.get("result")
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        raise ProviderError("unexpected response")
    result: dict[str, Any] = results[0]
    if not isinstance(result.get("meta"), dict):
        raise ProviderError("missing meta")
    return result


def _market_state(meta: dict[str, Any], now: datetime) -> MarketState:
    period = meta.get("currentTradingPeriod")
    regular = period.get("regular") if isinstance(period, dict) else None
    if not isinstance(regular, dict):
        return "unknown"
    try:
        start, end = from_unix(regular.get("start")), from_unix(regular.get("end"))
    except ProviderError:
        return "unknown"
    return "open" if start <= now < end else "closed"


class Yahoo:
    name: ClassVar[str] = "yahoo"
    label: ClassVar[str] = "Yahoo Finance"
    streams: ClassVar[bool] = False

    def __init__(self, client: httpx2.AsyncClient | None = None) -> None:
        self._client = client or new_client()

    def supports(self, instrument: InstrumentRef) -> bool:
        return self.symbol(instrument) is not None

    @staticmethod
    def symbol(instrument: InstrumentRef) -> str | None:
        s, exchange = instrument.symbol, instrument.exchange
        if exchange == "LSE":
            return s.rstrip(".").replace(".", "-") + ".L"
        if exchange in _EQUITY_EXCHANGES:
            return s.replace(".", "-")
        if exchange == "INDEX":
            return _INDEX.get(s)
        if exchange == "FX":
            return s.replace("/", "") + "=X"
        if exchange == "CRYPTO":
            return s
        return None

    async def _fetch(self, instrument: InstrumentRef, params: dict[str, Any]) -> dict[str, Any]:
        symbol = self.symbol(instrument)
        if symbol is None:
            raise ProviderError("not covered")
        payload = await get_json(self._client, f"{REST}/{symbol}", params)
        return _chart(payload)

    async def quote(self, instrument: InstrumentRef) -> Quote:
        result = await self._fetch(instrument, {"range": "1d", "interval": "1d"})
        meta = result["meta"]
        scale = _scale(_currency(meta.get("currency")), instrument.currency)
        previous = optional_amount(meta.get("previousClose") or meta.get("chartPreviousClose"))
        now = datetime.now(UTC)
        return Quote(
            instrument_id=instrument.id,
            price=amount(meta.get("regularMarketPrice")) * scale,
            previous_close=None if previous is None else previous * scale,
            currency=instrument.currency,
            at=from_unix(meta.get("regularMarketTime")),
            source=self.name,
            delay="delayed",
            delay_minutes=None,
            market_state=_market_state(meta, now),
        )

    async def history(
        self, instrument: InstrumentRef, interval: Interval, start: datetime, end: datetime
    ) -> list[Candle]:
        start = max(start, datetime.now(UTC) - _MAX_AGE[interval])
        if start >= end:
            return []
        result = await self._fetch(
            instrument,
            {
                "period1": int(start.timestamp()),
                "period2": int(end.timestamp()),
                "interval": _INTERVAL[interval],
                "includePrePost": "false",
            },
        )
        meta = result["meta"]
        scale = _scale(_currency(meta.get("currency")), instrument.currency)
        offset = meta.get("gmtoffset") if isinstance(meta.get("gmtoffset"), int) else 0
        stamps = result.get("timestamp") or []
        indicators = result.get("indicators")
        quotes = indicators.get("quote") if isinstance(indicators, dict) else None
        if not isinstance(stamps, list) or not isinstance(quotes, list) or len(quotes) != 1:
            raise ProviderError("unexpected chart data")
        series = quotes[0]
        columns = [series.get(k) for k in ("open", "high", "low", "close", "volume")]
        if not all(isinstance(c, list) and len(c) == len(stamps) for c in columns):
            raise ProviderError("unexpected chart data")
        candles: dict[datetime, Candle] = {}
        for i, stamp in enumerate(stamps):
            o, h, low, c, v = (col[i] for col in columns)
            if None in (o, h, low, c):
                continue  # Yahoo leaves gaps for bars with no trades
            t = from_unix(stamp)
            if interval == "1d":
                # Daily bars are keyed by the exchange's calendar date.
                local = t + timedelta(seconds=offset)
                t = datetime(local.year, local.month, local.day, tzinfo=UTC)
            bar = candle(t, o, h, low, c, v)
            candles[t] = Candle(
                t=t,
                open=bar.open * scale,
                high=bar.high * scale,
                low=bar.low * scale,
                close=bar.close * scale,
                volume=bar.volume,
            )
        return [candles[t] for t in sorted(candles)]

    def stream(self, instruments: Sequence[InstrumentRef]) -> AsyncIterator[Quote]:
        raise NotImplementedError("Yahoo is polled")

    async def aclose(self) -> None:
        await self._client.aclose()
