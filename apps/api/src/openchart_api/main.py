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
from openchart_api.routes import audit_log, auth, invites, setup
from openchart_api.routes import secrets as secrets_routes
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()  # read from the environment

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_engine(settings)
        try:
            await check_database(app.state.engine)
            app.state.setup_token = await _setup_token(app, settings)
            if settings.public_origin is None:
                log.warning(
                    "OPENCHART_PUBLIC_ORIGIN is not set. Set it to the URL you open the app "
                    "at (for example https://charts.example.com) to enable Secure cookies "
                    "and reject requests addressed to any other host."
                )
            yield
        finally:
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

    for module in (setup, auth, invites, secrets_routes, audit_log):
        api.include_router(module.router)
    app.include_router(api)
    return app
