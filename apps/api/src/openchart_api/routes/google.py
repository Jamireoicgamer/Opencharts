# SPDX-License-Identifier: AGPL-3.0-or-later
"""Google sign-in: link an account, sign in with a linked one, join by invite.

A Google login never creates an account or takes one over by itself: the
Google identity must have been linked by a signed-in user, or the person
must hold an invite.
"""

import secrets
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, insert, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from openchart_api import audit, flows
from openchart_api.auth import (
    CurrentUser,
    SettingsDep,
    clear_flow_cookie,
    mark_reauthenticated,
    require_recent_auth,
    session_user,
    set_flow_cookie,
    sign_in,
)
from openchart_api.db import Conn, set_rls_context
from openchart_api.oidc import OidcClient, OidcError, pkce_pair
from openchart_api.routes.mfa_login import FLOW_COOKIE, begin_second_factor
from openchart_api.routes.schemas import Token
from openchart_api.security import token_hash
from openchart_api.tables import oauth_identities

router = APIRouter(prefix="/auth/google", tags=["google"])

OAUTH_SECONDS = 600
Purpose = Literal["login", "link", "register", "reauth"]


class StartRequest(BaseModel):
    purpose: Purpose
    # Only for "register". Sent in the body so it never appears in a URL.
    invite_token: Token | None = None


class StartResponse(BaseModel):
    url: str


def _client(request: Request) -> OidcClient:
    client: OidcClient | None = getattr(request.app.state, "oidc", None)
    if client is None or not request.app.state.settings.google_enabled:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Google sign-in is not set up on this server"
        )
    return client


def _redirect_uri(request: Request) -> str:
    return f"{request.app.state.settings.public_origin}/api/auth/google/callback"


async def _signed_in(request: Request, conn: Conn, settings: SettingsDep) -> CurrentUser | None:
    try:
        return await session_user(request, conn, settings)
    except HTTPException:
        return None


@router.post("/start")
async def start(
    body: StartRequest, request: Request, response: Response, conn: Conn, settings: SettingsDep
) -> StartResponse:
    client = _client(request)
    user = await _signed_in(request, conn, settings)
    if body.purpose in ("link", "reauth") and user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    if body.purpose == "link" and user is not None:
        await require_recent_auth(user, conn)
    if body.purpose == "register" and not body.invite_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An invite is needed to join")

    verifier, challenge = pkce_pair()
    nonce = secrets.token_urlsafe(24)
    data = {"purpose": body.purpose, "verifier": verifier, "nonce": nonce}
    if body.invite_token:
        data["invite_hash"] = token_hash(body.invite_token).hex()
    state = await flows.start(
        conn,
        "oauth",
        user_id=user.id if user and body.purpose in ("link", "reauth") else None,
        data=data,
        ttl_seconds=OAUTH_SECONDS,
    )
    # The cookie ties the callback to this browser: a callback URL started
    # by someone else (login CSRF) is rejected.
    set_flow_cookie(response, settings, FLOW_COOKIE, state, OAUTH_SECONDS)
    url = client.authorization_url(
        redirect_uri=_redirect_uri(request), state=state, nonce=nonce, code_challenge=challenge
    )
    return StartResponse(url=url)


def _back(path: str, fragment: str) -> RedirectResponse:
    return RedirectResponse(f"{path}#{fragment}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/callback")
