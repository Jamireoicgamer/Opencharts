# SPDX-License-Identifier: AGPL-3.0-or-later
"""Session cookies, the current-user dependency, role checks and CSRF protection."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import func, insert, text, update
from sqlalchemy.ext.asyncio import AsyncConnection

from openchart_api.audit import client_ip
from openchart_api.config import Settings
from openchart_api.db import Conn, set_rls_context
from openchart_api.security import new_token, token_hash
from openchart_api.tables import sessions

SESSION_COOKIE = "oc_session"
Role = Literal["owner", "admin", "member"]
_TOUCH_INTERVAL = timedelta(minutes=5)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


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


async def start_session(
    conn: AsyncConnection,
    request: Request,
    response: Response,
    settings: Settings,
    user_id: UUID,
    role: str,
) -> None:
    """Create a session for ``user_id`` and set the cookie. Sets the RLS context."""
    await set_rls_context(conn, user_id, role)
    token = new_token()
    ttl = timedelta(days=settings.session_ttl_days)
    await conn.execute(
        insert(sessions).values(
            user_id=user_id,
            token_hash=token_hash(token),
            expires_at=datetime.now(UTC) + ttl,
            user_agent=(request.headers.get("user-agent") or "")[:512],
            ip=client_ip(request)[:64],
        )
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/"
    )


async def current_user(request: Request, conn: Conn) -> CurrentUser:
    token = request.cookies.get(SESSION_COOKIE)
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
    allowed = (
        {settings.public_origin.lower()}
        if settings.public_origin
        else {
            f"http://{request.headers.get('host', '')}".lower(),
            f"https://{request.headers.get('host', '')}".lower(),
        }
    )
    if origin.lower() not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cross-origin request blocked")
