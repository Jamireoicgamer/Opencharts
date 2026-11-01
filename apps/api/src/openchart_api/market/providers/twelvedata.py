# SPDX-License-Identifier: AGPL-3.0-or-later
"""Twelve Data: the first bring-your-own-key source (US stocks and ETFs, FX,
crypto). The key is stored sealed in the database and only used here.

LSE shares and indices need paid Twelve Data plans and use different symbol
rules, so they are left to other sources for now rather than guessed.

The free plan allows 8 requests a minute; requests wait for a free slot
rather than being refused by Twelve Data.
"""

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx2

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

REST = "https://api.twelvedata.com"
_INTERVAL: dict[Interval, str] = {"5m": "5min", "1h": "1h", "1d": "1day"}
_US = {"NASDAQ", "NYSE", "NYSEARCA"}


class RateLimiter:
    """At most ``limit`` calls per ``period`` seconds; callers wait their turn."""

    def __init__(self, limit: int, period: float = 60.0) -> None:
        self.limit, self.period = limit, period
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self.period:
                    self._calls.popleft()
                if len(self._calls) < self.limit:
                    self._calls.append(now)
                    return
                await asyncio.sleep(self.period - (now - self._calls[0]))


def _checked(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProviderError("unexpected response")
    if payload.get("status") == "error":
        # Messages can echo the request; keep them short and never log the key.
        raise ProviderError(f"Twelve Data error {payload.get('code')}")
    return payload


class TwelveData:
    name: ClassVar[str] = "twelvedata"
    label: ClassVar[str] = "Twelve Data"
    streams: ClassVar[bool] = False

    def __init__(
        self,
        api_key: str,
        client: httpx2.AsyncClient | None = None,
        per_minute: int = 8,
    ) -> None:
        self._key = api_key
        self._client = client or new_client()
        self._limiter = RateLimiter(per_minute)

    def supports(self, instrument: InstrumentRef) -> bool:
        return self.symbol(instrument) is not None

    @staticmethod
    def symbol(instrument: InstrumentRef) -> str | None:
        if instrument.exchange in _US:
            return instrument.symbol
        if instrument.exchange == "FX":
            return instrument.symbol  # already "GBP/USD"
        if instrument.exchange == "CRYPTO":
            return instrument.symbol.replace("-", "/")
        return None

    async def _get(
        self, path: str, instrument: InstrumentRef, params: dict[str, Any]
    ) -> dict[str, Any]:
        symbol = self.symbol(instrument)
        if symbol is None:
            raise ProviderError("not covered")
        await self._limiter.wait()
        return _checked(
            await get_json(
                self._client, f"{REST}/{path}", {"symbol": symbol, "apikey": self._key, **params}
            )
        )

    def _currency_ok(self, instrument: InstrumentRef, reported: Any) -> None:
        if isinstance(reported, str) and reported and reported.upper() != instrument.currency:
            raise ProviderError(f"currency mismatch: {reported} vs {instrument.currency}")

    async def quote(self, instrument: InstrumentRef) -> Quote:
        data = await self._get("quote", instrument, {})
        self._currency_ok(instrument, data.get("currency"))
        is_open = data.get("is_market_open")
        return Quote(
            instrument_id=instrument.id,
            price=amount(data.get("close")),
            previous_close=optional_amount(data.get("previous_close")),
            currency=instrument.currency,
            at=from_unix(data.get("timestamp")),
            source=self.name,
            # Twelve Data does not say how delayed a quote is on a given plan.
            delay="delayed",
            delay_minutes=None,
            market_state="open" if is_open is True else "closed" if is_open is False else "unknown",
        )

    async def history(
        self, instrument: InstrumentRef, interval: Interval, start: datetime, end: datetime
    ) -> list[Candle]:
        data = await self._get(
            "time_series",
            instrument,
            {
                "interval": _INTERVAL[interval],
                "start_date": start.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": end.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
                "timezone": "UTC",
                "outputsize": 5000,
                "order": "asc",
            },
        )
        meta = data.get("meta")
        if isinstance(meta, dict):
            self._currency_ok(instrument, meta.get("currency"))
        values = data.get("values")
        if not isinstance(values, list):
            raise ProviderError("unexpected time series")
        candles: dict[datetime, Candle] = {}
        for row in values:
            if not isinstance(row, dict):
                raise ProviderError("malformed candle")
            t = from_iso(row.get("datetime"))
            candles[t] = candle(
                t,
                row.get("open"),
                row.get("high"),
                row.get("low"),
                row.get("close"),
                row.get("volume"),
            )
        return [candles[t] for t in sorted(candles) if start <= t <= end]

    def stream(self, instruments: Sequence[InstrumentRef]) -> AsyncIterator[Quote]:
        raise NotImplementedError("Twelve Data is polled")

    async def aclose(self) -> None:
        await self._client.aclose()
