# SPDX-License-Identifier: AGPL-3.0-or-later
"""Account security settings: password, authenticator app, recovery codes,
passkeys and Google, plus the owner's "require two-factor" switch.

Changes need a recent sign-in (``RecentAuth``). Users who still have to set
up two-factor can use all of this (``SessionUser``).
"""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from openchart_api import audit, flows, mfa, passkeys
from openchart_api.auth import (
    CurrentUser,
    RecentAuth,
    SessionUser,
    SettingsDep,
    clear_flow_cookie,
    set_flow_cookie,
)
from openchart_api.config import Settings
from openchart_api.db import Conn
from openchart_api.routes.mfa_login import FLOW_COOKIE, CredentialRequest
from openchart_api.routes.schemas import Password, too_many_attempts
from openchart_api.security import hash_password
from openchart_api.tables import (
    oauth_identities,
    server_settings,
    sessions,
    users,
    webauthn_credentials,
)

router = APIRouter(prefix="/account/security", tags=["security"])
admin_router = APIRouter(prefix="/admin/settings", tags=["admin"])

PasskeyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class PasskeyInfo(BaseModel):
    id: UUID
    name: str
    backed_up: bool
    created_at: datetime
    last_used_at: datetime | None


class SecurityStatus(BaseModel):
    has_password: bool
    totp: bool
    passkeys: list[PasskeyInfo]
    google_email: str | None
    recovery_codes_left: int
    require_mfa: bool
    google_available: bool


class TotpSetup(BaseModel):
    secret: str
    uri: str
    qr_svg: str


class RecoveryCodes(BaseModel):
    # Shown once. None when the user already has unused codes.
    recovery_codes: list[str] | None


class NewPasskey(CredentialRequest):
    name: PasskeyName = "Passkey"


class PasskeyAdded(RecoveryCodes):
    id: UUID


class Rename(BaseModel):
    name: PasskeyName


class NewPassword(BaseModel):
    new_password: Password


class CodeBody(BaseModel):
    code: Annotated[str, Field(min_length=1, max_length=32)]


class ServerSettings(BaseModel):
    require_mfa: bool


async def _require_mfa(conn: AsyncConnection) -> bool:
    return bool(await conn.scalar(select(server_settings.c.require_mfa)))


async def _issue_codes_if_first_factor(
    conn: AsyncConnection, settings: Settings, request: Request, user: CurrentUser, had_factor: bool
) -> list[str] | None:
    """Recovery codes come with the first second factor a user sets up."""
    if had_factor:
        return None
    codes = await mfa.replace_recovery_codes(conn, settings.master_key_bytes, user.id)
    await audit.record(conn, request, "mfa.recovery_codes_issued", user_id=user.id)
    return codes


async def _after_factor_removed(conn: AsyncConnection, user_id: UUID) -> None:
    if not (await mfa.methods(conn, user_id)).has_second_factor:
        await mfa.remove_recovery_codes(conn, user_id)


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


@router.get("")
async def security_status(user: SessionUser, conn: Conn, settings: SettingsDep) -> SecurityStatus:
    m = await mfa.methods(conn, user.id)
    rows = await conn.execute(
        select(
            webauthn_credentials.c.id,
            webauthn_credentials.c.name,
            webauthn_credentials.c.backed_up,
            webauthn_credentials.c.created_at,
            webauthn_credentials.c.last_used_at,
        ).order_by(webauthn_credentials.c.created_at)
    )
    google_email = await conn.scalar(select(oauth_identities.c.email))
    return SecurityStatus(
        has_password=m.has_password,
        totp=m.totp,
        passkeys=[PasskeyInfo.model_validate(r, from_attributes=True) for r in rows],
        google_email=google_email,
        recovery_codes_left=m.recovery_codes_left,
        require_mfa=await _require_mfa(conn),
        google_available=settings.google_enabled,
    )


