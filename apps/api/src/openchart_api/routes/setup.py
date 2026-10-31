# SPDX-License-Identifier: AGPL-3.0-or-later
"""First-run setup: create the owner account with the one-time setup token."""

import hmac

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from openchart_api import audit
from openchart_api.auth import SettingsDep, sign_in
from openchart_api.db import Conn
from openchart_api.routes.schemas import Me, NewAccount, Token, too_many_attempts
from openchart_api.security import hash_password

router = APIRouter(prefix="/setup", tags=["setup"])


class SetupStatus(BaseModel):
    needs_setup: bool


class SetupRequest(NewAccount):
    setup_token: Token


@router.get("/status")
async def setup_status(conn: Conn) -> SetupStatus:
    return SetupStatus(needs_setup=bool(await conn.scalar(text("SELECT auth_needs_setup()"))))


@router.post("", status_code=status.HTTP_201_CREATED, responses={403: {}, 409: {}, 429: {}})
async def create_owner(
    body: SetupRequest, request: Request, response: Response, conn: Conn, settings: SettingsDep
) -> Me:
    expected: str | None = request.app.state.setup_token
    if expected is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup is already complete")
    limiter = request.app.state.failure_limiter
    ip = audit.client_ip(request)
    if wait := limiter.retry_after(ip, "setup"):
        raise too_many_attempts(wait)
    if not hmac.compare_digest(body.setup_token.encode(), expected.encode()):
        limiter.record_failure(ip, "setup")
        await audit.record_detached(request.app.state.engine, request, "setup.token_rejected")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Setup token is not valid")

    user_id = await conn.scalar(
        text("SELECT auth_bootstrap_owner(:email, :name, :hash)"),
        {
            "email": body.email,
            "name": body.display_name,
            "hash": await hash_password(body.password),
        },
    )
    if user_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup is already complete")

    await sign_in(
        conn,
        request,
        response,
        settings,
        user_id=user_id,
        role="owner",
        action="setup.owner_created",
    )
    request.app.state.setup_token = None
    return Me(id=user_id, email=body.email, display_name=body.display_name, role="owner")
