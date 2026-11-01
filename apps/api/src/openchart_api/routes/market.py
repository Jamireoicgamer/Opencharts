# SPDX-License-Identifier: AGPL-3.0-or-later
"""Prices for the web app: quote snapshots, cached history, and a WebSocket
that streams quotes, feed status and fired alerts."""

import asyncio
import contextlib
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, status
from pydantic import BaseModel
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect, WebSocketState

from openchart_api.auth import (
    User,
    host_allowed,
    mfa_setup_required,
    origin_allowed,
    session_cookie,
)
from openchart_api.config import Settings
from openchart_api.db import set_rls_context
from openchart_api.market.cache import NoSource, Period, SourcesFailed
from openchart_api.market.hub import AlertFired, FeedStatus, Hub, Watcher
from openchart_api.market.models import Candle, Quote
from openchart_api.routes.workspace.common import INSTRUMENT_ID_PATTERN, InstrumentIdPath
from openchart_api.security import token_hash

router = APIRouter(prefix="/market", tags=["market"])
# Mounted outside the HTTP router: its host and CSRF checks take a Request,
# so the WebSocket does the same checks itself.
stream_router = APIRouter(prefix="/api/market", tags=["market"])

MAX_QUOTE_IDS = 50
MAX_MESSAGE_CHARS = 16_000
# An open WebSocket re-checks its session this often, so signing out (or
# being signed out elsewhere) also ends the stream.
SESSION_RECHECK_SECONDS = 60.0
_ID = re.compile(INSTRUMENT_ID_PATTERN)


class QuoteOut(BaseModel):
    instrument_id: str
    price: Decimal
    previous_close: Decimal | None
    change: Decimal | None
    change_pct: Decimal | None
    currency: str
    at: datetime
    source: str
    delay: Literal["realtime", "delayed", "eod"]
    delay_minutes: int | None
    market_state: Literal["open", "closed", "unknown"]

    @classmethod
    def of(cls, q: Quote) -> "QuoteOut":
        pct = q.change_pct
        return cls(
            instrument_id=q.instrument_id,
            price=q.price,
            previous_close=q.previous_close,
            change=q.change,
            change_pct=None if pct is None else pct.quantize(Decimal("0.01")),
            currency=q.currency,
            at=q.at,
            source=q.source,
            delay=q.delay,
            delay_minutes=q.delay_minutes,
            market_state=q.market_state,
        )


class QuoteResult(BaseModel):
    instrument_id: str
    quote: QuoteOut | None
    # Why there is no quote: no enabled source covers it, or sources failed.
    reason: Literal["no_source", "unavailable"] | None = None


class CandleOut(BaseModel):
    t: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None

    @classmethod
    def of(cls, c: Candle) -> "CandleOut":
        return cls(t=c.t, open=c.open, high=c.high, low=c.low, close=c.close, volume=c.volume)


class HistoryOut(BaseModel):
    instrument_id: str
    period: str
    interval: str
    candles: list[CandleOut]
    sources: list[str]
    stale: bool


def hub_of(request: Request) -> Hub:
    hub: Hub = request.app.state.hub
    return hub


@router.get("/quotes")
async def quotes(
    request: Request,
    user: User,
    ids: Annotated[str, Query(max_length=MAX_QUOTE_IDS * 40)],
) -> list[QuoteResult]:
    """Latest quotes for up to 50 comma-separated instrument ids."""
    wanted = list(dict.fromkeys(i for i in ids.split(",") if i))
    if len(wanted) > MAX_QUOTE_IDS or not all(_ID.fullmatch(i) for i in wanted):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid instrument ids")
    hub = hub_of(request)

    async def one(instrument_id: str) -> QuoteResult:
        ref = await hub.instrument(instrument_id)
        if ref is None or not hub.covered(ref):
            return QuoteResult(instrument_id=instrument_id, quote=None, reason="no_source")
        quote = await hub.snapshot(instrument_id)
        if quote is None:
            return QuoteResult(instrument_id=instrument_id, quote=None, reason="unavailable")
        return QuoteResult(instrument_id=instrument_id, quote=QuoteOut.of(quote))

    return list(await asyncio.gather(*(one(i) for i in wanted)))


