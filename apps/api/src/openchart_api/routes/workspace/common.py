# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared types for the workspace routes."""

from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, Row, Select, Table, select
from sqlalchemy.ext.asyncio import AsyncConnection

from openchart_api.tables import instruments

INSTRUMENT_ID_PATTERN = r"^[A-Z]+:[A-Z0-9.\-]+$"

InstrumentIdPath = Annotated[str, Path(pattern=INSTRUMENT_ID_PATTERN, max_length=40)]
InstrumentIdField = Annotated[str, Field(pattern=INSTRUMENT_ID_PATTERN, max_length=40)]
# Exact decimals, sent as strings in JSON so no precision is lost.
Money = Annotated[Decimal, Field(gt=0, max_digits=28, decimal_places=10)]
AssetClass = Literal["equity", "etf", "crypto", "fx", "index"]


class Instrument(BaseModel):
    id: str
    symbol: str
    name: str
    exchange: str
    currency: str
    asset_class: AssetClass


INSTRUMENT_COLUMNS = [
    instruments.c.id,
    instruments.c.symbol,
    instruments.c.name,
    instruments.c.exchange,
    instruments.c.currency,
    instruments.c.asset_class,
]


async def require_instrument(conn: AsyncConnection, instrument_id: str) -> Instrument:
    row = (
        await conn.execute(select(*INSTRUMENT_COLUMNS).where(instruments.c.id == instrument_id))
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown instrument")
    return Instrument.model_validate(row, from_attributes=True)


_INSTRUMENT_LABELS = [c.label(f"instrument_{c.name}") for c in INSTRUMENT_COLUMNS]


def select_with_instrument(table: Table, *columns: ColumnElement[Any]) -> Select[Any]:
    """Select ``columns`` of ``table`` plus the instrument each row refers to."""
    return select(*columns, *_INSTRUMENT_LABELS).join(
        instruments, instruments.c.id == table.c.instrument_id
    )


def split_instrument(row: Row[Any]) -> dict[str, Any]:
    """A row from :func:`select_with_instrument` as fields with a nested instrument."""
    data = dict(row._mapping)
    data["instrument"] = Instrument(
        **{name: data.pop(f"instrument_{name}") for name in Instrument.model_fields}
    )
    return data