async def callback(
    request: Request,
    conn: Conn,
    settings: SettingsDep,
    state: str = "",
    code: str = "",
    error: str = "",
) -> RedirectResponse:
    client = _client(request)
    cookie = request.cookies.get(FLOW_COOKIE, "")
    flow = None
    if state and cookie and secrets.compare_digest(cookie, state):
        flow = await flows.take(conn, "oauth", state)
    purpose = flow.data["purpose"] if flow else "login"
    home = {
        "login": "/login",
        "register": "/register",
        "link": "/account/security",
        "reauth": "/account/security",
    }[purpose]

    def fail(reason: str) -> RedirectResponse:
        response = _back(home, f"error={reason}")
        clear_flow_cookie(response, settings, FLOW_COOKIE)
        return response

    if flow is None:
        return fail("expired")
    if error or not code:
        return fail("cancelled")
    try:
        identity = await client.identify(
            code=code,
            code_verifier=flow.data["verifier"],
            redirect_uri=_redirect_uri(request),
            nonce=flow.data["nonce"],
        )
    except OidcError as exc:
        await audit.record_detached(
            request.app.state.engine,
            request,
            "oauth.failed",
            target="google",
            metadata={"reason": str(exc)[:200]},
        )
        return fail("google")

    linked = (
        await conn.execute(
            text("SELECT * FROM auth_oauth_lookup('google', :sub)"), {"sub": identity.subject}
        )
    ).one_or_none()

    if purpose == "login":
        if linked is None:
            return fail("not_linked")
        await set_rls_context(conn, linked.user_id, linked.role)
        await _touch(conn, linked.user_id)
        # With two-factor on, Google is only the first step.
        response = _back("/login", "mfa")
        if not await begin_second_factor(
            conn,
            response,
            settings,
            user_id=linked.user_id,
            role=linked.role,
            first_factor="google",
        ):
            response = _back("/", "signed-in")
            await sign_in(
                conn,
                request,
                response,
                settings,
                user_id=linked.user_id,
                role=linked.role,
                action="auth.login",
                metadata={"methods": ["google"]},
            )
        clear_flow_cookie(response, settings, FLOW_COOKIE)
        return response

    if purpose == "register":
        try:
            async with conn.begin_nested():
                row = (
                    await conn.execute(
                        text("SELECT * FROM auth_redeem_invite(:t, :email, :name, NULL)"),
                        {
                            "t": bytes.fromhex(flow.data["invite_hash"]),
                            "email": identity.email,
                            "name": identity.name,
                        },
                    )
                ).one_or_none()
                if row is None:
                    return fail("invite_invalid")
                await set_rls_context(conn, row.new_user_id, row.new_user_role)
                await conn.execute(
                    insert(oauth_identities).values(
                        user_id=row.new_user_id,
                        provider="google",
                        subject=identity.subject,
                        email=identity.email,
                        last_used_at=func.now(),
                    )
                )
        except IntegrityError:
            # The email already has an account, or this Google account is linked.
            return fail("already_registered")
        response = _back("/", "welcome")
        await sign_in(
            conn,
            request,
            response,
            settings,
            user_id=row.new_user_id,
            role=row.new_user_role,
            action="auth.registered",
            metadata={"role": row.new_user_role, "via": "google"},
        )
        clear_flow_cookie(response, settings, FLOW_COOKIE)
        return response

    # link / reauth: the same signed-in user who started the flow.
    user = await _signed_in(request, conn, settings)
    if user is None or flow.user_id != user.id:
        return fail("session")

    if purpose == "link":
        if linked is not None:
            return fail("google_in_use" if linked.user_id != user.id else "already_linked")
        try:
            async with conn.begin_nested():
                await conn.execute(
                    insert(oauth_identities).values(
                        user_id=user.id,
                        provider="google",
                        subject=identity.subject,
                        email=identity.email,
                    )
                )
        except IntegrityError:
            return fail("already_linked")
        await audit.record(conn, request, "oauth.linked", user_id=user.id, target="google")
        response = _back("/account/security", "google=linked")
    else:
        if linked is None or linked.user_id != user.id:
            return fail("wrong_account")
        await mark_reauthenticated(conn, user.session_id)
        await audit.record(
            conn, request, "auth.reauth", user_id=user.id, metadata={"method": "google"}
        )
        response = _back("/account/security", "reauth=ok")
    clear_flow_cookie(response, settings, FLOW_COOKIE)
    return response


async def _touch(conn: AsyncConnection, user_id: UUID) -> None:
    await conn.execute(
        update(oauth_identities)
        .where(oauth_identities.c.user_id == user_id)
        .values(last_used_at=func.now())
    )
