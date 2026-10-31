# SPDX-License-Identifier: AGPL-3.0-or-later
"""Short-lived, single-use state for sign-in steps.

A flow (a pending second factor, a WebAuthn challenge, an OAuth round trip)
is identified by a random token held in an httpOnly cookie; the database only
stores the token's hash. Flows live in ``auth_flows``, which the app role can
reach only through the ``auth_flow_*`` SQL functions.
"""

import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from openchart_api.security import new_token, token_hash

Kind = Literal["mfa", "mfa_passkey", "passkey_login", "passkey_register", "reauth_passkey", "oauth"]

# Wrong second-factor codes allowed before the whole sign-in must restart.
MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class Flow:
    user_id: UUID | None
    data: dict[str, Any]


async def start(
    conn: AsyncConnection,
    kind: Kind,
    *,
    user_id: UUID | None,
    data: dict[str, Any],
    ttl_seconds: int,
) -> str:
    """Create a flow and return its token (for the cookie)."""
    token = new_token()
    await conn.execute(
        text("SELECT auth_flow_start(:h, :kind, :user_id, CAST(:data AS jsonb), :ttl)"),
        {
            "h": token_hash(token),
            "kind": kind,
            "user_id": user_id,
            "data": json.dumps(data),
            "ttl": ttl_seconds,
        },
    )
    return token


async def get(conn: AsyncConnection, kind: Kind, token: str | None) -> Flow | None:
    if not token:
        return None
    row = (
        await conn.execute(
            text("SELECT * FROM auth_flow_get(:h, :kind)"), {"h": token_hash(token), "kind": kind}
        )
    ).one_or_none()
    return Flow(row.user_id, row.data) if row else None


async def update(conn: AsyncConnection, kind: Kind, token: str, data: dict[str, Any]) -> bool:
    return bool(
        await conn.scalar(
            text("SELECT auth_flow_set_data(:h, :kind, CAST(:data AS jsonb))"),
            {"h": token_hash(token), "kind": kind, "data": json.dumps(data)},
        )
    )


async def fail(engine: AsyncEngine, kind: Kind, token: str) -> int:
    """Count a failed attempt. Returns attempts left; at 0 the flow is gone.

    Runs in its own transaction: the request that failed is about to be
    rolled back, and the count must survive that.
    """
    async with engine.begin() as conn:
        left = await conn.scalar(
            text("SELECT auth_flow_fail(:h, :kind, :max)"),
            {"h": token_hash(token), "kind": kind, "max": MAX_ATTEMPTS},
        )
    return int(left or 0)


async def take(conn: AsyncConnection, kind: Kind, token: str | None) -> Flow | None:
    """Return the flow and delete it, so it can be used only once."""
    if not token:
        return None
    row = (
        await conn.execute(
            text("SELECT * FROM auth_flow_take(:h, :kind)"), {"h": token_hash(token), "kind": kind}
        )
    ).one_or_none()
    return Flow(row.user_id, row.data) if row else None
