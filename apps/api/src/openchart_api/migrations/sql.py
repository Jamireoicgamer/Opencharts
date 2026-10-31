# SPDX-License-Identifier: AGPL-3.0-or-later
"""Helpers for migrations written as SQL scripts."""

import re
from types import ModuleType

from alembic import context


def statements(sql: str) -> list[str]:
    """Split a script into single statements (asyncpg prepares each one).

    Statements end with ``;`` at the end of a line; semicolons inside
    ``$$``-quoted function bodies are left alone.
    """
    found: list[str] = []
    current: list[str] = []
    for line in sql.splitlines():
        current.append(line)
        chunk = "\n".join(current)
        if line.rstrip().endswith(";") and chunk.count("$$") % 2 == 0:
            body = chunk.strip().removesuffix(";").strip()
            if body and not all(ln.lstrip().startswith("--") for ln in body.splitlines()):
                found.append(body)
            current = []
    if "\n".join(current).strip():
        raise ValueError("SQL script does not end with a complete statement")
    return found


def run(op: ModuleType, sql: str) -> None:
    for statement in statements(sql):
        op.execute(statement)


def app_role() -> str:
    """The API's database role, passed in by ``openchart_api.migrate``."""
    role = str(context.config.attributes["app_role"])
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError(f"unsafe app role name: {role!r}")
    return role
