# SPDX-License-Identifier: AGPL-3.0-or-later
"""A manual holdings journal. Valuations arrive with live prices (M3)."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import Row, Select, delete, func, insert, select, update

from openchart_api.auth import User
from openchart_api.db import Conn
from openchart_api.routes.workspace.common import (
    Instrument,
    InstrumentIdField,
    Money,
    require_instrument,
    select_with_instrument,
    split_instrument,
)
from openchart_api.tables import instruments, positions

router = APIRouter(prefix="/positions", tags=["positions"])

Account = Literal["isa", "gia", "sipp", "other"]
Note = Annotated[str, Field(max_length=500)]
MAX_POSITIONS = 1000


class PositionInput(BaseModel):
    instrument_id: InstrumentIdField
    quantity: Money
    average_price: Money | None = None
    account: Account = "other"
    note: Note = ""


class PositionChange(BaseModel):
    quantity: Money | None = None
    average_price: Money | None = None
    account: Account | None = None
    note: Note | None = None


class Position(BaseModel):
    id: UUID
    instrument: Instrument
    quantity: Money
    average_price: Money | None
    account: Account
    note: str
    created_at: datetime
    updated_at: datetime


def _query() -> Select[Any]:
    return select_with_instrument(
        positions,
        positions.c.id,
        positions.c.quantity,
        positions.c.average_price,
        positions.c.account,
        positions.c.note,
        positions.c.created_at,
        positions.c.updated_at,
    ).order_by(positions.c.account, instruments.c.name, positions.c.created_at)


def _position(row: Row[Any]) -> Position:
    return Position(**split_instrument(row))


@router.get("")
async def list_positions(user: User, conn: Conn) -> list[Position]:
    return [_position(r) for r in await conn.execute(_query())]


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_position(body: PositionInput, user: User, conn: Conn) -> Position:
    await require_instrument(conn, body.instrument_id)
    if (await conn.scalar(select(func.count()).select_from(positions)) or 0) >= MAX_POSITIONS:
        raise HTTPException(status.HTTP_409_CONFLICT, "Too many positions")
    new_id = await conn.scalar(
        insert(positions).values(user_id=user.id, **body.model_dump()).returning(positions.c.id)
    )
    return _position((await conn.execute(_query().where(positions.c.id == new_id))).one())


@router.patch("/{position_id}")
async def change_position(
    position_id: UUID, body: PositionChange, user: User, conn: Conn
) -> Position:
    values = body.model_dump(exclude_unset=True)
    if "quantity" in values and values["quantity"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Quantity is required")
    if values:
        await conn.execute(
            update(positions)
            .where(positions.c.id == position_id)
            .values(**values, updated_at=func.now())
        )
    row = (await conn.execute(_query().where(positions.c.id == position_id))).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")
    return _position(row)


@router.delete("/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_position(position_id: UUID, user: User, conn: Conn) -> None:
    result = await conn.execute(delete(positions).where(positions.c.id == position_id))
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")
