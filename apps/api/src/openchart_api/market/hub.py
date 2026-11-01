# SPDX-License-Identifier: AGPL-3.0-or-later
"""The market-data hub: one place that knows what is being watched.

* Browsers connect over a WebSocket and say which instruments they watch.
  Instruments with armed price alerts are watched by the hub itself, so
  alerts fire even when nobody has the app open.
* For each watched instrument one *feed* runs: it streams from a provider
  that can stream, or polls one that can't, and fails over to the next
  enabled provider when one keeps failing.
* Every quote goes to the instrument's watchers and is checked against
  alerts. Feeds stop shortly after the last watcher leaves.

Everything runs in the API process (no Redis or worker yet; see PLAN.md).
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from openchart_api.market.cache import CandleCache
from openchart_api.market.models import InstrumentRef, Quote
from openchart_api.market.providers.base import MarketDataProvider
from openchart_api.market.sources import Router, SourceConfig, build, load_config
from openchart_api.tables import instruments

log = logging.getLogger(__name__)

FeedState = Literal["connecting", "live", "no_source", "error"]

MAX_WATCH_PER_CONNECTION = 100
# Seconds between polls, per provider. Delayed sources gain nothing from
# being asked more often, and their public endpoints rate-limit.
POLL_SECONDS: dict[str, float] = {"kraken": 10, "yahoo": 60, "twelvedata": 60}
DEFAULT_POLL_SECONDS = 30.0
# A feed with no watchers lingers this long, so page reloads don't reconnect.
LINGER_SECONDS = 15.0
ALERT_REFRESH_SECONDS = 30.0
# Alerts are checked at most this often per instrument (streams tick fast).
ALERT_CHECK_SECONDS = 1.0
FAILURES_BEFORE_FAILOVER = 2


@dataclass(frozen=True)
class FeedStatus:
    instrument_id: str
    state: FeedState
    source: str | None = None


@dataclass(frozen=True)
class AlertFired:
    alert_id: UUID
    user_id: UUID
    instrument_id: str
    direction: str
    level: Decimal
    price: Decimal
    currency: str
    note: str
    at: datetime


Event = Quote | FeedStatus | AlertFired


@dataclass(eq=False)
class Watcher:
    """One browser connection."""

    user_id: UUID
    queue: asyncio.Queue[Event] = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    ids: set[str] = field(default_factory=set)

    def send(self, event: Event) -> None:
        if self.queue.full():
            # A slow client loses the oldest update, never blocks the hub.
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
        self.queue.put_nowait(event)


class Hub:
    def __init__(
        self,
        engine: AsyncEngine,
        master_key: bytes,
        *,
        load: Callable[[AsyncEngine, bytes], Any] = load_config,
        factory: Callable[[SourceConfig], MarketDataProvider | None] = build,
        poll_seconds: dict[str, float] | None = None,
        linger_seconds: float = LINGER_SECONDS,
        retry_delay: Callable[[int], float] = lambda failures: min(60.0, 2.0**failures),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._engine = engine
        self._master_key = master_key
        self._load = load
        self._factory = factory
        self._poll = {**POLL_SECONDS, **(poll_seconds or {})}
        self._linger = linger_seconds
        self._retry_delay = retry_delay
        self._clock = clock
        self.router = Router([])
        self.cache = CandleCache(engine, lambda: self.router)
        self.last: dict[str, Quote] = {}
        self.status: dict[str, FeedStatus] = {}
        self._refs: dict[str, InstrumentRef] = {}
        self._watchers: set[Watcher] = set()
        self._alert_ids: set[str] = set()
        self._feeds: dict[str, asyncio.Task[None]] = {}
        self._stopping: dict[str, asyncio.TimerHandle] = {}
        self._alert_checked: dict[str, float] = {}
        self._alerts_changed = asyncio.Event()
        self._background: list[asyncio.Task[None]] = []
        self._providers: list[MarketDataProvider] = []

    # Lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        await self.reload_sources()
        self._background.append(asyncio.create_task(self._watch_alerts(), name="alerts"))

    async def stop(self) -> None:
        for task in [*self._background, *self._feeds.values()]:
            task.cancel()
        for task in [*self._background, *self._feeds.values()]:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._feeds.clear()
        await self._close(self._providers)

    async def reload_sources(self, configs: list[SourceConfig] | None = None) -> None:
        """Apply data-source settings (read from the database unless given)
        and restart feeds on the new providers."""
        if configs is None:
            try:
                configs = await self._load(self._engine, self._master_key)
            except Exception:
                log.exception("Could not load data-source settings")
                configs = []
        old = self._providers
        self._providers = [p for c in configs if (p := self._factory(c)) is not None]
        self.router = Router(self._providers, clock=self._clock)
        for instrument_id in list(self._feeds):
            self._restart(instrument_id)
        await self._close(old)

    @staticmethod
    async def _close(providers: Iterable[MarketDataProvider]) -> None:
        for provider in providers:
            with contextlib.suppress(Exception):
                await provider.aclose()

    # Instruments -------------------------------------------------------------

    async def instrument(self, instrument_id: str) -> InstrumentRef | None:
        if instrument_id not in self._refs:
            async with self._engine.connect() as conn:
                row = (
                    await conn.execute(select(instruments).where(instruments.c.id == instrument_id))
                ).one_or_none()
            if row is None:
                return None
            self._refs[instrument_id] = InstrumentRef(
                row.id, row.symbol, row.exchange, row.currency, row.asset_class
            )
        return self._refs[instrument_id]

    def covered(self, instrument: InstrumentRef) -> bool:
        return bool(self.router.candidates(instrument))

    # Watchers ---------------------------------------------------------------

    def connect(self, user_id: UUID) -> Watcher:
        watcher = Watcher(user_id)
        self._watchers.add(watcher)
        return watcher

    def disconnect(self, watcher: Watcher) -> None:
        self._watchers.discard(watcher)
        ids, watcher.ids = watcher.ids, set()
        for instrument_id in ids:
            self._maybe_stop(instrument_id)

    async def watch(self, watcher: Watcher, ids: Iterable[str]) -> list[str]:
        """Start sending these instruments' quotes. Returns the ids accepted."""
        accepted = []
        for instrument_id in ids:
            if len(watcher.ids) >= MAX_WATCH_PER_CONNECTION:
                break
            if await self.instrument(instrument_id) is None:
                continue
            watcher.ids.add(instrument_id)
            accepted.append(instrument_id)
            self._ensure_feed(instrument_id)
            # Send what we already know straight away.
            if status := self.status.get(instrument_id):
                watcher.send(status)
            if quote := self.last.get(instrument_id):
                watcher.send(quote)
        return accepted

    def unwatch(self, watcher: Watcher, ids: Iterable[str]) -> None:
        for instrument_id in ids:
            watcher.ids.discard(instrument_id)
            self._maybe_stop(instrument_id)

    def watched(self, instrument_id: str) -> bool:
        return instrument_id in self._alert_ids or any(
            instrument_id in w.ids for w in self._watchers
        )

    # Feeds ------------------------------------------------------------------

    def _ensure_feed(self, instrument_id: str) -> None:
        if handle := self._stopping.pop(instrument_id, None):
            handle.cancel()
        if instrument_id not in self._feeds:
            self._feeds[instrument_id] = asyncio.create_task(
                self._run_feed(instrument_id), name=f"feed:{instrument_id}"
            )

    def _maybe_stop(self, instrument_id: str) -> None:
        if self.watched(instrument_id) or instrument_id not in self._feeds:
            return
        if instrument_id in self._stopping:
            return
        loop = asyncio.get_running_loop()
        self._stopping[instrument_id] = loop.call_later(
            self._linger, self._stop_feed, instrument_id
        )

    def _stop_feed(self, instrument_id: str) -> None:
        self._stopping.pop(instrument_id, None)
        if self.watched(instrument_id):
            return
        if task := self._feeds.pop(instrument_id, None):
            task.cancel()

    def _restart(self, instrument_id: str) -> None:
        if task := self._feeds.pop(instrument_id, None):
            task.cancel()
        if self.watched(instrument_id):
            self._ensure_feed(instrument_id)

    def _set_status(self, instrument_id: str, state: FeedState, source: str | None = None) -> None:
        status = FeedStatus(instrument_id, state, source)
        if self.status.get(instrument_id) == status:
            return
        self.status[instrument_id] = status
        for watcher in self._watchers:
            if instrument_id in watcher.ids:
                watcher.send(status)

    async def _run_feed(self, instrument_id: str) -> None:
        ref = await self.instrument(instrument_id)
        if ref is None:
            return
        failures = 0
        while True:
            candidates = self.router.candidates(ref)
            if not candidates:
                self._set_status(instrument_id, "no_source")
                await asyncio.sleep(self._retry_delay(5))  # until sources change
                continue
            provider = candidates[0]
            current = self.status.get(instrument_id)
            if current is None or current.state != "live":
                self._set_status(instrument_id, "connecting", provider.name)
            try:
                if provider.streams:
                    async for quote in provider.stream([ref]):
                        failures = 0
                        self.router.mark_ok(provider, ref)
                        await self.publish(quote)
                    await asyncio.sleep(1)  # the stream closed cleanly: reconnect
                else:
                    quote = await provider.quote(ref)
                    failures = 0
                    self.router.mark_ok(provider, ref)
                    await self.publish(quote)
                    await asyncio.sleep(self._poll.get(provider.name, DEFAULT_POLL_SECONDS))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a feed must survive any provider failure
                failures += 1
                # Warn once per run of failures, so a long outage doesn't flood the log.
                level = logging.WARNING if failures == 1 else logging.DEBUG
                log.log(level, "%s feed for %s failed: %s", provider.name, instrument_id, exc)
                self._set_status(instrument_id, "error", provider.name)
                if failures >= FAILURES_BEFORE_FAILOVER:
                    self.router.mark_failed(provider, ref)
                    failures = 0
                await asyncio.sleep(self._retry_delay(failures))

    async def publish(self, quote: Quote) -> None:
        """Hand a quote to watchers and check it against alerts."""
        previous = self.last.get(quote.instrument_id)
        if previous is not None and quote.at < previous.at and quote.source == previous.source:
            return  # out of order
        self.last[quote.instrument_id] = quote
        self._set_status(quote.instrument_id, "live", quote.source)
        for watcher in self._watchers:
            if quote.instrument_id in watcher.ids:
                watcher.send(quote)
        if quote.instrument_id in self._alert_ids:
            now = self._clock()
            if now - self._alert_checked.get(quote.instrument_id, -1e9) >= ALERT_CHECK_SECONDS:
                self._alert_checked[quote.instrument_id] = now
                await self._check_alerts(quote)

    # Snapshots --------------------------------------------------------------

    async def snapshot(self, instrument_id: str) -> Quote | None:
        """The latest quote: from a running feed, else asked for once."""
        if instrument_id in self._feeds and (quote := self.last.get(instrument_id)):
            return quote
        ref = await self.instrument(instrument_id)
        if ref is None:
            return None
        for provider in self.router.candidates(ref):
            try:
                quote = await provider.quote(ref)
            except Exception as exc:  # try the next provider
                log.warning("%s quote for %s failed: %s", provider.name, instrument_id, exc)
                continue
            self.last[instrument_id] = quote
            return quote
        return self.last.get(instrument_id)

    # Alerts -----------------------------------------------------------------

    def alerts_changed(self) -> None:
        """Called when someone creates or re-arms an alert."""
        self._alerts_changed.set()

    async def _watch_alerts(self) -> None:
        while True:
            try:
                await self.refresh_alerts()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Could not refresh alert instruments")
            self._alerts_changed.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._alerts_changed.wait(), ALERT_REFRESH_SECONDS)
                # Let the request that changed an alert commit first.
                await asyncio.sleep(0.5)

    async def refresh_alerts(self) -> None:
        async with self._engine.connect() as conn:
            ids = set(await conn.scalars(text("SELECT market_alert_instruments()")))
        old, self._alert_ids = self._alert_ids, ids
        for instrument_id in ids - old:
            if await self.instrument(instrument_id) is not None:
                self._ensure_feed(instrument_id)
        for instrument_id in old - ids:
            self._maybe_stop(instrument_id)

    async def _check_alerts(self, quote: Quote) -> None:
        try:
            async with self._engine.begin() as conn:
                fired = (
                    await conn.execute(
                        text("SELECT * FROM market_trigger_alerts(:i, :p)"),
                        {"i": quote.instrument_id, "p": quote.price},
                    )
                ).all()
        except Exception:
            log.exception("Could not check alerts for %s", quote.instrument_id)
            return
        for row in fired:
            event = AlertFired(
                row.alert_id,
                row.user_id,
                quote.instrument_id,
                row.direction,
                row.price,
                quote.price,
                quote.currency,
                row.note,
                quote.at,
            )
            log.info("Alert %s fired for %s", row.alert_id, quote.instrument_id)
            for watcher in self._watchers:
                if watcher.user_id == row.user_id:
                    watcher.send(event)
        if fired:
            self.alerts_changed()
