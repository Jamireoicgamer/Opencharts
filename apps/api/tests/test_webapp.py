# SPDX-License-Identifier: AGPL-3.0-or-later
"""The desktop app's web serving: same files and headers as nginx."""

import re
from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest

from openchart_api.config import Settings
from openchart_api.main import create_app
from openchart_api.webapp import SECURITY_HEADERS

from .conftest import ORIGIN

pytestmark = pytest.mark.anyio

NGINX = Path(__file__).resolve().parents[3] / "deploy" / "nginx.conf"


def test_headers_match_nginx() -> None:
    nginx = dict(re.findall(r'add_header ([\w-]+) "([^"]+)" always;', NGINX.read_text()))
    assert nginx == SECURITY_HEADERS


@pytest.fixture
def site(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>OpenChart</title>")
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)")
    (tmp_path / "manifest.webmanifest").write_text("{}")
    (tmp_path.parent / "secret.txt").write_text("not for the web")
    return tmp_path


@pytest.fixture
async def web(settings: Settings, site: Path) -> AsyncIterator[httpx2.AsyncClient]:
    app = create_app(settings.model_copy(update={"static_dir": str(site)}))
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        ) as client,
    ):
        yield client


async def test_serves_index_for_app_routes(web: httpx2.AsyncClient) -> None:
    for path in ("/", "/setup", "/w/CRYPTO:BTC-USD"):
        response = await web.get(path)
        assert response.status_code == 200, path
        assert "<title>OpenChart</title>" in response.text
        assert response.headers["cache-control"] == "no-cache"
        for name, value in SECURITY_HEADERS.items():
            assert response.headers[name] == value


async def test_assets_are_cached_and_missing_ones_404(web: httpx2.AsyncClient) -> None:
    asset = await web.get("/assets/app-abc123.js")
    assert asset.status_code == 200
    assert "immutable" in asset.headers["cache-control"]
    assert (await web.get("/assets/missing.js")).status_code == 404


async def test_manifest_type(web: httpx2.AsyncClient) -> None:
    response = await web.get("/manifest.webmanifest")
    assert response.headers["content-type"].startswith("application/manifest+json")


async def test_api_is_not_shadowed(web: httpx2.AsyncClient) -> None:
    health = await web.get("/api/health")
    assert health.json()["status"] == "ok"
    assert health.headers["cache-control"] == "no-store"
    assert health.headers["content-security-policy"] == SECURITY_HEADERS["Content-Security-Policy"]
    missing = await web.get("/api/nope")
    assert missing.status_code == 404
    assert "<title>" not in missing.text


async def test_no_files_outside_the_folder(web: httpx2.AsyncClient) -> None:
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt"):
        response = await web.get(path)
        assert "not for the web" not in response.text, path


async def test_off_without_static_dir(client: httpx2.AsyncClient) -> None:
    assert (await client.get("/")).status_code == 404


async def test_large_bodies_are_refused(web: httpx2.AsyncClient) -> None:
    from openchart_api.webapp import MAX_BODY_BYTES

    big = b"x" * (MAX_BODY_BYTES + 1)
    response = await web.post("/api/auth/login", content=big)
    assert response.status_code == 413
    assert response.headers["x-content-type-options"] == "nosniff"

    async def chunks() -> AsyncIterator[bytes]:  # no Content-Length: counted as it arrives
        for _ in range(3):
            yield b"x" * (MAX_BODY_BYTES // 2)

    response = await web.post("/api/auth/login", content=chunks())
    assert response.status_code == 413, response.text
