# SPDX-License-Identifier: AGPL-3.0-or-later
import sys
from pathlib import Path

import anyio
import pytest
from anyio import to_thread

from openchart_api import cli

from .conftest import Database

pytestmark = pytest.mark.anyio


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, db: Database) -> pytest.MonkeyPatch:
    monkeypatch.setenv("OPENCHART_APP_ROLE", db.app_role)
    return monkeypatch


async def test_migrate_is_idempotent(
    env: pytest.MonkeyPatch, db: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    env.setenv("OPENCHART_MIGRATE_DATABASE_URL", db.owner_url)
    assert await to_thread.run_sync(cli.main, ["migrate"]) == 0
    assert "up to date" in capsys.readouterr().out


async def test_migrate_needs_owner_url(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env.delenv("OPENCHART_MIGRATE_DATABASE_URL", raising=False)
    assert cli.main(["migrate"]) == 2
    assert "OPENCHART_MIGRATE_DATABASE_URL" in capsys.readouterr().err


async def test_serve_runs_and_stops_when_stdin_closes(db: Database, tmp_path: Path) -> None:
    import base64
    import os
    import socket
    import subprocess

    import httpx2

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {
        **os.environ,
        "OPENCHART_DATABASE_URL": db.app_url,
        "OPENCHART_MASTER_KEY": base64.b64encode(os.urandom(32)).decode(),
        "OPENCHART_MARKET_DATA": "false",
        "OPENCHART_PUBLIC_ORIGIN": f"http://localhost:{port}",
    }
    process = subprocess.Popen(  # noqa: S603 - our own interpreter and module
        [
            sys.executable,
            "-m",
            "openchart_api.cli",
            "serve",
            "--port",
            str(port),
            "--exit-with-stdin",
        ],
        stdin=subprocess.PIPE,
        env=env,
        cwd=tmp_path,
    )
    try:
        async with httpx2.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            for _ in range(100):
                try:
                    health = await client.get("/api/health", headers={"Host": f"localhost:{port}"})
                    break
                except httpx2.TransportError:
                    await anyio.sleep(0.1)
            else:
                pytest.fail("API did not start")
            assert health.json()["status"] == "ok"
        assert process.stdin is not None
        process.stdin.close()
        assert await to_thread.run_sync(lambda: process.wait(timeout=15)) == 0
    finally:
        process.kill()


async def test_bootstrap_creates_roles_and_is_idempotent(
    env: pytest.MonkeyPatch, database: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    import asyncpg

    from openchart_api import bootstrap

    admin = database.admin_url.replace("+asyncpg", "").rsplit("/", 1)[0] + "/postgres"
    suffix = database.app_role.removeprefix("oc_app_")
    env.setattr(bootstrap, "OWNER_ROLE", f"oc_boot_owner_{suffix}")
    env.setattr(bootstrap, "APP_ROLE", f"oc_boot_app_{suffix}")
    env.setattr(bootstrap, "DATABASE", f"oc_boot_{suffix}")
    env.setenv("OPENCHART_BOOTSTRAP_ADMIN_URL", admin)
    env.setenv("OPENCHART_BOOTSTRAP_OWNER_PASSWORD", "owner-pw-'quoted'")
    try:
        for app_password in ("first-app-pw", "second-app-pw"):
            env.setenv("OPENCHART_BOOTSTRAP_APP_PASSWORD", app_password)
            assert await to_thread.run_sync(cli.main, ["bootstrap"]) == 0
        assert "ready" in capsys.readouterr().out
        host = admin.split("@", 1)[1].rsplit("/", 1)[0]
        conn = await asyncpg.connect(
            f"postgresql://{bootstrap.APP_ROLE}:second-app-pw@{host}/{bootstrap.DATABASE}"
        )
        await conn.close()
        owner = await asyncpg.connect(
            f"postgresql://{bootstrap.OWNER_ROLE}@{host}/{bootstrap.DATABASE}",
            password="owner-pw-'quoted'",
        )
        assert await owner.fetchval("SELECT current_user") == bootstrap.OWNER_ROLE
        await owner.close()
    finally:
        conn = await asyncpg.connect(admin)
        await conn.execute(f"DROP DATABASE IF EXISTS {bootstrap.DATABASE} WITH (FORCE)")
        await conn.execute(f"DROP ROLE IF EXISTS {bootstrap.APP_ROLE}")
        await conn.execute(f"DROP ROLE IF EXISTS {bootstrap.OWNER_ROLE}")
        await conn.close()


def test_bootstrap_needs_its_settings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("ADMIN_URL", "OWNER_PASSWORD", "APP_PASSWORD"):
        monkeypatch.delenv(f"OPENCHART_BOOTSTRAP_{name}", raising=False)
    assert cli.main(["bootstrap"]) == 2
    assert "OPENCHART_BOOTSTRAP_ADMIN_URL" in capsys.readouterr().err
