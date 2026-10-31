# SPDX-License-Identifier: AGPL-3.0-or-later
"""Second-factor sign-in steps, passwordless passkey sign-in and re-authentication."""

from dataclasses import dataclass
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection

from openchart_api import audit, flows, mfa, passkeys
from openchart_api.auth import (
    SessionUser,
    SettingsDep,
    clear_flow_cookie,
    mark_reauthenticated,
    set_flow_cookie,
    sign_in,
)
from openchart_api.config import Settings
from openchart_api.db import Conn, set_rls_context
from openchart_api.routes.schemas import AnyPassword, Me, too_many_attempts
from openchart_api.security import verify_password
from openchart_api.tables import webauthn_credentials

router = APIRouter(prefix="/auth", tags=["auth"])

MFA_COOKIE = "oc_mfa"
FLOW_COOKIE = "oc_flow"
MFA_SECONDS = 300

Method = Literal["totp", "passkey", "recovery"]
Credential = Annotated[dict[str, Any], Field()]


class MfaRequired(BaseModel):
    mfa_required: Literal[True] = True
    methods: list[Method]


class CodeRequest(BaseModel):
    code: Annotated[str, Field(min_length=1, max_length=32)]


class CredentialRequest(BaseModel):
    credential: Credential


class PasswordRequest(BaseModel):
    password: AnyPassword


class Providers(BaseModel):
    google: bool


# Starting the second-factor step (used by password and Google sign-in) ----------


async def begin_second_factor(
    conn: AsyncConnection,
    response: Response,
    settings: Settings,
    *,
    user_id: UUID,
    role: str,
    first_factor: str,
) -> MfaRequired | None:
    """If the user has two-factor, start the second step instead of signing in.

    Expects the RLS context to be the user's. Returns None when no second
    factor is needed.
    """
    methods = await mfa.methods(conn, user_id)
    if not methods.has_second_factor:
        return None
    available: list[Method] = []
    if methods.totp:
        available.append("totp")
    if methods.passkeys:
        available.append("passkey")
    if methods.recovery_codes_left:
        available.append("recovery")
    token = await flows.start(
        conn,
        "mfa",
        user_id=user_id,
        data={"role": role, "first": first_factor, "methods": available},
        ttl_seconds=MFA_SECONDS,
    )
    set_flow_cookie(response, settings, MFA_COOKIE, token, MFA_SECONDS)
    return MfaRequired(methods=available)


@dataclass(frozen=True)
class PendingSignIn:
    token: str
    user_id: UUID
    role: str
    data: dict[str, Any]


async def _mfa_flow(conn: AsyncConnection, request: Request) -> PendingSignIn:
    token = request.cookies.get(MFA_COOKIE) or ""
    flow = await flows.get(conn, "mfa", token)
    if flow is None or flow.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in step expired. Start again.")
    await set_rls_context(conn, flow.user_id, flow.data["role"])
    return PendingSignIn(token, flow.user_id, flow.data["role"], flow.data)


async def _check_limit(request: Request, user_id: UUID) -> None:
    if wait := request.app.state.failure_limiter.retry_after(
        audit.client_ip(request), f"mfa:{user_id}"
    ):
        raise too_many_attempts(wait)


async def _second_factor_failed(request: Request, pending: PendingSignIn) -> HTTPException:
    request.app.state.failure_limiter.record_failure(
        audit.client_ip(request), f"mfa:{pending.user_id}"
    )
    left = await flows.fail(request.app.state.engine, "mfa", pending.token)
    await audit.record_detached(
        request.app.state.engine,
        request,
        "auth.mfa_failed",
        user_id=pending.user_id,
        role=pending.role,
    )
    if left == 0:
        return HTTPException(status.HTTP_401_UNAUTHORIZED, "Too many wrong codes. Sign in again.")
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "That code is not right. Try again.")


async def _finish_second_factor(
    conn: AsyncConnection,
    request: Request,
    response: Response,
    settings: Settings,
    token: str,
    method: Method,
) -> Me:
    flow = await flows.take(conn, "mfa", token)
    if flow is None or flow.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in step expired. Start again.")
    clear_flow_cookie(response, settings, MFA_COOKIE)
    request.app.state.failure_limiter.reset(audit.client_ip(request), f"mfa:{flow.user_id}")
    await sign_in(
        conn,
        request,
        response,
        settings,
        user_id=flow.user_id,
        role=flow.data["role"],
        action="auth.login",
        metadata={"methods": [flow.data["first"], method]},
    )
    return await Me.signed_in(conn, flow.user_id)


# Second-factor step ----------------------------------------------------------------


@router.get("/mfa")
async def pending_second_factor(request: Request, conn: Conn) -> MfaRequired:
    """The methods offered for the sign-in in progress (e.g. after Google)."""
    pending = await _mfa_flow(conn, request)
    return MfaRequired(methods=pending.data["methods"])


