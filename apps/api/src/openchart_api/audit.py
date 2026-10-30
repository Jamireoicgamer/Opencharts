# SPDX-License-Identifier: AGPL-3.0-or-later
"""Append-only audit log of security-relevant events.

Never put secrets, passwords or tokens in ``target`` or ``metadata``.
"""

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from openchart_api.db import set_rls_context
from openchart_api.tables import audit_log


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _row(
    request: Request,
    action: str,
    user_id: UUID | None,
    target: str | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "action": action,
        "target": target,
        "ip": client_ip(request),
        "user_agent": (request.headers.get("user-agent") or "")[:512],
        "metadata": metadata or {},
    }


async def record(
    conn: AsyncConnection,
    request: Request,
    action: str,
    *,
    user_id: UUID | None,
    target: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record an event inside the request's transaction."""
    await conn.execute(insert(audit_log).values(_row(request, action, user_id, target, metadata)))


async def record_detached(
    engine: AsyncEngine,
    request: Request,
    action: str,
    *,
    user_id: UUID | None = None,
    role: str = "anonymous",
    target: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record an event in its own transaction, so it survives a failed request."""
    async with engine.begin() as conn:
        if user_id is not None:
            await set_rls_context(conn, user_id, role)
        await record(conn, request, action, user_id=user_id, target=target, metadata=metadata)
