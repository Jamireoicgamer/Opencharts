# SPDX-License-Identifier: AGPL-3.0-or-later
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
