# SPDX-License-Identifier: AGPL-3.0-or-later
"""API keys and other secrets. Values are write-only: they are never returned."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete, select

from openchart_api import audit, vault
from openchart_api.auth import User
from openchart_api.db import Conn
from openchart_api.tables import vault_secrets

router = APIRouter(prefix="/secrets", tags=["secrets"])

SecretName = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9_.-]{0,63}$")]


class SecretWrite(BaseModel):
    value: Annotated[str, Field(min_length=1, max_length=4096)]
    provider: Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)] | None = None


class SecretInfo(BaseModel):
    name: str
    provider: str | None
    hint: str
    created_at: datetime
    updated_at: datetime


@router.get("")
async def list_secrets(user: User, conn: Conn) -> list[SecretInfo]:
    rows = await conn.execute(
        select(
            vault_secrets.c.name,
            vault_secrets.c.provider,
            vault_secrets.c.hint,
            vault_secrets.c.created_at,
            vault_secrets.c.updated_at,
        ).order_by(vault_secrets.c.name)
    )
    return [SecretInfo.model_validate(r, from_attributes=True) for r in rows]


@router.put("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def save_secret(
    name: SecretName, body: SecretWrite, user: User, request: Request, conn: Conn
) -> None:
    master_key: bytes = request.app.state.settings.master_key_bytes
    await vault.store(conn, master_key, user.id, name, body.value, body.provider or None)
    await audit.record(
        conn,
        request,
        "secret.saved",
        user_id=user.id,
        target=name,
        metadata={"provider": body.provider},
    )


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(name: SecretName, user: User, request: Request, conn: Conn) -> None:
    result = await conn.execute(delete(vault_secrets).where(vault_secrets.c.name == name))
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Secret not found")
    await audit.record(conn, request, "secret.deleted", user_id=user.id, target=name)
