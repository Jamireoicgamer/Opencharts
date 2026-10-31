# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sign in and out, invite-based registration, and session management."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from openchart_api import audit
from openchart_api.auth import SettingsDep, User, clear_session_cookie, sign_in
from openchart_api.db import Conn
from openchart_api.routes.schemas import (
    AnyPassword,
    Email,
    Me,
    NewAccount,
    SessionInfo,
    Token,
    too_many_attempts,
)
from openchart_api.security import hash_password, token_hash, verify_password
from openchart_api.tables import sessions

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_LOGIN = "Invalid email or password"


class LoginRequest(BaseModel):
    email: Email
    password: AnyPassword


class RegisterRequest(NewAccount):
    invite_token: Token


class RevokedCount(BaseModel):
    revoked: int


@router.post("/login", responses={401: {}, 429: {}})
async def login(
    body: LoginRequest, request: Request, response: Response, conn: Conn, settings: SettingsDep
) -> Me:
    limiter = request.app.state.failure_limiter
    ip = audit.client_ip(request)
    if wait := limiter.retry_after(ip, body.email):
        await audit.record_detached(
            request.app.state.engine, request, "auth.login_rate_limited", target=body.email
        )
        raise too_many_attempts(wait)

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
    await sign_in(
        conn, request, response, settings, user_id=row.id, role=row.role, action="auth.login"
    )
    return Me.of(row)


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
    return Me.of(user)


@router.post(
    "/register", status_code=status.HTTP_201_CREATED, responses={400: {}, 409: {}, 429: {}}
)
async def register(
    body: RegisterRequest, request: Request, response: Response, conn: Conn, settings: SettingsDep
) -> Me:
    # Checked before hashing: argon2 is deliberately expensive, so bad invite
    # attempts must not be able to make the server hash without limit.
    limiter = request.app.state.failure_limiter
    ip = audit.client_ip(request)
    if wait := limiter.retry_after(ip, "register"):
        raise too_many_attempts(wait)
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
        limiter.record_failure(ip, "register")
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This invite link is invalid or has expired"
        )

    await sign_in(
        conn,
        request,
        response,
        settings,
        user_id=row.new_user_id,
        role=row.new_user_role,
        action="auth.registered",
        metadata={"role": row.new_user_role},
    )
    return Me(
        id=row.new_user_id, email=body.email, display_name=body.display_name, role=row.new_user_role
    )


@router.get("/sessions")
async def list_sessions(user: User, conn: Conn) -> list[SessionInfo]:
    s = sessions.c
    rows = await conn.execute(
        select(s.id, s.created_at, s.last_seen_at, s.expires_at, s.user_agent, s.ip)
        .where(s.revoked_at.is_(None), s.expires_at > func.now())
        .order_by(s.last_seen_at.desc())
    )
    return [SessionInfo(**r._mapping, current=r.id == user.session_id) for r in rows]


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
