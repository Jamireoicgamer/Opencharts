# SPDX-License-Identifier: AGPL-3.0-or-later
"""The market-data hub and candle cache, with fake providers and the real
database (instrument catalogue, candle cache, alert functions)."""

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

import httpx2
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from openchart_api.market.cache import CandleCache, NoSource, SourcesFailed, weekly
from openchart_api.market.hub import AlertFired, FeedStatus, Hub, Watcher
from openchart_api.market.models import Candle, InstrumentRef, Interval, Quote
from openchart_api.market.providers.base import ProviderError
from openchart_api.market.sources import Router, SourceConfig
from openchart_api.tables import alerts

from .conftest import Invite

pytestmark = pytest.mark.anyio

BTC = "CRYPTO:BTC-USD"
BAE = "LSE:BA."


class FakeProvider:
    name: ClassVar[str] = "fake"
    label: ClassVar[str] = "Fake"
    streams: ClassVar[bool] = False

    def __init__(
        self,
        name: str = "fake",
        *,
        crypto_only: bool = True,
        fail: bool = False,
        price: str = "100",
    ) -> None:
        self.name = name  # type: ignore[misc]
        self.crypto_only = crypto_only
        self.fail = fail
        self.price = Decimal(price)
        self.quote_calls = 0
        self.history_calls: list[tuple[str, datetime, datetime]] = []

    def supports(self, instrument: InstrumentRef) -> bool:
        return instrument.asset_class == "crypto" or not self.crypto_only

    async def quote(self, instrument: InstrumentRef) -> Quote:
        self.quote_calls += 1
        if self.fail:
            raise ProviderError("down")
        return Quote(
            instrument.id,
            self.price,
            Decimal("90"),
            instrument.currency,
            datetime.now(UTC),
            self.name,
            "realtime",
            0,
        )

    async def history(
        self, instrument: InstrumentRef, interval: Interval, start: datetime, end: datetime
    ) -> list[Candle]:
        self.history_calls.append((interval, start, end))
        if self.fail:
            raise ProviderError("down")
        step = {"5m": timedelta(minutes=5), "1h": timedelta(hours=1), "1d": timedelta(days=1)}[
            interval
        ]
        t = start.replace(minute=0, second=0, microsecond=0)
        if interval == "1d":
            t = t.replace(hour=0)
        bars = []
        while t <= end:
            if t >= start:
                bars.append(Candle(t, Decimal(1), Decimal(2), Decimal("0.5"), Decimal(1), None))
            t += step
        return bars

    def stream(self, instruments: Sequence[InstrumentRef]) -> AsyncIterator[Quote]:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


def make_hub(engine: AsyncEngine, *providers: FakeProvider) -> Hub:
    by_name = {p.name: p for p in providers}

    async def load(engine: AsyncEngine, key: bytes) -> list[SourceConfig]:
        return [SourceConfig(p.name, i, True, None) for i, p in enumerate(providers)]

    return Hub(
        engine,
        b"k" * 32,
        load=load,
        factory=lambda c: by_name[c.provider],
        poll_seconds={p.name: 0.01 for p in providers},
        linger_seconds=0.05,
        retry_delay=lambda failures: 0.01,
    )


async def next_event(watcher: Watcher, kind: type, timeout: float = 2.0) -> object:
    async def wait() -> object:
        while True:
            event = await watcher.queue.get()
            if isinstance(event, kind):
                return event

    return await asyncio.wait_for(wait(), timeout)


@pytest.fixture
async def hub_engine(db: object, app_engine: AsyncEngine) -> AsyncEngine:
    return app_engine


