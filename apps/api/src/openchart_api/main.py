# SPDX-License-Identifier: AGPL-3.0-or-later
"""FastAPI application factory.

Run locally with ``uv run uvicorn --factory openchart_api.main:create_app``.
Uvicorn binds to 127.0.0.1 by default; keep it that way unless a reverse
proxy (the Docker ``web`` service) sits in front.
"""

import logging
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from openchart_api.auth import check_host, csrf_protect
from openchart_api.config import Settings
from openchart_api.db import check_database, create_engine
from openchart_api.market.hub import Hub
from openchart_api.oidc import GoogleClient
from openchart_api.routes import (
    audit_log,
    auth,
    data_sources,
    google,
    invites,
    market,
    mfa_login,
    security,
    setup,
)
from openchart_api.routes import secrets as secrets_routes
from openchart_api.routes.workspace import (
    alerts,
    instruments,
    positions,
    preferences,
    research,
    thesis,
    transfer,
    watchlist,
)
from openchart_api.security import FailureLimiter

__version__ = version("openchart-api")

log = logging.getLogger("openchart_api")


class Health(BaseModel):
    status: Literal["ok"]
    version: str


async def _setup_token(app: FastAPI, settings: Settings) -> str | None:
    """The one-time token that guards owner creation, or None once set up."""
    async with app.state.engine.connect() as conn:
        needs_setup = bool(await conn.scalar(text("SELECT auth_needs_setup()")))
    if not needs_setup:
        return None
    if settings.setup_token is not None:
        return settings.setup_token.get_secret_value()
    token = secrets.token_urlsafe(18)
    log.warning("No owner account yet. Open the web app and enter this setup token: %s", token)
    return token


def _configure_logging() -> None:
    """Give the app's own loggers a handler in uvicorn's style (uvicorn only
    configures its own), so warnings such as failing data sources show up
    with their level and source."""
    app_log = logging.getLogger("openchart_api")
    if not app_log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        app_log.addHandler(handler)
        app_log.setLevel(logging.INFO)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()  # read from the environment
    _configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_engine(settings)
        try:
            await check_database(app.state.engine)
            app.state.setup_token = await _setup_token(app, settings)
            app.state.hub = Hub(app.state.engine, settings.master_key_bytes)
            if settings.market_data:
                await app.state.hub.start()
            if settings.public_origin is None:
                log.warning(
                    "OPENCHART_PUBLIC_ORIGIN is not set. Set it to the URL you open the app "
                    "at (for example https://charts.example.com) to enable Secure cookies "
                    "and reject requests addressed to any other host."
                )
            yield
        finally:
            if hub := getattr(app.state, "hub", None):
                await hub.stop()
            await app.state.engine.dispose()

    app = FastAPI(
        title="OpenChart AI API",
        version=__version__,
        docs_url="/api/docs" if settings.api_docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.api_docs else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.failure_limiter = FailureLimiter()
    app.state.oidc = (
        GoogleClient(
            settings.google_client_id or "",
            settings.google_client_secret.get_secret_value()
            if settings.google_client_secret
            else "",
        )
        if settings.google_enabled
        else None
    )

    @app.middleware("http")
    async def no_store(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # API responses hold personal data: keep them out of browser and proxy caches.
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    api = APIRouter(prefix="/api", dependencies=[Depends(check_host), Depends(csrf_protect)])

    @api.get("/health")
    async def health() -> Health:
        """Liveness check used by the web app and container health checks."""
        return Health(status="ok", version=__version__)

    for module in (setup, auth, mfa_login, google, security, invites, secrets_routes, audit_log):
        api.include_router(module.router)
    api.include_router(security.admin_router)
    for module in (
        instruments,
        watchlist,
        thesis,
        research,
        positions,
        alerts,
        preferences,
        transfer,
        market,
        data_sources,
    ):
        api.include_router(module.router)
    app.include_router(api)
    app.include_router(market.stream_router)
    return app