# Password ---------------------------------------------------------------------------


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def set_password(body: NewPassword, user: RecentAuth, request: Request, conn: Conn) -> None:
    await conn.execute(
        update(users)
        .where(users.c.id == user.id)
        .values(password_hash=await hash_password(body.new_password))
    )
    # Anyone holding another session (perhaps the reason for the change) is signed out.
    await conn.execute(
        update(sessions)
        .where(sessions.c.id != user.session_id, sessions.c.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )
    await audit.record(conn, request, "auth.password_changed", user_id=user.id)


# Authenticator app ---------------------------------------------------------------------


@router.post("/totp/setup")
async def totp_setup(user: RecentAuth, conn: Conn, settings: SettingsDep) -> TotpSetup:
    if (await mfa.methods(conn, user.id)).totp:
        raise _conflict("An authenticator app is already set up. Remove it first.")
    enrolment = await mfa.begin_totp(conn, settings.master_key_bytes, user.id, user.email)
    return TotpSetup(secret=enrolment.secret, uri=enrolment.uri, qr_svg=enrolment.qr_svg)


@router.post("/totp/confirm", responses={400: {}, 429: {}})
async def totp_confirm(
    body: CodeBody, user: SessionUser, request: Request, conn: Conn, settings: SettingsDep
) -> RecoveryCodes:
    limiter = request.app.state.failure_limiter
    ip, subject = audit.client_ip(request), f"totp-confirm:{user.id}"
    if wait := limiter.retry_after(ip, subject):
        raise too_many_attempts(wait)
    had_factor = (await mfa.methods(conn, user.id)).has_second_factor
    if not await mfa.verify_totp(
        conn, settings.master_key_bytes, user.id, body.code, confirming=True
    ):
        limiter.record_failure(ip, subject)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That code is not right. Check your phone's clock too."
        )
    await audit.record(conn, request, "mfa.totp_enabled", user_id=user.id)
    codes = await _issue_codes_if_first_factor(conn, settings, request, user, had_factor)
    return RecoveryCodes(recovery_codes=codes)


@router.delete("/totp", status_code=status.HTTP_204_NO_CONTENT)
async def totp_remove(user: RecentAuth, request: Request, conn: Conn) -> None:
    m = await mfa.methods(conn, user.id)
    if not m.totp:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No authenticator app is set up")
    if await _require_mfa(conn) and m.passkeys == 0:
        raise _conflict("Two-factor is required on this server. Add a passkey first.")
    await mfa.remove_totp(conn, user.id)
    await _after_factor_removed(conn, user.id)
    await audit.record(conn, request, "mfa.totp_disabled", user_id=user.id)


@router.post("/recovery-codes")
async def recovery_codes_regenerate(
    user: RecentAuth, request: Request, conn: Conn, settings: SettingsDep
) -> RecoveryCodes:
    if not (await mfa.methods(conn, user.id)).has_second_factor:
        raise _conflict("Set up two-factor first")
    codes = await mfa.replace_recovery_codes(conn, settings.master_key_bytes, user.id)
    await audit.record(conn, request, "mfa.recovery_codes_issued", user_id=user.id)
    return RecoveryCodes(recovery_codes=codes)


# Passkeys ----------------------------------------------------------------------------------


@router.post("/passkeys/options")
async def passkey_options(
    user: RecentAuth, request: Request, response: Response, conn: Conn, settings: SettingsDep
) -> dict[str, Any]:
    existing = list(await conn.scalars(select(webauthn_credentials.c.credential_id)))
    options, challenge = passkeys.registration_options(
        passkeys.relying_party(request, settings),
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        existing=existing,
    )
    token = await flows.start(
        conn,
        "passkey_register",
        user_id=user.id,
        data={"challenge": challenge},
        ttl_seconds=passkeys.CEREMONY_SECONDS,
    )
    set_flow_cookie(response, settings, FLOW_COOKIE, token, passkeys.CEREMONY_SECONDS)
    return options


