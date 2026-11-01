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
from fastapi.responses import FileResponse, JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# nginx's client_max_body_size.
MAX_BODY_BYTES = 1024 * 1024

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


class BodyLimit:
    """Refuse request bodies over ``MAX_BODY_BYTES``, as nginx does on a server."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
            await _too_large(scope, receive, send)
            return
        received = 0
        too_large = False

        async def limited() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:
                    # Stop reading; whatever the app answers becomes a 413.
                    too_large = True
                    return {"type": "http.disconnect"}
            return message

        replaced = False

        async def checked(message: Message) -> None:
            nonlocal replaced
            if not too_large:
                await send(message)
            elif not replaced:
                replaced = True
                await _too_large(scope, receive, send)

        try:
            await self.app(scope, limited, checked)
        except Exception:
            if not too_large:
                raise
        if too_large and not replaced:
            await _too_large(scope, receive, send)


async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
    response = JSONResponse({"detail": "Request too large"}, status.HTTP_413_CONTENT_TOO_LARGE)
    await response(scope, receive, send)


def add_security_headers(app: FastAPI) -> None:
    """nginx's request size limit and response headers. Added last, so it's outermost."""
    app.add_middleware(BodyLimit)

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