async def test_watching_starts_a_feed_and_leaving_stops_it(hub_engine: AsyncEngine) -> None:
    provider = FakeProvider()
    hub = make_hub(hub_engine, provider)
    await hub.reload_sources()
    first = hub.connect(UUID(int=1))
    assert await hub.watch(first, [BTC, "NOPE:XYZ"]) == [BTC]
    quote = await next_event(first, Quote)
    assert isinstance(quote, Quote) and quote.price == Decimal("100")
    assert hub.status[BTC] == FeedStatus(BTC, "live", "fake")

    # A second watcher gets the latest quote straight away.
    second = hub.connect(UUID(int=2))
    await hub.watch(second, [BTC])
    assert isinstance(second.queue.get_nowait(), FeedStatus)
    assert isinstance(second.queue.get_nowait(), Quote)

    hub.disconnect(first)
    hub.unwatch(second, [BTC])
    await asyncio.sleep(0.15)
    calls = provider.quote_calls
    await asyncio.sleep(0.05)
    assert provider.quote_calls == calls  # stopped polling
    await hub.stop()


async def test_failover_to_the_next_source(hub_engine: AsyncEngine) -> None:
    broken, backup = FakeProvider("broken", fail=True), FakeProvider("backup", price="101")
    hub = make_hub(hub_engine, broken, backup)
    await hub.reload_sources()
    watcher = hub.connect(UUID(int=1))
    await hub.watch(watcher, [BTC])
    quote = await next_event(watcher, Quote)
    assert isinstance(quote, Quote) and quote.source == "backup"
    assert broken.quote_calls == 2  # two failures, then moved on
    await hub.stop()


async def test_uncovered_instruments_say_so(hub_engine: AsyncEngine) -> None:
    hub = make_hub(hub_engine, FakeProvider())  # crypto only
    await hub.reload_sources()
    watcher = hub.connect(UUID(int=1))
    await hub.watch(watcher, [BAE])
    status = await next_event(watcher, FeedStatus)
    assert status == FeedStatus(BAE, "no_source", None)
    await hub.stop()


async def test_alerts_fire_once_for_their_owner_only(
    hub_engine: AsyncEngine, owner: httpx2.AsyncClient, invite_user: Invite
) -> None:
    member = await invite_user("member@example.com")
    above = (
        await owner.post(
            "/api/alerts", json={"instrument_id": BTC, "direction": "above", "price": "70000"}
        )
    ).json()
    below = (
        await owner.post(
            "/api/alerts", json={"instrument_id": BTC, "direction": "below", "price": "60000"}
        )
    ).json()
    theirs = (
        await member.post(
            "/api/alerts", json={"instrument_id": BTC, "direction": "above", "price": "69000"}
        )
    ).json()
    owner_id = UUID((await owner.get("/api/auth/me")).json()["id"])
    member_id = UUID((await member.get("/api/auth/me")).json()["id"])

    provider = FakeProvider(price="70500")
    hub = make_hub(hub_engine, provider)
    await hub.reload_sources()
    await hub.refresh_alerts()
    # Watched for the alerts even though no browser is open.
    assert hub.watched(BTC)
    owner_socket, member_socket = hub.connect(owner_id), hub.connect(member_id)

    fired = await next_event(owner_socket, AlertFired)
    assert isinstance(fired, AlertFired)
    assert str(fired.alert_id) == above["id"] and fired.price == Decimal("70500")
    theirs_fired = await next_event(member_socket, AlertFired)
    assert isinstance(theirs_fired, AlertFired) and str(theirs_fired.alert_id) == theirs["id"]
    assert owner_socket.queue.empty()  # the owner never sees the member's alert

    listed = {a["id"]: a for a in (await owner.get("/api/alerts")).json()}
    assert listed[above["id"]]["triggered_at"] is not None
    assert listed[above["id"]]["active"] is False
    assert listed[below["id"]]["triggered_at"] is None

    # It fires once: later quotes don't fire it again.
    await asyncio.sleep(1.2)
    assert owner_socket.queue.empty()

    # Re-arming clears the trigger, so it can fire again.
    rearmed = await owner.patch(f"/api/alerts/{above['id']}", json={"active": True})
    assert rearmed.json()["triggered_at"] is None
    await hub.stop()