@router.get("/candles/{instrument_id}")
async def candles(
    instrument_id: InstrumentIdPath, request: Request, user: User, period: Period = "1M"
) -> HistoryOut:
    """Price history for a chart period, served from the cache when possible."""
    hub = hub_of(request)
    ref = await hub.instrument(instrument_id)
    if ref is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown instrument")
    try:
        history = await hub.cache.history(ref, period)
    except NoSource:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no_source") from None
    except SourcesFailed:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "unavailable") from None
    return HistoryOut(
        instrument_id=instrument_id,
        period=period,
        interval=history.interval,
        candles=[CandleOut.of(c) for c in history.candles],
        sources=history.sources,
        stale=history.stale,
    )


# WebSocket -------------------------------------------------------------------


def _encode(event: Quote | FeedStatus | AlertFired) -> str:
    if isinstance(event, Quote):
        return json.dumps({"type": "quote", **QuoteOut.of(event).model_dump(mode="json")})
    if isinstance(event, FeedStatus):
        return json.dumps(
            {
                "type": "status",
                "instrument_id": event.instrument_id,
                "state": event.state,
                "source": event.source,
            }
        )
    return json.dumps(
        {
            "type": "alert",
            "alert_id": str(event.alert_id),
            "instrument_id": event.instrument_id,
            "direction": event.direction,
            "level": str(event.level),
            "price": str(event.price),
            "note": event.note,
            "at": event.at.isoformat(),
        }
    )


async def _session_user(websocket: WebSocket, settings: Settings) -> UUID | None:
    """The signed-in user behind this socket, or None. Same rules as HTTP."""
    token = websocket.cookies.get(session_cookie(settings))
    if not token:
        return None
    async with websocket.app.state.engine.begin() as conn:
        row = (
            await conn.execute(
                text("SELECT * FROM auth_session_lookup(:h)"), {"h": token_hash(token)}
            )
        ).one_or_none()
        if row is None:
            return None
        await set_rls_context(conn, row.user_id, row.role)
        if await mfa_setup_required(conn, row.user_id):
            return None
    user_id: UUID = row.user_id
    return user_id


def _ids(message: dict[str, Any]) -> list[str]:
    ids = message.get("ids")
    if not isinstance(ids, list) or len(ids) > 100:
        return []
    return [i for i in ids if isinstance(i, str) and _ID.fullmatch(i)]


@stream_router.websocket("/stream")
async def stream(websocket: WebSocket) -> None:
    settings: Settings = websocket.app.state.settings
    # Browsers always send Origin on WebSockets, and cookies ride along even
    # cross-site, so the Origin check is what stops cross-site hijacking.
    origin = websocket.headers.get("origin", "")
    host = websocket.headers.get("host", "")
    if not host_allowed(host, settings) or not origin_allowed(origin, host, settings):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user_id = await _session_user(websocket, settings)
    if user_id is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    hub: Hub = websocket.app.state.hub
    await websocket.accept()
    watcher: Watcher = hub.connect(user_id)

    async def send_events() -> None:
        while True:
            await websocket.send_text(_encode(await watcher.queue.get()))

    async def receive_commands() -> None:
        while True:
            raw = await websocket.receive_text()
            if len(raw) > MAX_MESSAGE_CHARS:
                await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                return
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            if message.get("type") == "watch":
                accepted = await hub.watch(watcher, _ids(message))
                await websocket.send_text(json.dumps({"type": "watching", "ids": accepted}))
            elif message.get("type") == "unwatch":
                hub.unwatch(watcher, _ids(message))

    async def recheck_session() -> None:
        while True:
            await asyncio.sleep(SESSION_RECHECK_SECONDS)
            if await _session_user(websocket, settings) != user_id:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

    tasks = [
        asyncio.create_task(send_events()),
        asyncio.create_task(receive_commands()),
        asyncio.create_task(recheck_session()),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, Exception):
                await task
        hub.disconnect(watcher)
        if websocket.application_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await websocket.close()
