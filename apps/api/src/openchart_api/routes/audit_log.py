# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read access to the audit log: your own events, or everyone's for the owner."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from openchart_api.auth import User
from openchart_api.db import Conn
from openchart_api.tables import audit_log

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEvent(BaseModel):
    id: int
    user_id: UUID | None
    action: str
    target: str | None
    ip: str | None
    user_agent: str | None
    metadata: dict[str, Any]
    created_at: datetime


@router.get("")
async def list_events(
    user: User,
    conn: Conn,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_id: int | None = None,
) -> list[AuditEvent]:
    query = select(audit_log).order_by(audit_log.c.id.desc()).limit(limit)
    if before_id is not None:
        query = query.where(audit_log.c.id < before_id)
    return [AuditEvent.model_validate(r, from_attributes=True) for r in await conn.execute(query)]
