# SPDX-License-Identifier: AGPL-3.0-or-later
"""Create the database and roles on a fresh Postgres, for the desktop app.

The Docker stack does this in ``deploy/postgres-init.sh``. The desktop app
has no psql, so ``openchart-api bootstrap`` does the same with the API's
own driver. It is idempotent: on every run it also resets both passwords
to the ones given, so they always match what the app keeps in the OS
keychain.
"""

import asyncpg

OWNER_ROLE = "openchart_owner"
APP_ROLE = "openchart_app"
DATABASE = "openchart"


async def _execute_formatted(conn: asyncpg.Connection, template: str, *args: str) -> None:
    # Utility statements can't take bind parameters; let Postgres quote them.
    statement = await conn.fetchval(f"SELECT format('{template}', {_params(len(args))})", *args)
    await conn.execute(statement)


def _params(count: int) -> str:
    return ", ".join(f"${i}::text" for i in range(1, count + 1))


async def bootstrap(admin_dsn: str, owner_password: str, app_password: str) -> None:
    conn = await asyncpg.connect(admin_dsn)
    try:
        for role, password in ((OWNER_ROLE, owner_password), (APP_ROLE, app_password)):
            exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
            verb = "ALTER" if exists else "CREATE"
            await _execute_formatted(conn, f"{verb} ROLE %I LOGIN PASSWORD %L", role, password)
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", DATABASE):
            await _execute_formatted(conn, "CREATE DATABASE %I OWNER %I", DATABASE, OWNER_ROLE)
        await _execute_formatted(conn, "REVOKE ALL ON DATABASE %I FROM PUBLIC", DATABASE)
        await _execute_formatted(conn, "GRANT CONNECT ON DATABASE %I TO %I", DATABASE, APP_ROLE)
    finally:
        await conn.close()
