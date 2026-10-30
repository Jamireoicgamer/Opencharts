# SPDX-License-Identifier: AGPL-3.0-or-later
from fastapi.testclient import TestClient

from openchart_api.main import __version__, app

client = TestClient(app)


def test_health_reports_ok_and_version() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_openapi_schema_is_served_under_api_prefix() -> None:
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]
