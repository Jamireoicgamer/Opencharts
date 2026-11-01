# SPDX-License-Identifier: AGPL-3.0-or-later
"""Investment theses: a journal of versions per instrument.

Saving never overwrites: each save adds a version, and the newest one is the
current thesis.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select

from openchart_api import audit
from openchart_api.auth import User
from openchart_api.db import Conn
from openchart_api.routes.workspace.common import InstrumentIdPath, Money, require_instrument
from openchart_api.tables import thesis_versions

router = APIRouter(prefix="/instruments/{instrument_id}/thesis", tags=["thesis"])

Conviction = Literal["not_assessed", "low", "moderate", "high"]
Horizon = Literal["not_set", "under_1y", "1_3y", "3_5y", "over_5y"]
HISTORY_LIMIT = 100


class ThesisInput(BaseModel):
    summary: Annotated[str, Field(max_length=10000)] = ""
    key_risk: Annotated[str, Field(max_length=5000)] = ""
    bull_case: Annotated[str, Field(max_length=5000)] = ""
    bear_case: Annotated[str, Field(max_length=5000)] = ""
    fair_value: Money | None = None
    entry_price: Money | None = None
    conviction: Conviction = "not_assessed"
    horizon: Horizon = "not_set"


class ThesisVersion(ThesisInput):
    id: UUID
    created_at: datetime


class Thesis(BaseModel):
    current: ThesisVersion | None
    history: list[ThesisVersion]


_COLUMNS = [
    thesis_versions.c.id,
    thesis_versions.c.summary,
    thesis_versions.c.key_risk,
    thesis_versions.c.bull_case,
    thesis_versions.c.bear_case,
    thesis_versions.c.fair_value,
    thesis_versions.c.entry_price,
    thesis_versions.c.conviction,
    thesis_versions.c.horizon,
    thesis_versions.c.created_at,
]


@router.get("")
async def get_thesis(instrument_id: InstrumentIdPath, user: User, conn: Conn) -> Thesis:
    await require_instrument(conn, instrument_id)
    rows = await conn.execute(
        select(*_COLUMNS)
        .where(thesis_versions.c.instrument_id == instrument_id)
        .order_by(thesis_versions.c.created_at.desc())
        .limit(HISTORY_LIMIT)
    )
    history = [ThesisVersion.model_validate(r, from_attributes=True) for r in rows]
    return Thesis(current=history[0] if history else None, history=history)


@router.post("", status_code=status.HTTP_201_CREATED)
async def save_thesis(
    instrument_id: InstrumentIdPath, body: ThesisInput, user: User, conn: Conn
) -> ThesisVersion:
    await require_instrument(conn, instrument_id)
    row = (
        await conn.execute(
            insert(thesis_versions)
            .values(user_id=user.id, instrument_id=instrument_id, **body.model_dump())
            .returning(*_COLUMNS)
        )
    ).one()
    return ThesisVersion.model_validate(row, from_attributes=True)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thesis(
    instrument_id: InstrumentIdPath, user: User, request: Request, conn: Conn
) -> None:
    """Delete this instrument's whole thesis history."""
    await conn.execute(
        delete(thesis_versions).where(thesis_versions.c.instrument_id == instrument_id)
    )
    await audit.record(conn, request, "thesis.deleted", user_id=user.id, target=instrument_id)