@router.post("/mfa/totp", responses={401: {}, 429: {}})
async def second_factor_totp(
    body: CodeRequest, request: Request, response: Response, conn: Conn, settings: SettingsDep
) -> Me:
    pending = await _mfa_flow(conn, request)
    await _check_limit(request, pending.user_id)
    if not await mfa.verify_totp(conn, settings.master_key_bytes, pending.user_id, body.code):
        raise await _second_factor_failed(request, pending)
    return await _finish_second_factor(conn, request, response, settings, pending.token, "totp")


@router.post("/mfa/recovery", responses={401: {}, 429: {}})
async def second_factor_recovery(
    body: CodeRequest, request: Request, response: Response, conn: Conn, settings: SettingsDep
) -> Me:
    pending = await _mfa_flow(conn, request)
    await _check_limit(request, pending.user_id)
    if not await mfa.use_recovery_code(conn, settings.master_key_bytes, pending.user_id, body.code):
        raise await _second_factor_failed(request, pending)
    await audit.record(conn, request, "mfa.recovery_code_used", user_id=pending.user_id)
    return await _finish_second_factor(conn, request, response, settings, pending.token, "recovery")


async def _credential_ids(conn: AsyncConnection, user_id: UUID) -> list[bytes]:
    rows = await conn.scalars(
        select(webauthn_credentials.c.credential_id).where(
            webauthn_credentials.c.user_id == user_id
        )
    )
    return list(rows)


@router.post("/mfa/passkey/options")
async def second_factor_passkey_options(
    request: Request, conn: Conn, settings: SettingsDep
) -> dict[str, Any]:
    pending = await _mfa_flow(conn, request)
    allow = await _credential_ids(conn, pending.user_id)
    if not allow:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No passkeys on this account")
    options, challenge = passkeys.authentication_options(
        passkeys.relying_party(request, settings), allow=allow, user_verification=False
    )
    await flows.update(conn, "mfa", pending.token, {"challenge": challenge})
    return options


async def _verify_own_passkey(
    conn: AsyncConnection,
    request: Request,
    settings: Settings,
    *,
    user_id: UUID,
    credential: dict[str, Any],
    challenge: str | None,
    user_verification: bool,
) -> bool:
    """Verify an assertion from one of ``user_id``'s passkeys and record its use."""
    if not challenge:
        return False
    try:
        credential_id = passkeys.credential_id_of(credential)
    except passkeys.PasskeyError:
        return False
    row = (
        await conn.execute(
            select(webauthn_credentials).where(
                webauthn_credentials.c.user_id == user_id,
                webauthn_credentials.c.credential_id == credential_id,
            )
        )
    ).one_or_none()
    if row is None:
        return False
    try:
        new_count = passkeys.verify_authentication(
            passkeys.relying_party(request, settings),
            credential,
            challenge,
            public_key=row.public_key,
            sign_count=row.sign_count,
            user_verification=user_verification,
        )
    except passkeys.PasskeyError:
        return False
    await conn.execute(
        update(webauthn_credentials)
        .where(webauthn_credentials.c.id == row.id)
        .values(sign_count=new_count, last_used_at=func.now())
    )
    return True


@router.post("/mfa/passkey", responses={401: {}, 429: {}})
async def second_factor_passkey(
    body: CredentialRequest,
    request: Request,
    response: Response,
    conn: Conn,
    settings: SettingsDep,
) -> Me:
    pending = await _mfa_flow(conn, request)
    await _check_limit(request, pending.user_id)
    if not await _verify_own_passkey(
        conn,
        request,
        settings,
        user_id=pending.user_id,
        credential=body.credential,
        challenge=pending.data.get("challenge"),
        user_verification=False,
    ):
        raise await _second_factor_failed(request, pending)
    return await _finish_second_factor(conn, request, response, settings, pending.token, "passkey")


# Passwordless passkey sign-in ---------------------------------------------------------


@router.post("/passkey/options")
async def passkey_sign_in_options(
    request: Request, response: Response, conn: Conn, settings: SettingsDep
) -> dict[str, Any]:
    options, challenge = passkeys.authentication_options(
        passkeys.relying_party(request, settings), allow=None, user_verification=True
    )
    token = await flows.start(
        conn,
        "passkey_login",
        user_id=None,
        data={"challenge": challenge},
        ttl_seconds=passkeys.CEREMONY_SECONDS,
    )
    set_flow_cookie(response, settings, FLOW_COOKIE, token, passkeys.CEREMONY_SECONDS)
    return options


