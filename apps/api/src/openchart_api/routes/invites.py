# SPDX-License-Identifier: AGPL-3.0-or-later
"""Invite links: the only way to join after the owner account exists."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, insert, select

from openchart_api import audit
from openchart_api.auth import Admin, SettingsDep
from openchart_api.db import Conn
from openchart_api.routes.schemas import Email
from openchart_api.security import new_token, token_hash
from openchart_api.tables import invites

router = APIRouter(prefix="/invites", tags=["invites"])


class InviteRequest(BaseModel):
    email: Email | None = None
    role: Literal["admin", "member"] = "member"


class Invite(BaseModel):
    id: UUID
    email: str | None
    role: Literal["admin", "member"]
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None


class CreatedInvite(Invite):
    # Returned once, when the invite is created. Only its hash is stored.
    token: str


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_invite(
    body: InviteRequest,
    request: Request,
    conn: Conn,
    settings: SettingsDep,
    user: Admin,
) -> CreatedInvite:
    if body.role == "admin" and user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can invite admins")
    token = new_token()
    row = (
        await conn.execute(
            insert(invites)
            .values(
                token_hash=token_hash(token),
                created_by=user.id,
                email=body.email,
                role=body.role,
                expires_at=datetime.now(UTC) + timedelta(hours=settings.invite_ttl_hours),
            )
            .returning(invites)
        )
    ).one()
    await audit.record(
        conn,
        request,
        "invite.created",
        user_id=user.id,
        target=str(row.id),
        metadata={"role": body.role, "email": body.email},
    )
    return CreatedInvite(
        id=row.id,
        email=row.email,
        role=row.role,
        created_at=row.created_at,
        expires_at=row.expires_at,
        used_at=row.used_at,
        token=token,
    )


@router.get("")
async def list_invites(conn: Conn, user: Admin) -> list[Invite]:
    rows = await conn.execute(select(invites).order_by(invites.c.created_at.desc()))
    return [
        Invite(
            id=r.id,
            email=r.email,
            role=r.role,
            created_at=r.created_at,
            expires_at=r.expires_at,
            used_at=r.used_at,
        )
        for r in rows
    ]


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(invite_id: UUID, request: Request, conn: Conn, user: Admin) -> None:
    result = await conn.execute(
        delete(invites).where(invites.c.id == invite_id, invites.c.used_at.is_(None))
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found or already used")
    await audit.record(conn, request, "invite.revoked", user_id=user.id, target=str(invite_id))
