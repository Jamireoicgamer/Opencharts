# SPDX-License-Identifier: AGPL-3.0-or-later
"""First-run setup: create the owner account with the one-time setup token."""

import hmac
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import text

from openchart_api import audit
from openchart_api.auth import SettingsDep, start_session
from openchart_api.db import Conn
from openchart_api.routes.schemas import Me, NewAccount
from openchart_api.security import hash_password

router = APIRouter(prefix="/setup", tags=["setup"])


class SetupStatus(BaseModel):
    needs_setup: bool


class SetupRequest(NewAccount):
    setup_token: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]


@router.get("/status")
async def setup_status(conn: Conn) -> SetupStatus:
    return SetupStatus(needs_setup=bool(await conn.scalar(text("SELECT auth_needs_setup()"))))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_owner(
    body: SetupRequest, request: Request, response: Response, conn: Conn, settings: SettingsDep
) -> Me:
    expected: str | None = request.app.state.setup_token
    if expected is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup is already complete")
    if not hmac.compare_digest(body.setup_token.encode(), expected.encode()):
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

    await start_session(conn, request, response, settings, user_id, "owner")
    await audit.record(conn, request, "setup.owner_created", user_id=user_id, target=body.email)
    request.app.state.setup_token = None
    return Me(id=user_id, email=body.email, display_name=body.display_name, role="owner")
