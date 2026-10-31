# SPDX-License-Identifier: AGPL-3.0-or-later
"""Request and response bodies shared by the routes."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from openchart_api.auth import mfa_setup_required
from openchart_api.security import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH

Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Password = Annotated[str, Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)]
# Login accepts any length so old or wrong passwords get a normal "invalid" answer.
AnyPassword = Annotated[str, Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)]
Token = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Me(BaseModel):
    id: UUID
    email: str
    display_name: str
    role: Literal["owner", "admin", "member"]
    # The owner requires two-factor and this user must set it up first.
    mfa_setup_required: bool = False

    @classmethod
    def of(cls, user: object) -> "Me":
        """Build from any object with matching attributes (a row, CurrentUser…)."""
        return cls.model_validate(user, from_attributes=True)

    @classmethod
    async def signed_in(cls, conn: AsyncConnection, user_id: UUID) -> "Me":
        """The newly signed-in user, as /auth/me would report them.
        Expects the RLS context to be the user's."""
        row = (
            await conn.execute(
                text("SELECT id, email, display_name, role FROM users WHERE id = :id"),
                {"id": user_id},
            )
        ).one()
        me = cls.of(row)
        me.mfa_setup_required = await mfa_setup_required(conn, user_id)
        return me


class NewAccount(BaseModel):
    email: Email
    display_name: DisplayName
    password: Password


def too_many_attempts(wait: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many failed attempts. Try again later.",
        headers={"Retry-After": str(wait)},
    )


class SessionInfo(BaseModel):
    id: UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip: str | None
    current: bool
