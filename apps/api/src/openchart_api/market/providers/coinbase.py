# SPDX-License-Identifier: AGPL-3.0-or-later
"""Coinbase Exchange public market data: keyless, real-time crypto.

REST: ``/products/{id}/ticker``, ``/products/{id}/stats``, ``/products/{id}/candles``.
WebSocket: the ``ticker`` channel of ``wss://ws-feed.exchange.coinbase.com``.
Terms: Coinbase's public market data endpoints need no account; data is for
the user's own use.
"""

import json
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import datetime, timedelta
from typing import Any, ClassVar

import httpx2
from websockets.asyncio.client import connect

from openchart_api.market.models import Candle, InstrumentRef, Interval, Quote
from openchart_api.market.providers.base import (
    ProviderError,
    amount,
    candle,
    from_iso,
    from_unix,
    get_json,
    new_client,
    optional_amount,
)

REST = "https://api.exchange.coinbase.com"
WS = "wss://ws-feed.exchange.coinbase.com"
_MAX_CANDLES = 300  # per request
_GRANULARITY: dict[Interval, int] = {"5m": 300, "1h": 3600, "1d": 86400}


class Coinbase:
    name: ClassVar[str] = "coinbase"
    label: ClassVar[str] = "Coinbase"
    streams: ClassVar[bool] = True

    def __init__(
        self,
        client: httpx2.AsyncClient | None = None,
        connector: Callable[[str], Any] | None = None,
    ) -> None:
        self._client = client or new_client()
        self._connect = connector or (lambda url: connect(url, open_timeout=10, max_size=2**20))

    def supports(self, instrument: InstrumentRef) -> bool:
        return instrument.asset_class == "crypto" and instrument.exchange == "CRYPTO"

    @staticmethod
    def product(instrument: InstrumentRef) -> str:
        return instrument.symbol  # BTC-USD is already Coinbase's product id

    async def quote(self, instrument: InstrumentRef) -> Quote:
        product = self.product(instrument)
        ticker = await get_json(self._client, f"{REST}/products/{product}/ticker", {})
        stats = await get_json(self._client, f"{REST}/products/{product}/stats", {})
        if not isinstance(ticker, dict) or not isinstance(stats, dict):
            raise ProviderError("unexpected response")
        return Quote(
            instrument_id=instrument.id,
            price=amount(ticker.get("price")),
            previous_close=optional_amount(stats.get("open")),
            currency=instrument.currency,
            at=from_iso(ticker.get("time")),
            source=self.name,
            delay="realtime",
            delay_minutes=0,
            market_state="open",
        )

    async def history(
        self, instrument: InstrumentRef, interval: Interval, start: datetime, end: datetime
    ) -> list[Candle]:
        granularity = _GRANULARITY[interval]
        step = timedelta(seconds=granularity * _MAX_CANDLES)
        found: dict[datetime, Candle] = {}
        window_start = start
        while window_start < end:
            window_end = min(window_start + step, end)
            rows = await get_json(
                self._client,
                f"{REST}/products/{self.product(instrument)}/candles",
                {
                    "granularity": granularity,
                    "start": window_start.isoformat(),
                    "end": window_end.isoformat(),
                },
            )
            if not isinstance(rows, list):
                raise ProviderError("unexpected candles response")
            for row in rows:
                # [time, low, high, open, close, volume], newest first
                if not isinstance(row, list) or len(row) < 6:
                    raise ProviderError("malformed candle")
                t = from_unix(row[0])
                found[t] = candle(t, row[3], row[2], row[1], row[4], row[5])
            window_start = window_end
        return [found[t] for t in sorted(found) if start <= t <= end]

    async def stream(self, instruments: Sequence[InstrumentRef]) -> AsyncIterator[Quote]:
        by_product = {self.product(i): i for i in instruments}
        async with self._connect(WS) as ws:
            await ws.send(
                json.dumps(
                    {"type": "subscribe", "product_ids": list(by_product), "channels": ["ticker"]}
                )
            )
            async for raw in ws:
                message = json.loads(raw)
                if not isinstance(message, dict):
                    continue
                kind = message.get("type")
                if kind == "error":
                    raise ProviderError(f"stream error: {str(message.get('message'))[:200]}")
                if kind != "ticker":
                    continue
                instrument = by_product.get(message.get("product_id"))  # type: ignore[arg-type]
                if instrument is None:
                    continue
                try:
                    yield Quote(
                        instrument_id=instrument.id,
                        price=amount(message.get("price")),
                        previous_close=optional_amount(message.get("open_24h")),
                        currency=instrument.currency,
                        at=from_iso(message.get("time")),
                        source=self.name,
                        delay="realtime",
                        delay_minutes=0,
                        market_state="open",
                    )
                except ProviderError:
                    continue  # skip one bad message, keep the stream

    async def aclose(self) -> None:
        await self._client.aclose()
