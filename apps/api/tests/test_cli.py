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
