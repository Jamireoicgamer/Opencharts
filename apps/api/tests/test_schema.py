# SPDX-License-Identifier: AGPL-3.0-or-later
"""The migrated schema matches the code and keeps its safety properties."""

import base64
import os

import pytest
from anyio import to_thread
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from openchart_api import migrate
from openchart_api.config import Settings
from openchart_api.db import UnsafeDatabaseRole
from openchart_api.main import create_app
from openchart_api.tables import metadata

from .conftest import Database

pytestmark = pytest.mark.anyio


async def test_tables_match_core_definitions(db: Database, admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name <> 'alembic_version'"
            )
        )
        in_db: dict[str, set[str]] = {}
        for row in rows:
            in_db.setdefault(row.table_name, set()).add(row.column_name)
    in_code = {t.name: {c.name for c in t.columns} for t in metadata.sorted_tables}
    assert in_db == in_code


async def test_every_table_has_row_level_security(db: Database, admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        unprotected = (
            await conn.scalars(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename <> 'alembic_version' AND NOT rowsecurity"
                )
            )
        ).all()
    assert unprotected == []


async def test_app_role_cannot_bypass_rls(db: Database, app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        role = (
            await conn.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
    assert not role.rolsuper
    assert not role.rolbypassrls


@pytest.mark.parametrize("which", ["owner", "admin"])
async def test_api_refuses_to_start_with_privileged_role(db: Database, which: str) -> None:
    url = db.owner_url if which == "owner" else db.admin_url
    settings = Settings(database_url=url, master_key=base64.b64encode(os.urandom(32)).decode())
    app = create_app(settings)
    with pytest.raises(UnsafeDatabaseRole):
        async with app.router.lifespan_context(app):
            pass


async def test_migrations_downgrade_and_upgrade_cleanly(db: Database) -> None:
    # The migrator runs its own event loop, so keep it off the test's loop.
    await to_thread.run_sync(migrate.downgrade, db.owner_url, db.app_role, "base")
    await to_thread.run_sync(migrate.upgrade, db.owner_url, db.app_role)
