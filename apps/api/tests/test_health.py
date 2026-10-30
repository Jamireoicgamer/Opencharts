# SPDX-License-Identifier: AGPL-3.0-or-later
import httpx2
import pytest

from openchart_api.main import __version__

pytestmark = pytest.mark.anyio


async def test_health_reports_ok_and_version(client: httpx2.AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_openapi_schema_is_served_under_api_prefix(client: httpx2.AsyncClient) -> None:
    response = await client.get("/api/openapi.json")
    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]