async def test_the_alert_function_is_the_only_way_in(
    hub_engine: AsyncEngine, owner: httpx2.AsyncClient
) -> None:
    await owner.post("/api/alerts", json={"instrument_id": BTC, "direction": "above", "price": "1"})
    async with hub_engine.begin() as conn:
        # Without a user, RLS hides every alert from the app role...
        assert (await conn.execute(select(alerts))).all() == []
        # ...and the narrow functions expose only instrument ids.
        assert list(await conn.scalars(text("SELECT market_alert_instruments()"))) == [BTC]


# Candle cache ------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def make_cache(
    engine: AsyncEngine, *providers: FakeProvider
) -> tuple[CandleCache, Clock, Callable[[], Router]]:
    clock = Clock()
    router = Router(list(providers))
    return CandleCache(engine, lambda: router, now=clock), clock, lambda: router


async def btc(engine: AsyncEngine) -> InstrumentRef:
    hub = make_hub(engine)
    ref = await hub.instrument(BTC)
    assert ref is not None
    return ref


async def test_history_is_fetched_once_then_only_what_is_missing(
    hub_engine: AsyncEngine,
) -> None:
    provider = FakeProvider()
    cache, clock, _ = make_cache(hub_engine, provider)
    ref = await btc(hub_engine)

    first = await cache.history(ref, "3M")
    assert len(provider.history_calls) == 1
    assert first.interval == "1d" and first.sources == ["fake"] and len(first.candles) >= 90

    # Within the refresh time: straight from the cache.
    await cache.history(ref, "3M")
    assert len(provider.history_calls) == 1

    # Later: only the tail, starting from the last (still forming) bar.
    clock.now += timedelta(hours=1)
    await cache.history(ref, "3M")
    interval, start, end = provider.history_calls[-1]
    assert (interval, end) == ("1d", clock.now)
    assert start == clock.now - timedelta(hours=1) - timedelta(days=1)

    # A longer period: only the older part is fetched.
    await cache.history(ref, "1Y")
    _, start, end = provider.history_calls[-1]
    assert end == clock.now - timedelta(days=92) - timedelta(hours=1)
    assert start == clock.now - timedelta(days=366)


async def test_history_falls_back_and_reports_staleness(hub_engine: AsyncEngine) -> None:
    broken, backup = FakeProvider("broken", fail=True), FakeProvider("backup")
    cache, clock, _ = make_cache(hub_engine, broken, backup)
    ref = await btc(hub_engine)
    result = await cache.history(ref, "1W")
    assert result.sources == ["backup"] and not result.stale

    backup.fail = True
    clock.now += timedelta(hours=2)
    stale = await cache.history(ref, "1W")
    assert stale.stale and stale.candles  # cached bars, labelled stale

    uncached, _, _ = make_cache(hub_engine, FakeProvider("x", fail=True))
    with pytest.raises(SourcesFailed):
        await uncached.history(ref, "1D")
    nobody, _, _ = make_cache(hub_engine)
    with pytest.raises(NoSource):
        await nobody.history(ref, "1D")


async def test_one_day_shows_the_last_session_and_all_shows_weeks(
    hub_engine: AsyncEngine,
) -> None:
    cache, _, _ = make_cache(hub_engine, FakeProvider())
    ref = await btc(hub_engine)
    day = await cache.history(ref, "1D")
    assert day.interval == "5m"
    assert day.candles[-1].t - day.candles[0].t < timedelta(hours=24)

    every = await cache.history(ref, "ALL")
    assert all(c.t.weekday() == 0 for c in every.candles)


def test_weekly_bars_combine_days() -> None:
    days = [
        Candle(
            datetime(2026, 10, 26 + i, tzinfo=UTC),
            Decimal(o),
            Decimal(h),
            Decimal(lo),
            Decimal(c),
            Decimal(1),
        )
        for i, (o, h, lo, c) in enumerate([(10, 12, 9, 11), (11, 15, 10, 14), (14, 14, 8, 9)])
    ]
    (week,) = weekly(days)
    assert [week.open, week.high, week.low, week.close, week.volume] == [10, 15, 8, 9, 3]
    assert week.t == datetime(2026, 10, 26, tzinfo=UTC)
