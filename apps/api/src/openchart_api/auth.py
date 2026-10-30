# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sessions, the current-user dependency, role checks and request guards."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import func, insert, text, update
from sqlalchemy.ext.asyncio import AsyncConnection

from openchart_api import audit
from openchart_api.config import Settings
from openchart_api.db import Conn, set_rls_context
from openchart_api.security import new_token, token_hash
from openchart_api.tables import sessions

Role = Literal["owner", "admin", "member"]
_TOUCH_INTERVAL = timedelta(minutes=5)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Always accepted as Host, for the container health check and local use.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str
    display_name: str
    role: Role
    session_id: UUID


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings)]


def session_cookie(settings: Settings) -> str:
    """Cookie name. Over HTTPS the ``__Host-`` prefix makes browsers refuse it
    unless it is Secure, host-only and scoped to ``/``, so a sibling subdomain
    cannot plant or overwrite it."""
    return "__Host-oc_session" if settings.cookie_secure else "oc_session"


async def sign_in(
    conn: AsyncConnection,
    request: Request,
    response: Response,
    settings: Settings,
    *,
    user_id: UUID,
    role: str,
    action: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Start a session for ``user_id``, set its cookie and record ``action``.

    Any session this browser already had is ended first, so signing in again
    never leaves an orphaned session behind. Sets the RLS context to the user.
    """
    if previous := request.cookies.get(session_cookie(settings)):
        await conn.execute(text("SELECT auth_revoke_session(:h)"), {"h": token_hash(previous)})
    await set_rls_context(conn, user_id, role)
    token = new_token()
    ttl = timedelta(days=settings.session_ttl_days)
    await conn.execute(
        insert(sessions).values(
            user_id=user_id,
            token_hash=token_hash(token),
            expires_at=datetime.now(UTC) + ttl,
            user_agent=(request.headers.get("user-agent") or "")[:512],
            ip=audit.client_ip(request)[:64],
        )
    )
    response.set_cookie(
        session_cookie(settings),
        token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    await audit.record(conn, request, action, user_id=user_id, metadata=metadata)


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        session_cookie(settings),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


async def current_user(request: Request, conn: Conn, settings: SettingsDep) -> CurrentUser:
    token = request.cookies.get(session_cookie(settings))
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    row = (
        await conn.execute(text("SELECT * FROM auth_session_lookup(:h)"), {"h": token_hash(token)})
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or signed out")
    await set_rls_context(conn, row.user_id, row.role)
    await conn.execute(
        update(sessions)
        .where(sessions.c.id == row.session_id)
        .where(sessions.c.last_seen_at < func.now() - _TOUCH_INTERVAL)
        .values(last_seen_at=func.now())
    )
    return CurrentUser(row.user_id, row.email, row.display_name, row.role, row.session_id)


User = Annotated[CurrentUser, Depends(current_user)]


def require_role(*roles: Role) -> Callable[[CurrentUser], Awaitable[CurrentUser]]:
    async def check(user: User) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")
        return user

    return check


Admin = Annotated[CurrentUser, Depends(require_role("owner", "admin"))]


def _origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower() if parts.scheme and parts.netloc else None


async def check_host(request: Request, settings: SettingsDep) -> None:
    """With a public origin configured, only answer requests addressed to it.

    This defeats DNS rebinding, where an attacker's domain is pointed at the
    server so that the attacker's page counts as "same origin".
    """
    if settings.public_host is None:
        return
    host = urlsplit(f"//{request.headers.get('host', '')}").hostname or ""
    if host not in _LOCAL_HOSTS and host != settings.public_host:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown host")


async def csrf_protect(request: Request, settings: SettingsDep) -> None:
    """Reject state-changing requests that do not come from the app's own origin.

    Session cookies are SameSite=Lax, which already blocks most cross-site
    requests; this check also covers same-site attackers (other apps on a
    sibling subdomain) and older browsers.
    """
    if request.method in _SAFE_METHODS:
        return
    if request.headers.get("sec-fetch-site") in ("cross-site", "same-site"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cross-site request blocked")
    origin = request.headers.get("origin") or _origin_of(request.headers.get("referer") or "")
    if origin is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing Origin header")
    host = request.headers.get("host", "")
    allowed = (
        {settings.public_origin.lower()}
        if settings.public_origin
        else {f"http://{host}".lower(), f"https://{host}".lower()}
    )
    if origin.lower() not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cross-origin request blocked")
