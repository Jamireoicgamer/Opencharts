# SPDX-License-Identifier: AGPL-3.0-or-later
"""The shared instrument catalogue."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import case, func, or_, select

from openchart_api.auth import User
from openchart_api.db import Conn
from openchart_api.routes.workspace.common import (
    INSTRUMENT_COLUMNS,
    Instrument,
    InstrumentIdPath,
    require_instrument,
)
from openchart_api.tables import instruments

router = APIRouter(prefix="/instruments", tags=["instruments"])


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("")
async def search(
    user: User,
    conn: Conn,
    q: Annotated[str, Query(max_length=60)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[Instrument]:
    q = q.strip()
    query = select(*INSTRUMENT_COLUMNS)
    if q:
        pattern = _like(q)
        upper = q.upper()
        query = query.where(
            or_(
                instruments.c.symbol.ilike(pattern, escape="\\"),
                instruments.c.name.ilike(pattern, escape="\\"),
                instruments.c.id.ilike(pattern, escape="\\"),
            )
        ).order_by(
            # Exact ticker first, then tickers that start with the text.
            case((func.upper(instruments.c.symbol) == upper, 0), else_=1),
            case((func.upper(instruments.c.symbol).startswith(upper), 0), else_=1),
            instruments.c.name,
        )
    else:
        query = query.order_by(instruments.c.name)
    rows = await conn.execute(query.limit(limit))
    return [Instrument.model_validate(r, from_attributes=True) for r in rows]


@router.get("/{instrument_id}")
async def get_instrument(instrument_id: InstrumentIdPath, user: User, conn: Conn) -> Instrument:
    return await require_instrument(conn, instrument_id)
