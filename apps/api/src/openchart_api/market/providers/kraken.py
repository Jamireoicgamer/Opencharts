# SPDX-License-Identifier: AGPL-3.0-or-later
"""Kraken public market data: keyless crypto, used as the fallback for
Coinbase. Polled over REST (``/0/public/Ticker`` and ``/0/public/OHLC``).

Kraken returns at most the latest 720 bars per interval, so long histories
come from Coinbase when it is available.
"""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx2

from openchart_api.market.models import Candle, InstrumentRef, Interval, Quote
from openchart_api.market.providers.base import (
    ProviderError,
    amount,
    candle,
    from_unix,
    get_json,
    new_client,
    optional_amount,
)

REST = "https://api.kraken.com/0/public"
_INTERVAL: dict[Interval, int] = {"5m": 5, "1h": 60, "1d": 1440}
# Kraken's own names for a few assets.
_ASSET = {"BTC": "XBT", "DOGE": "XDG"}


def _result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProviderError("unexpected response")
    errors = payload.get("error")
    if errors:
        raise ProviderError(f"Kraken error: {str(errors)[:200]}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ProviderError("unexpected response")
    return result


def _only_pair(result: dict[str, Any]) -> Any:
    pairs = [v for k, v in result.items() if k != "last"]
    if len(pairs) != 1:
        raise ProviderError("unexpected pair data")
    return pairs[0]


class Kraken:
    name: ClassVar[str] = "kraken"
    label: ClassVar[str] = "Kraken"
    streams: ClassVar[bool] = False

    def __init__(self, client: httpx2.AsyncClient | None = None) -> None:
        self._client = client or new_client()

    def supports(self, instrument: InstrumentRef) -> bool:
        return instrument.asset_class == "crypto" and instrument.exchange == "CRYPTO"

    @staticmethod
    def pair(instrument: InstrumentRef) -> str:
        base, _, quote = instrument.symbol.partition("-")
        return f"{_ASSET.get(base, base)}{quote}"

    async def quote(self, instrument: InstrumentRef) -> Quote:
        result = _result(
            await get_json(self._client, f"{REST}/Ticker", {"pair": self.pair(instrument)})
        )
        ticker = _only_pair(result)
        if not isinstance(ticker, dict) or not isinstance(ticker.get("c"), list) or not ticker["c"]:
            raise ProviderError("unexpected ticker")
        return Quote(
            instrument_id=instrument.id,
            price=amount(ticker["c"][0]),
            # Kraken's "o" is today's opening price (UTC midnight).
            previous_close=optional_amount(ticker.get("o")),
            currency=instrument.currency,
            # Kraken's ticker has no timestamp: this is when it was fetched.
            at=datetime.now(UTC),
            source=self.name,
            delay="realtime",
            delay_minutes=0,
            market_state="open",
        )

    async def history(
        self, instrument: InstrumentRef, interval: Interval, start: datetime, end: datetime
    ) -> list[Candle]:
        result = _result(
            await get_json(
                self._client,
                f"{REST}/OHLC",
                {
                    "pair": self.pair(instrument),
                    "interval": _INTERVAL[interval],
                    "since": int(start.timestamp()) - 1,
                },
            )
        )
        rows = _only_pair(result)
        if not isinstance(rows, list):
            raise ProviderError("unexpected OHLC data")
        candles = []
        for row in rows:
            # [time, open, high, low, close, vwap, volume, count]
            if not isinstance(row, list) or len(row) < 7:
                raise ProviderError("malformed candle")
            t = from_unix(row[0])
            if start <= t <= end:
                candles.append(candle(t, row[1], row[2], row[3], row[4], row[6]))
        return candles

    def stream(self, instruments: Sequence[InstrumentRef]) -> AsyncIterator[Quote]:
        raise NotImplementedError("Kraken is polled")

    async def aclose(self) -> None:
        await self._client.aclose()
