# SPDX-License-Identifier: AGPL-3.0-or-later
"""Price alerts. Stored now; checked against live prices from milestone M3."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
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
from openchart_api.tables import alerts

router = APIRouter(prefix="/alerts", tags=["alerts"])

Direction = Literal["above", "below"]
Note = Annotated[str, Field(max_length=200)]
MAX_ALERTS = 1000


class AlertInput(BaseModel):
    instrument_id: InstrumentIdField
    direction: Direction
    price: Money
    note: Note = ""


class AlertChange(BaseModel):
    active: bool | None = None
    note: Note | None = None


class Alert(BaseModel):
    id: UUID
    instrument: Instrument
    direction: Direction
    price: Money
    note: str
    active: bool
    created_at: datetime
    triggered_at: datetime | None


def _query() -> Select[Any]:
    return select_with_instrument(
        alerts,
        alerts.c.id,
        alerts.c.direction,
        alerts.c.price,
        alerts.c.note,
        alerts.c.active,
        alerts.c.created_at,
        alerts.c.triggered_at,
    ).order_by(alerts.c.created_at.desc())


def _alert(row: Row[Any]) -> Alert:
    return Alert(**split_instrument(row))


@router.get("")
async def list_alerts(user: User, conn: Conn) -> list[Alert]:
    return [_alert(r) for r in await conn.execute(_query())]


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_alert(body: AlertInput, user: User, request: Request, conn: Conn) -> Alert:
    await require_instrument(conn, body.instrument_id)
    if (await conn.scalar(select(func.count()).select_from(alerts)) or 0) >= MAX_ALERTS:
        raise HTTPException(status.HTTP_409_CONFLICT, "Too many alerts")
    new_id = await conn.scalar(
        insert(alerts).values(user_id=user.id, **body.model_dump()).returning(alerts.c.id)
    )
    alerts_changed(request)
    return _alert((await conn.execute(_query().where(alerts.c.id == new_id))).one())


@router.patch("/{alert_id}")
async def change_alert(
    alert_id: UUID, body: AlertChange, user: User, request: Request, conn: Conn
) -> Alert:
    values: dict[str, Any] = body.model_dump(exclude_none=True)
    if values.get("active"):
        # Re-arming a triggered alert: it can fire again.
        values["triggered_at"] = None
    if values:
        await conn.execute(update(alerts).where(alerts.c.id == alert_id).values(**values))
    row = (await conn.execute(_query().where(alerts.c.id == alert_id))).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    if "active" in values:
        alerts_changed(request)
    return _alert(row)


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(alert_id: UUID, user: User, request: Request, conn: Conn) -> None:
    result = await conn.execute(delete(alerts).where(alerts.c.id == alert_id))
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    alerts_changed(request)


def alerts_changed(request: Request) -> None:
    """Tell the market-data hub which instruments it must watch for alerts."""
    if hub := getattr(request.app.state, "hub", None):
        hub.alerts_changed()
