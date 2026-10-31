# SPDX-License-Identifier: AGPL-3.0-or-later
"""The user's watchlist (one ordered list)."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from openchart_api.auth import User
from openchart_api.db import Conn
from openchart_api.routes.workspace.common import (
    INSTRUMENT_COLUMNS,
    Instrument,
    InstrumentIdField,
    InstrumentIdPath,
    require_instrument,
)
from openchart_api.tables import instruments, watchlist_items

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

MAX_ITEMS = 500


class WatchlistItem(Instrument):
    added_at: datetime


class AddItem(BaseModel):
    instrument_id: InstrumentIdField


class Order(BaseModel):
    instrument_ids: list[InstrumentIdField] = Field(max_length=MAX_ITEMS)


async def _items(conn: Conn) -> list[WatchlistItem]:
    rows = await conn.execute(
        select(*INSTRUMENT_COLUMNS, watchlist_items.c.added_at)
        .join(instruments, instruments.c.id == watchlist_items.c.instrument_id)
        .order_by(watchlist_items.c.position)
    )
    return [WatchlistItem.model_validate(r, from_attributes=True) for r in rows]


@router.get("")
async def get_watchlist(user: User, conn: Conn) -> list[WatchlistItem]:
    return await _items(conn)


@router.post("", status_code=status.HTTP_201_CREATED)
async def add(body: AddItem, user: User, conn: Conn) -> list[WatchlistItem]:
    await require_instrument(conn, body.instrument_id)
    count = await conn.scalar(select(func.count()).select_from(watchlist_items))
    if (count or 0) >= MAX_ITEMS:
        raise HTTPException(status.HTTP_409_CONFLICT, "The watchlist is full")
    next_position = await conn.scalar(
        select(func.coalesce(func.max(watchlist_items.c.position) + 1, 0))
    )
    await conn.execute(
        pg_insert(watchlist_items)
        .values(user_id=user.id, instrument_id=body.instrument_id, position=next_position)
        .on_conflict_do_nothing()
    )
    return await _items(conn)


@router.delete("/{instrument_id}")
async def remove(instrument_id: InstrumentIdPath, user: User, conn: Conn) -> list[WatchlistItem]:
    await conn.execute(
        delete(watchlist_items).where(watchlist_items.c.instrument_id == instrument_id)
    )
    return await _items(conn)


@router.put("/order")
async def reorder(body: Order, user: User, conn: Conn) -> list[WatchlistItem]:
    current = set(await conn.scalars(select(watchlist_items.c.instrument_id)))
    if set(body.instrument_ids) != current or len(body.instrument_ids) != len(current):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The order must list exactly the instruments in the watchlist"
        )
    for position, instrument_id in enumerate(body.instrument_ids):
        await conn.execute(
            update(watchlist_items)
            .where(watchlist_items.c.instrument_id == instrument_id)
            .values(position=position)
        )
    return await _items(conn)
