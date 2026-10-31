# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-user workspace preferences, synced across devices."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from openchart_api.auth import User
from openchart_api.db import Conn
from openchart_api.routes.workspace.common import InstrumentIdField
from openchart_api.tables import user_preferences

router = APIRouter(prefix="/preferences", tags=["preferences"])


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart_type: Literal["candle", "line"] = "candle"
    period: Literal["1D", "1W", "1M", "3M", "1Y", "ALL"] = "1M"
    show_grid: bool = True
    show_ohlc: bool = False
    compact: bool = False
    risk_profile: Literal["conservative", "balanced", "aggressive"] = "balanced"
    last_instrument: InstrumentIdField | None = None


class PreferencesChange(BaseModel):
    """Only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")

    chart_type: Literal["candle", "line"] | None = None
    period: Literal["1D", "1W", "1M", "3M", "1Y", "ALL"] | None = None
    show_grid: bool | None = None
    show_ohlc: bool | None = None
    compact: bool | None = None
    risk_profile: Literal["conservative", "balanced", "aggressive"] | None = None
    last_instrument: InstrumentIdField | None = None


async def load(conn: AsyncConnection) -> Preferences:
    stored = await conn.scalar(select(user_preferences.c.data)) or {}
    # Ignore keys from older versions rather than failing.
    known = {k: v for k, v in stored.items() if k in Preferences.model_fields}
    return Preferences.model_validate(known)


async def save(conn: AsyncConnection, user_id: object, prefs: Preferences) -> None:
    data = prefs.model_dump()
    await conn.execute(
        pg_insert(user_preferences)
        .values(user_id=user_id, data=data)
        .on_conflict_do_update(
            index_elements=[user_preferences.c.user_id],
            set_={"data": data, "updated_at": func.now()},
        )
    )


@router.get("")
async def get_preferences(user: User, conn: Conn) -> Preferences:
    return await load(conn)


@router.put("")
async def change_preferences(body: PreferencesChange, user: User, conn: Conn) -> Preferences:
    merged = (await load(conn)).model_copy(update=body.model_dump(exclude_unset=True))
    prefs = Preferences.model_validate(merged.model_dump())
    await save(conn, user.id, prefs)
    return prefs
