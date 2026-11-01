# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test fixtures backed by a real, throwaway PostgreSQL database.

Set ``OPENCHART_TEST_ADMIN_URL`` to a superuser connection, for example
``postgresql://postgres:postgres@127.0.0.1:5432/postgres``. Each test run
creates its own database plus owner and app roles, runs the migrations, and
drops everything afterwards. Without the variable the database tests are
skipped, unless ``OPENCHART_REQUIRE_DB_TESTS=1`` (set in CI) makes that an error.
"""

import asyncio
import base64
import os
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from openchart_api import migrate
from openchart_api.config import Settings
from openchart_api.main import create_app

ORIGIN = "http://testserver"
SETUP_TOKEN = "test-setup-token"
OWNER = {"email": "owner@example.com", "display_name": "Owner", "password": "correct horse battery"}


def _asyncpg(url: str) -> str:
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


def _with_credentials(url: str, user: str, password: str, database: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or "127.0.0.1"
    netloc = f"{user}:{password}@{host}" + (f":{parts.port}" if parts.port else "")
    return _asyncpg(urlunsplit((parts.scheme, netloc, f"/{database}", "", "")))


@dataclass(frozen=True)
class Database:
    admin_url: str
    owner_url: str
    app_url: str
    app_role: str
    owner_role: str


async def _admin(url: str, *statements: str) -> None:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def database() -> Iterator[Database]:
    admin = os.environ.get("OPENCHART_TEST_ADMIN_URL")
    if not admin:
        message = "OPENCHART_TEST_ADMIN_URL is not set"
        if os.environ.get("OPENCHART_REQUIRE_DB_TESTS") == "1":
            pytest.fail(message)
        pytest.skip(message)
    admin_url = _asyncpg(admin)
    suffix = secrets.token_hex(4)
    owner_role, app_role, name = f"oc_owner_{suffix}", f"oc_app_{suffix}", f"oc_test_{suffix}"
    owner_pw, app_pw = secrets.token_hex(16), secrets.token_hex(16)
    asyncio.run(
        _admin(
            admin_url,
            f"CREATE ROLE {owner_role} LOGIN PASSWORD '{owner_pw}'",
            f"CREATE ROLE {app_role} LOGIN PASSWORD '{app_pw}'",
            f"CREATE DATABASE {name} OWNER {owner_role}",
        )
    )
    db = Database(
        admin_url=_with_credentials(admin, *_admin_credentials(admin), name),
        owner_url=_with_credentials(admin, owner_role, owner_pw, name),
        app_url=_with_credentials(admin, app_role, app_pw, name),
        app_role=app_role,
        owner_role=owner_role,
    )
    try:
        migrate.upgrade(db.owner_url, app_role)
        yield db
    finally:
        asyncio.run(
            _admin(
                admin_url,
                f"DROP DATABASE IF EXISTS {name} WITH (FORCE)",
                f"DROP ROLE IF EXISTS {app_role}",
                f"DROP ROLE IF EXISTS {owner_role}",
            )
        )


def _admin_credentials(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.username or "postgres", parts.password or ""


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def admin_engine(database: Database) -> AsyncIterator[AsyncEngine]:
    """Superuser connection to the test database, for inspection and cleanup."""
    engine = create_async_engine(database.admin_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_engine(database: Database) -> AsyncIterator[AsyncEngine]:
    """Raw connection as the least-privilege app role, for RLS tests."""
    engine = create_async_engine(database.app_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(database: Database, admin_engine: AsyncEngine) -> Database:
    """The test database, emptied before each test."""
    async with admin_engine.begin() as conn:
        # Replica mode skips the audit log's append-only triggers.
        await conn.execute(text("SET LOCAL session_replication_role = replica"))
        # CASCADE empties every table that references users.
        await conn.execute(text("TRUNCATE users, audit_log CASCADE"))
        await conn.execute(text("UPDATE server_settings SET require_mfa = false"))
        await conn.execute(text("TRUNCATE candles, candle_ranges, data_sources"))
        await conn.execute(
            text(
                "INSERT INTO data_sources (provider, enabled, priority) VALUES "
                "('coinbase', true, 10), ('kraken', true, 20), "
                "('yahoo', false, 30), ('twelvedata', false, 40)"
            )
        )
    return database


@pytest.fixture
def settings(db: Database) -> Settings:
    return Settings(
        database_url=db.app_url,
        migrate_database_url=db.owner_url,
        master_key=base64.b64encode(os.urandom(32)).decode(),
        setup_token=SETUP_TOKEN,
        # Tests never reach real providers; market tests install fakes.
        market_data=False,
    )


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


ClientFactory = Callable[[], httpx2.AsyncClient]


@pytest.fixture
async def new_client(app: FastAPI) -> AsyncIterator[ClientFactory]:
    """Make independent clients, like separate browsers with their own cookies."""
    clients: list[httpx2.AsyncClient] = []

    def make() -> httpx2.AsyncClient:
        client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url=ORIGIN,
            headers={"Origin": ORIGIN},
        )
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


@pytest.fixture
def client(new_client: ClientFactory) -> httpx2.AsyncClient:
    return new_client()


@pytest.fixture
async def owner(client: httpx2.AsyncClient) -> httpx2.AsyncClient:
    """A client signed in as the owner, created through first-run setup."""
    response = await client.post("/api/setup", json={**OWNER, "setup_token": SETUP_TOKEN})
    assert response.status_code == 201, response.text
    return client


Invite = Callable[..., Awaitable[httpx2.AsyncClient]]


@pytest.fixture
def invite_user(owner: httpx2.AsyncClient, new_client: ClientFactory) -> Invite:
    """Invite a new user as the owner and return a client signed in as them."""

    async def invite(email: str, role: str = "member", **extra: Any) -> httpx2.AsyncClient:
        created = await owner.post("/api/invites", json={"role": role})
        assert created.status_code == 201, created.text
        client = new_client()
        response = await client.post(
            "/api/auth/register",
            json={
                "invite_token": created.json()["token"],
                "email": email,
                "display_name": email.split("@")[0],
                "password": "another long password",
                **extra,
            },
        )
        assert response.status_code == 201, response.text
        return client

    return invite
