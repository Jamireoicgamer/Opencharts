# SPDX-License-Identifier: AGPL-3.0-or-later
import httpx2
import pytest

from openchart_api.config import Settings
from openchart_api.main import __version__, create_app

from .conftest import ORIGIN

pytestmark = pytest.mark.anyio


async def test_health_reports_ok_and_version(client: httpx2.AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_api_docs_are_off_by_default(client: httpx2.AsyncClient) -> None:
    for path in ("/api/docs", "/api/openapi.json"):
        assert (await client.get(path)).status_code == 404, path


async def test_api_docs_can_be_enabled(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"api_docs": True}))
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=ORIGIN) as client,
    ):
        schema = await client.get("/api/openapi.json")
        assert "/api/health" in schema.json()["paths"]
        assert (await client.get("/api/docs")).status_code == 200
