# SPDX-License-Identifier: AGPL-3.0-or-later
"""Serving the built web app from the API, for the desktop app.

On a server, nginx serves the web app and sets the security headers
(``deploy/nginx.conf``). The desktop app has no nginx, so when
``static_dir`` is set the API does both, with the same headers; a test
keeps the two identical.
"""

from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), geolocation=(), payment=(), usb=()",
}

_TYPES = {".webmanifest": "application/manifest+json"}


def add_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


def mount_web_app(app: FastAPI, static_dir: str) -> None:
    """Serve files from ``static_dir``, with index.html for app routes."""
    root = Path(static_dir).resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"static_dir has no index.html: {root}")

    @app.get("/{path:path}", include_in_schema=False)
    async def web_app(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        file = (root / path).resolve()
        if path and file.is_relative_to(root) and file.is_file():
            # Hashed build assets never change; everything else is revalidated.
            cache = (
                "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            )
            return FileResponse(
                file, media_type=_TYPES.get(file.suffix), headers={"Cache-Control": cache}
            )
        if path.startswith("assets/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
