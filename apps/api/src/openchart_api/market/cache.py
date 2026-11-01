# SPDX-License-Identifier: AGPL-3.0-or-later
"""Price history, fetched from providers once and kept in Postgres.

``candle_ranges`` records which span of each series has been fetched. A
request only goes to a provider for what is missing: older history the
first time a longer period is opened, and the latest bars when the cached
ones are older than the series' refresh time.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from openchart_api.market.models import INTERVAL_SECONDS, Candle, InstrumentRef, Interval
from openchart_api.market.sources import Router
from openchart_api.tables import candle_ranges, candles

log = logging.getLogger(__name__)

Period = Literal["1D", "1W", "1M", "3M", "1Y", "ALL"]


@dataclass(frozen=True)
class PeriodSpec:
    interval: Interval
    lookback: timedelta
    weekly: bool = False  # aggregate daily bars into weeks for display
    last_day_only: bool = False


PERIODS: dict[Period, PeriodSpec] = {
    # Several days are fetched so a weekend or holiday still shows the last session.
    "1D": PeriodSpec("5m", timedelta(days=5), last_day_only=True),
    "1W": PeriodSpec("1h", timedelta(days=7)),
    "1M": PeriodSpec("1h", timedelta(days=31)),
    "3M": PeriodSpec("1d", timedelta(days=92)),
    "1Y": PeriodSpec("1d", timedelta(days=366)),
    "ALL": PeriodSpec("1d", timedelta(days=365 * 20), weekly=True),
}

# How old the newest fetch may be before the tail is fetched again.
REFRESH: dict[Interval, timedelta] = {
    "5m": timedelta(minutes=1),
    "1h": timedelta(minutes=5),
    "1d": timedelta(minutes=15),
}


_CHUNK = 1000


class NoSource(Exception):
    """No enabled provider covers this instrument."""


class SourcesFailed(Exception):
    """Every provider that covers the instrument failed."""


@dataclass(frozen=True)
class History:
    candles: list[Candle]
    interval: Interval
    sources: list[str]
    # True when providers failed and only cached bars could be returned.
    stale: bool = False


def weekly(daily: list[Candle]) -> list[Candle]:
    """Combine daily bars into weeks starting on Monday."""
    weeks: dict[datetime, list[Candle]] = defaultdict(list)
    for bar in daily:
        monday = (bar.t - timedelta(days=bar.t.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        weeks[monday].append(bar)
    result = []
    for start in sorted(weeks):
        bars = weeks[start]
        volumes = [b.volume for b in bars if b.volume is not None]
        result.append(
            Candle(
                t=start,
                open=bars[0].open,
                high=max(b.high for b in bars),
                low=min(b.low for b in bars),
                close=bars[-1].close,
                volume=sum(volumes, Decimal(0)) if volumes else None,
            )
        )
    return result


class CandleCache:
    def __init__(
        self,
        engine: AsyncEngine,
        router: Callable[[], Router],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._engine = engine
        self._router = router
        self._now = now
        self._locks: dict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)

    async def history(self, instrument: InstrumentRef, period: Period) -> History:
        spec = PERIODS[period]
        now = self._now()
        start = now - spec.lookback
        async with self._locks[(instrument.id, spec.interval)]:
            sources, stale = await self._fill(instrument, spec.interval, start, now)
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(candles)
                    .where(
                        candles.c.instrument_id == instrument.id,
                        candles.c.interval == spec.interval,
                        candles.c.t >= start,
                    )
                    .order_by(candles.c.t)
                )
            ).all()
        # Row has its own .t, so read the columns by name.
        bars = [
            Candle(m["t"], m["open"], m["high"], m["low"], m["close"], m["volume"])
            for m in (r._mapping for r in rows)
        ]
        used = sorted({r.source for r in rows})
        if spec.last_day_only and bars:
            cutoff = bars[-1].t - timedelta(hours=24)
            bars = [b for b in bars if b.t > cutoff]
        if spec.weekly:
            bars = weekly(bars)
        return History(bars, spec.interval, used or sources, stale)

    async def _fill(
        self, instrument: InstrumentRef, interval: Interval, start: datetime, now: datetime
    ) -> tuple[list[str], bool]:
        """Fetch what the cache lacks. Returns the sources used and whether it went stale."""
        async with self._engine.connect() as conn:
            covered = (
                await conn.execute(
                    select(candle_ranges).where(
                        candle_ranges.c.instrument_id == instrument.id,
                        candle_ranges.c.interval == interval,
                    )
                )
            ).one_or_none()
        step = timedelta(seconds=INTERVAL_SECONDS[interval])
        wanted: list[tuple[datetime, datetime]] = []
        if covered is None:
            wanted.append((start, now))
        else:
            if start < covered.covered_from:
                wanted.append((start, covered.covered_from))
            if now - covered.covered_to > REFRESH[interval]:
                # Fetch the last bar again: it was still forming.
                wanted.append((covered.covered_to - step, now))
        if not wanted:
            return [], False

        candidates = self._router().candidates(instrument)
        if not candidates:
            raise NoSource(instrument.id)
        used: list[str] = []
        for span_start, span_end in wanted:
            for provider in candidates:
                try:
                    bars = await provider.history(instrument, interval, span_start, span_end)
                except Exception as exc:  # any provider failure means "try the next"
                    log.info("%s history for %s failed: %s", provider.name, instrument.id, exc)
                    continue
                await self._store(instrument, interval, bars, provider.name, span_start, span_end)
                used.append(provider.name)
                break
            else:
                if covered is None:
                    raise SourcesFailed(instrument.id)
                return used, True
        return used, False

    async def _store(
        self,
        instrument: InstrumentRef,
        interval: Interval,
        bars: list[Candle],
        source: str,
        span_start: datetime,
        span_end: datetime,
    ) -> None:
        async with self._engine.begin() as conn:
            # Chunked: asyncpg allows at most 32767 parameters per statement.
            for first in range(0, len(bars), _CHUNK):
                stmt = insert(candles).values(
                    [
                        {
                            "instrument_id": instrument.id,
                            "interval": interval,
                            "t": b.t,
                            "open": b.open,
                            "high": b.high,
                            "low": b.low,
                            "close": b.close,
                            "volume": b.volume,
                            "source": source,
                        }
                        for b in bars[first : first + _CHUNK]
                    ]
                )
                await conn.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[candles.c.instrument_id, candles.c.interval, candles.c.t],
                        set_={
                            k: stmt.excluded[k]
                            for k in ("open", "high", "low", "close", "volume", "source")
                        }
                        | {"fetched_at": func.now()},
                    )
                )
            stmt = insert(candle_ranges).values(
                instrument_id=instrument.id,
                interval=interval,
                covered_from=span_start,
                covered_to=span_end,
            )
            await conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=[candle_ranges.c.instrument_id, candle_ranges.c.interval],
                    set_={
                        "covered_from": func.least(candle_ranges.c.covered_from, span_start),
                        "covered_to": func.greatest(candle_ranges.c.covered_to, span_end),
                    },
                )
            )
