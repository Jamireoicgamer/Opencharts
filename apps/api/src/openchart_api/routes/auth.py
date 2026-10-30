# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sign in and out, invite-based registration, and session management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from openchart_api import audit
from openchart_api.auth import SettingsDep, User, clear_session_cookie, start_session
from openchart_api.db import Conn
from openchart_api.routes.schemas import AnyPassword, Email, Me, NewAccount, SessionInfo
from openchart_api.security import hash_password, token_hash, verify_password
from openchart_api.tables import sessions

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_LOGIN = "Invalid email or password"


class LoginRequest(BaseModel):
    email: Email
    password: AnyPassword


class RegisterRequest(NewAccount):
    invite_token: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]


class RevokedCount(BaseModel):
    revoked: int


@router.post("/login", responses={401: {}, 429: {}})
async def login(
    body: LoginRequest, request: Request, response: Response, conn: Conn, settings: SettingsDep
) -> Me:
    limiter = request.app.state.login_limiter
    ip = audit.client_ip(request)
    if wait := limiter.retry_after(ip, body.email):
        await audit.record_detached(
            request.app.state.engine, request, "auth.login_rate_limited", target=body.email
        )
        return JSONResponse(  # type: ignore[return-value]
            {"detail": "Too many failed sign-in attempts. Try again later."},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(wait)},
        )

    row = (
        await conn.execute(text("SELECT * FROM auth_login_lookup(:email)"), {"email": body.email})
    ).one_or_none()
    if not await verify_password(row.password_hash if row else None, body.password) or row is None:
        limiter.record_failure(ip, body.email)
        # Attributed to the account when it exists, so its owner sees the attempt.
        await audit.record_detached(
            request.app.state.engine,
            request,
            "auth.login_failed",
            user_id=row.id if row else None,
            role=row.role if row else "anonymous",
            target=body.email,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_LOGIN)

    limiter.reset(ip, body.email)
    await start_session(conn, request, response, settings, row.id, row.role)
    await audit.record(conn, request, "auth.login", user_id=row.id)
    return Me(id=row.id, email=row.email, display_name=row.display_name, role=row.role)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(user: User, request: Request, conn: Conn, settings: SettingsDep) -> Response:
    await conn.execute(
        update(sessions).where(sessions.c.id == user.session_id).values(revoked_at=func.now())
    )
    await audit.record(conn, request, "auth.logout", user_id=user.id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, settings)
    return response


@router.get("/me")
async def me(user: User) -> Me:
    return Me(id=user.id, email=user.email, display_name=user.display_name, role=user.role)


@router.post("/register", status_code=status.HTTP_201_CREATED, responses={400: {}, 409: {}})
async def register(
    body: RegisterRequest, request: Request, response: Response, conn: Conn, settings: SettingsDep
) -> Me:
    params = {
        "token": token_hash(body.invite_token),
        "email": body.email,
        "name": body.display_name,
        "hash": await hash_password(body.password),
    }
    try:
        async with conn.begin_nested():
            row = (
                await conn.execute(
                    text("SELECT * FROM auth_redeem_invite(:token, :email, :name, :hash)"), params
                )
            ).one_or_none()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account with that email already exists"
        ) from None
    if row is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This invite link is invalid or has expired"
        )

    await start_session(conn, request, response, settings, row.new_user_id, row.new_user_role)
    await audit.record(
        conn,
        request,
        "auth.registered",
        user_id=row.new_user_id,
        metadata={"role": row.new_user_role},
    )
    return Me(
        id=row.new_user_id, email=body.email, display_name=body.display_name, role=row.new_user_role
    )


@router.get("/sessions")
async def list_sessions(user: User, conn: Conn) -> list[SessionInfo]:
    rows = await conn.execute(
        select(sessions)
        .where(sessions.c.revoked_at.is_(None), sessions.c.expires_at > func.now())
        .order_by(sessions.c.last_seen_at.desc())
    )
    return [
        SessionInfo(
            id=r.id,
            created_at=r.created_at,
            last_seen_at=r.last_seen_at,
            expires_at=r.expires_at,
            user_agent=r.user_agent,
            ip=r.ip,
            current=r.id == user.session_id,
        )
        for r in rows
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(session_id: UUID, user: User, request: Request, conn: Conn) -> None:
    result = await conn.execute(
        update(sessions)
        .where(sessions.c.id == session_id, sessions.c.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    await audit.record(
        conn, request, "auth.session_revoked", user_id=user.id, target=str(session_id)
    )


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(user: User, request: Request, conn: Conn) -> RevokedCount:
    result = await conn.execute(
        update(sessions)
        .where(sessions.c.id != user.session_id, sessions.c.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )
    await audit.record(
        conn,
        request,
        "auth.sessions_revoked_others",
        user_id=user.id,
        metadata={"count": result.rowcount},
    )
    return RevokedCount(revoked=result.rowcount)
