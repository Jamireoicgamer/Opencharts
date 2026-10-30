# SPDX-License-Identifier: AGPL-3.0-or-later
"""FastAPI application entry point.

Run locally with ``uv run uvicorn openchart_api.main:app --reload``. Uvicorn
binds to 127.0.0.1 by default; keep it that way until authentication lands
in milestone M1.
"""

from importlib.metadata import version
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

__version__ = version("openchart-api")

app = FastAPI(
    title="OpenChart AI API",
    version=__version__,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)


class Health(BaseModel):
    status: Literal["ok"]
    version: str


@app.get("/api/health")
def health() -> Health:
    """Liveness check used by the web app and container health checks."""
    return Health(status="ok", version=__version__)