@router.post("/passkeys", status_code=status.HTTP_201_CREATED, responses={400: {}, 409: {}})
async def passkey_add(
    body: NewPasskey,
    user: RecentAuth,
    request: Request,
    response: Response,
    conn: Conn,
    settings: SettingsDep,
) -> PasskeyAdded:
    flow = await flows.take(conn, "passkey_register", request.cookies.get(FLOW_COOKIE))
    clear_flow_cookie(response, settings, FLOW_COOKIE)
    if flow is None or flow.user_id != user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Passkey setup expired. Try again.")
    try:
        new = passkeys.verify_registration(
            passkeys.relying_party(request, settings), body.credential, flow.data["challenge"]
        )
    except passkeys.PasskeyError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That passkey could not be verified"
        ) from None
    had_factor = (await mfa.methods(conn, user.id)).has_second_factor
    try:
        async with conn.begin_nested():
            result = await conn.execute(
                insert(webauthn_credentials)
                .values(
                    user_id=user.id,
                    credential_id=new.credential_id,
                    public_key=new.public_key,
                    sign_count=new.sign_count,
                    transports=new.transports,
                    name=body.name,
                    backed_up=new.backed_up,
                )
                .returning(webauthn_credentials.c.id)
            )
            passkey_id: UUID = result.scalar_one()
    except IntegrityError:
        raise _conflict("This passkey is already registered") from None
    await audit.record(
        conn,
        request,
        "passkey.added",
        user_id=user.id,
        target=str(passkey_id),
        metadata={"name": body.name},
    )
    codes = await _issue_codes_if_first_factor(conn, settings, request, user, had_factor)
    return PasskeyAdded(id=passkey_id, recovery_codes=codes)


@router.patch("/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def passkey_rename(passkey_id: UUID, body: Rename, user: SessionUser, conn: Conn) -> None:
    result = await conn.execute(
        update(webauthn_credentials)
        .where(webauthn_credentials.c.id == passkey_id)
        .values(name=body.name)
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Passkey not found")


@router.delete("/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def passkey_remove(passkey_id: UUID, user: RecentAuth, request: Request, conn: Conn) -> None:
    m = await mfa.methods(conn, user.id)
    exists = await conn.scalar(
        select(webauthn_credentials.c.id).where(webauthn_credentials.c.id == passkey_id)
    )
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Passkey not found")
    if m.sign_in_methods <= 1:
        raise _conflict("This is your only way to sign in. Add another one first.")
    if await _require_mfa(conn) and not m.totp and m.passkeys == 1:
        raise _conflict("Two-factor is required on this server. Set up another method first.")
    await conn.execute(delete(webauthn_credentials).where(webauthn_credentials.c.id == passkey_id))
    await _after_factor_removed(conn, user.id)
    await audit.record(conn, request, "passkey.removed", user_id=user.id, target=str(passkey_id))


# Google -------------------------------------------------------------------------------------


@router.delete("/google", status_code=status.HTTP_204_NO_CONTENT)
async def google_unlink(user: RecentAuth, request: Request, conn: Conn) -> None:
    m = await mfa.methods(conn, user.id)
    if not m.google:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Google account is linked")
    if m.sign_in_methods <= 1:
        raise _conflict("This is your only way to sign in. Set a password or add a passkey first.")
    await conn.execute(delete(oauth_identities).where(oauth_identities.c.user_id == user.id))
    await audit.record(conn, request, "oauth.unlinked", user_id=user.id, target="google")


# Server-wide settings (owner) -------------------------------------------------------------------


@admin_router.get("")
async def get_server_settings(user: SessionUser, conn: Conn) -> ServerSettings:
    return ServerSettings(require_mfa=await _require_mfa(conn))


@admin_router.put("")
async def put_server_settings(
    body: ServerSettings, user: RecentAuth, request: Request, conn: Conn
) -> ServerSettings:
    if user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can change this")
    if body.require_mfa and not (await mfa.methods(conn, user.id)).has_second_factor:
        raise _conflict("Set up two-factor on your own account first")
    await conn.execute(
        update(server_settings).values(require_mfa=body.require_mfa, updated_at=func.now())
    )
    await audit.record(
        conn,
        request,
        "settings.require_mfa_changed",
        user_id=user.id,
        metadata={"require_mfa": body.require_mfa},
    )
    return body
