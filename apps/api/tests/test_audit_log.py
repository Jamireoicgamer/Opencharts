# SPDX-License-Identifier: AGPL-3.0-or-later
"""The audit log can only be appended to — even by the schema owner."""

import httpx2
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .conftest import Database

pytestmark = pytest.mark.anyio


async def test_records_security_events(owner: httpx2.AsyncClient) -> None:
    await owner.put("/api/secrets/finnhub", json={"value": "some-long-secret-value"})
    await owner.delete("/api/secrets/finnhub")
    events = (await owner.get("/api/audit")).json()
    assert [e["action"] for e in events] == [
        "secret.deleted",
        "secret.saved",
        "setup.owner_created",
    ]
    assert events[0]["target"] == "finnhub"
    assert events[0]["ip"]


async def test_pagination(owner: httpx2.AsyncClient) -> None:
    for i in range(5):
        await owner.put(f"/api/secrets/key{i}", json={"value": "x" * 20})
    first = (await owner.get("/api/audit", params={"limit": 2})).json()
    rest = (await owner.get("/api/audit", params={"before_id": first[-1]["id"]})).json()
    assert len(first) == 2
    assert len(first) + len(rest) == 6
    assert first[-1]["id"] > rest[0]["id"]


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log", "TRUNCATE audit_log"],
)
async def test_app_role_cannot_rewrite_history(
    owner: httpx2.AsyncClient, app_engine: AsyncEngine, statement: str
) -> None:
    async with app_engine.begin() as conn:
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text(statement))


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log", "TRUNCATE audit_log"],
)
async def test_even_schema_owner_cannot_rewrite_history(
    owner: httpx2.AsyncClient, db: Database, statement: str
) -> None:
    engine = create_async_engine(db.owner_url)
    try:
        async with engine.begin() as conn:
            with pytest.raises(DBAPIError, match="append-only"):
                await conn.execute(text(statement))
    finally:
        await engine.dispose()
