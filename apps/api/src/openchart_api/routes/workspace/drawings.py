# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chart drawings per instrument: trend lines, horizontal levels,
rectangles, Fibonacci retracements and notes."""

import math
from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, insert, select, update

from openchart_api.auth import User
from openchart_api.db import Conn
from openchart_api.routes.workspace.common import InstrumentIdPath, require_instrument
from openchart_api.tables import drawings

router = APIRouter(prefix="/instruments/{instrument_id}/drawings", tags=["drawings"])

Kind = Literal["trend", "hline", "rect", "fib", "note"]
Color = Literal["accent", "amber", "blue", "pink", "green", "red", "muted"]
Text = Annotated[str, Field(max_length=200)]
# How many points each kind is drawn from.
POINTS = {"trend": 2, "hline": 1, "rect": 2, "fib": 2, "note": 1}
MAX_DRAWINGS = 200
# 1970 to 2100, in seconds.
LATEST_TIME = 4_102_444_800


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t: Annotated[int, Field(ge=0, le=LATEST_TIME)]
    price: Annotated[float, Field(gt=0, lt=1e12)]

    @field_validator("price")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("price must be a number")
        return value


Points = Annotated[list[Point], Field(min_length=1, max_length=2)]


def _check_points(kind: str, points: list[Point]) -> None:
    if len(points) != POINTS[kind]:
        raise ValueError(f"a {kind} drawing needs {POINTS[kind]} point(s)")


class DrawingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind
    points: Points
    color: Color = "accent"
    text: Text = ""

    @model_validator(mode="after")
    def _points_fit_kind(self) -> Self:
        _check_points(self.kind, self.points)
        return self


class DrawingChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: Points | None = None
    color: Color | None = None
    text: Text | None = None


class Drawing(DrawingInput):
    # Built from table rows, which also carry user_id.
    model_config = ConfigDict(extra="ignore")

    id: UUID
    instrument_id: str
    created_at: datetime
    updated_at: datetime


async def list_drawings(conn: Conn, instrument_id: str | None = None) -> list[Drawing]:
    query = select(drawings).order_by(drawings.c.instrument_id, drawings.c.created_at)
    if instrument_id is not None:
        query = query.where(drawings.c.instrument_id == instrument_id)
    return [Drawing.model_validate(dict(r._mapping)) for r in await conn.execute(query)]


@router.get("")
async def get_drawings(instrument_id: InstrumentIdPath, user: User, conn: Conn) -> list[Drawing]:
    await require_instrument(conn, instrument_id)
    return await list_drawings(conn, instrument_id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_drawing(
    instrument_id: InstrumentIdPath, body: DrawingInput, user: User, conn: Conn
) -> Drawing:
    await require_instrument(conn, instrument_id)
    count = await conn.scalar(
        select(func.count()).select_from(drawings).where(drawings.c.instrument_id == instrument_id)
    )
    if (count or 0) >= MAX_DRAWINGS:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"At most {MAX_DRAWINGS} drawings per instrument"
        )
    row = (
        await conn.execute(
            insert(drawings)
            .values(user_id=user.id, instrument_id=instrument_id, **body.model_dump())
            .returning(drawings)
        )
    ).one()
    return Drawing.model_validate(dict(row._mapping))


@router.patch("/{drawing_id}")
async def change_drawing(
    instrument_id: InstrumentIdPath,
    drawing_id: UUID,
    body: DrawingChange,
    user: User,
    conn: Conn,
) -> Drawing:
    current = (
        await conn.execute(
            select(drawings.c.kind).where(
                drawings.c.id == drawing_id, drawings.c.instrument_id == instrument_id
            )
        )
    ).one_or_none()
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such drawing")
    values: dict[str, Any] = body.model_dump(exclude_none=True)
    if body.points is not None:
        try:
            _check_points(current.kind, body.points)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    row = (
        await conn.execute(
            update(drawings)
            .where(drawings.c.id == drawing_id)
            .values(**values, updated_at=func.now())
            .returning(drawings)
        )
    ).one()
    return Drawing.model_validate(dict(row._mapping))


@router.delete("/{drawing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_drawing(
    instrument_id: InstrumentIdPath, drawing_id: UUID, user: User, conn: Conn
) -> Response:
    result = await conn.execute(
        delete(drawings).where(
            drawings.c.id == drawing_id, drawings.c.instrument_id == instrument_id
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such drawing")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_drawings(instrument_id: InstrumentIdPath, user: User, conn: Conn) -> Response:
    await conn.execute(delete(drawings).where(drawings.c.instrument_id == instrument_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
