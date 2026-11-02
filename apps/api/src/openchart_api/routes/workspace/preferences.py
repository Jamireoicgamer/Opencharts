# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-user workspace preferences, synced across devices."""

from typing import Annotated, Literal, Self

from fastapi import APIRouter
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from openchart_api.auth import User
from openchart_api.db import Conn
from openchart_api.routes.workspace.common import InstrumentIdField
from openchart_api.tables import user_preferences

router = APIRouter(prefix="/preferences", tags=["preferences"])


# Indicators with a period the user chooses, and the default for each.
PERIODIC = {"sma": 20, "ema": 20, "bollinger": 20, "rsi": 14}
MAX_INDICATORS = 10


class Indicator(BaseModel):
    """One indicator shown on the chart."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["sma", "ema", "bollinger", "vwap", "volume", "rsi", "macd"]
    period: Annotated[int, Field(ge=2, le=400)] | None = None

    @model_validator(mode="after")
    def _period_fits_kind(self) -> Self:
        if self.kind in PERIODIC:
            if self.period is None:
                self.period = PERIODIC[self.kind]
        elif self.period is not None:
            raise ValueError(f"{self.kind} has no period")
        return self


def _distinct(indicators: list[Indicator]) -> list[Indicator]:
    keys = [(i.kind, i.period) for i in indicators]
    if len(keys) != len(set(keys)):
        raise ValueError("the same indicator is listed twice")
    return indicators


Indicators = Annotated[list[Indicator], Field(max_length=MAX_INDICATORS), AfterValidator(_distinct)]


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart_type: Literal["candle", "line"] = "candle"
    period: Literal["1D", "1W", "1M", "3M", "1Y", "ALL"] = "1M"
    show_grid: bool = True
    show_ohlc: bool = False
    compact: bool = False
    risk_profile: Literal["conservative", "balanced", "aggressive"] = "balanced"
    last_instrument: InstrumentIdField | None = None
    indicators: Indicators = []


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
    indicators: Indicators | None = None


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
    current = (await load(conn)).model_dump()
    prefs = Preferences.model_validate({**current, **body.model_dump(exclude_unset=True)})
    await save(conn, user.id, prefs)
    return prefs