@router.post("/passkey", responses={401: {}, 429: {}})
async def passkey_sign_in(
    body: CredentialRequest,
    request: Request,
    response: Response,
    conn: Conn,
    settings: SettingsDep,
) -> Me:
    limiter = request.app.state.failure_limiter
    ip = audit.client_ip(request)
    if wait := limiter.retry_after(ip, "passkey"):
        raise too_many_attempts(wait)
    flow = await flows.take(conn, "passkey_login", request.cookies.get(FLOW_COOKIE))
    clear_flow_cookie(response, settings, FLOW_COOKIE)
    rejected = HTTPException(status.HTTP_401_UNAUTHORIZED, "That passkey could not be used here")
    if flow is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in step expired. Start again.")
    try:
        credential_id = passkeys.credential_id_of(body.credential)
    except passkeys.PasskeyError:
        limiter.record_failure(ip, "passkey")
        raise rejected from None
    owner = (
        await conn.execute(text("SELECT * FROM auth_passkey_lookup(:c)"), {"c": credential_id})
    ).one_or_none()
    if owner is None:
        limiter.record_failure(ip, "passkey")
        raise rejected
    await set_rls_context(conn, owner.user_id, owner.role)
    # User verification (PIN, fingerprint, face) makes the passkey a complete
    # two-factor sign-in on its own.
    if not await _verify_own_passkey(
        conn,
        request,
        settings,
        user_id=owner.user_id,
        credential=body.credential,
        challenge=flow.data.get("challenge"),
        user_verification=True,
    ):
        limiter.record_failure(ip, "passkey")
        raise rejected
    await sign_in(
        conn,
        request,
        response,
        settings,
        user_id=owner.user_id,
        role=owner.role,
        action="auth.login",
        metadata={"methods": ["passkey"]},
    )
    return await Me.signed_in(conn, owner.user_id)


# Re-authentication for sensitive changes ---------------------------------------------


@router.post("/reauth", status_code=status.HTTP_204_NO_CONTENT, responses={401: {}, 429: {}})
async def reauthenticate(
    body: PasswordRequest, user: SessionUser, request: Request, conn: Conn
) -> None:
    limiter = request.app.state.failure_limiter
    ip = audit.client_ip(request)
    subject = f"reauth:{user.id}"
    if wait := limiter.retry_after(ip, subject):
        raise too_many_attempts(wait)
    row = (
        await conn.execute(text("SELECT * FROM auth_login_lookup(:email)"), {"email": user.email})
    ).one_or_none()
    if row is None or row.password_hash is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This account has no password. Use a passkey or Google."
        )
    if not await verify_password(row.password_hash, body.password):
        limiter.record_failure(ip, subject)
        await audit.record_detached(
            request.app.state.engine, request, "auth.reauth_failed", user_id=user.id, role=user.role
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That password is not right")
    limiter.reset(ip, subject)
    await mark_reauthenticated(conn, user.session_id)
    await audit.record(
        conn, request, "auth.reauth", user_id=user.id, metadata={"method": "password"}
    )


@router.post("/reauth/passkey/options")
async def reauthenticate_passkey_options(
    user: SessionUser, request: Request, response: Response, conn: Conn, settings: SettingsDep
) -> dict[str, Any]:
    allow = await _credential_ids(conn, user.id)
    if not allow:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No passkeys on this account")
    options, challenge = passkeys.authentication_options(
        passkeys.relying_party(request, settings), allow=allow, user_verification=True
    )
    token = await flows.start(
        conn,
        "reauth_passkey",
        user_id=user.id,
        data={"challenge": challenge},
        ttl_seconds=passkeys.CEREMONY_SECONDS,
    )
    set_flow_cookie(response, settings, FLOW_COOKIE, token, passkeys.CEREMONY_SECONDS)
    return options


@router.post("/reauth/passkey", status_code=status.HTTP_204_NO_CONTENT, responses={401: {}})
async def reauthenticate_passkey(
    body: CredentialRequest,
    user: SessionUser,
    request: Request,
    response: Response,
    conn: Conn,
    settings: SettingsDep,
) -> None:
    flow = await flows.take(conn, "reauth_passkey", request.cookies.get(FLOW_COOKIE))
    clear_flow_cookie(response, settings, FLOW_COOKIE)
    if (
        flow is None
        or flow.user_id != user.id
        or not await _verify_own_passkey(
            conn,
            request,
            settings,
            user_id=user.id,
            credential=body.credential,
            challenge=flow.data.get("challenge"),
            user_verification=True,
        )
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That passkey could not be verified")
    await mark_reauthenticated(conn, user.session_id)
    await audit.record(
        conn, request, "auth.reauth", user_id=user.id, metadata={"method": "passkey"}
    )


@router.get("/providers")
async def providers(settings: SettingsDep) -> Providers:
    """Which optional sign-in methods this server offers."""
    return Providers(google=settings.google_enabled)
