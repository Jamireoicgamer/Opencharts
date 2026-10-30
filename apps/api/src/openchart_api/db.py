# SPDX-License-Identifier: AGPL-3.0-or-later
"""Database engine, per-request transactions and row-level security context."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from openchart_api.config import Settings


class UnsafeDatabaseRole(RuntimeError):
    """The API's database role could bypass row-level security."""


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )


async def check_database(engine: AsyncEngine) -> None:
    """Refuse to start if row-level security would not protect tenant data."""
    async with engine.connect() as conn:
        role = (
            await conn.execute(
                text(
                    "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            )
        ).one()
        if role.rolsuper or role.rolbypassrls:
            raise UnsafeDatabaseRole(
                f"database role {role.rolname!r} is a superuser or has BYPASSRLS; "
                "connect as the least-privilege app role instead"
            )
        owner = await conn.scalar(
            text(
                "SELECT tableowner FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename = 'users'"
            )
        )
        if owner is None:
            raise RuntimeError("database schema is missing; run `openchart-api migrate` first")
        if owner == role.rolname:
            raise UnsafeDatabaseRole(
                f"database role {role.rolname!r} owns the schema, so row-level security "
                "does not apply to it; use a separate app role"
            )


async def transaction(request: Request) -> AsyncIterator[AsyncConnection]:
    """One transaction per request: committed on success, rolled back on error."""
    engine: AsyncEngine = request.app.state.engine
    async with engine.begin() as conn:
        yield conn


Conn = Annotated[AsyncConnection, Depends(transaction)]


async def set_rls_context(conn: AsyncConnection, user_id: UUID, role: str) -> None:
    """Scope the rest of this transaction to one user for row-level security."""
    await conn.execute(
        text(
            "SELECT set_config('app.user_id', :uid, true), set_config('app.user_role', :role, true)"
        ),
        {"uid": str(user_id), "role": role},
    )
