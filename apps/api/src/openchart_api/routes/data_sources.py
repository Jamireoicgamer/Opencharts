# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where prices come from: everyone can see which sources are active;
owners and admins choose them, accept terms and set provider keys.

Changes need a recent sign-in and are audited. Keys are sealed on arrival
and never returned, only a short hint.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select, update

from openchart_api import audit, vault
from openchart_api.auth import RecentAuth, User
from openchart_api.db import Conn
from openchart_api.market.hub import Hub
from openchart_api.market.sources import (
    LABELS,
    NEEDS_KEY,
    NEEDS_TERMS,
    SourceConfig,
    config_from_row,
    seal_key,
)
from openchart_api.tables import data_sources

router = APIRouter(tags=["data-sources"])

Provider = Literal["coinbase", "kraken", "yahoo", "twelvedata"]

COVERAGE = {
    "coinbase": "Crypto, real-time",
    "kraken": "Crypto, real-time (backup for Coinbase)",
    "yahoo": "UK and US stocks, ETFs, indices, FX and crypto; delayed",
    "twelvedata": "US stocks and ETFs, FX, crypto (UK shares need a paid plan)",
}


class SourceInfo(BaseModel):
    provider: Provider
    label: str
    coverage: str
    active: bool
    # The rest is only filled in for owners and admins.
    enabled: bool | None = None
    priority: int | None = None
    needs_terms: bool = False
    terms_accepted: bool | None = None
    needs_key: bool = False
    key_hint: str | None = None


class SourceChange(BaseModel):
    enabled: bool | None = None
    priority: Annotated[int, Field(ge=1, le=100)] | None = None
    accept_terms: bool | None = None
    api_key: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=200)]
        | None
    ) = None
    remove_key: bool = False


def _hub(request: Request) -> Hub:
    hub: Hub = request.app.state.hub
    return hub


@router.get("/data-sources")
async def list_sources(request: Request, user: User, conn: Conn) -> list[SourceInfo]:
    active = {p.name for p in _hub(request).router.providers}
    rows = {r.provider: r for r in await conn.execute(select(data_sources))}
    result = []
    for provider in LABELS:
        info = SourceInfo(
            provider=provider,
            label=LABELS[provider],
            coverage=COVERAGE[provider],
            active=provider in active,
            needs_terms=provider in NEEDS_TERMS,
            needs_key=provider in NEEDS_KEY,
        )
        # RLS only returns rows to owners and admins.
        if row := rows.get(provider):
            info.enabled = row.enabled
            info.priority = row.priority
            info.terms_accepted = row.tos_accepted_at is not None
            info.key_hint = (row.key_hint or "set") if row.key_ciphertext is not None else None
        result.append(info)
    if rows:
        result.sort(key=lambda s: s.priority or 0)
    return result


@router.put("/admin/data-sources/{provider}")
async def change_source(
    provider: Provider, body: SourceChange, user: RecentAuth, request: Request, conn: Conn
) -> list[SourceInfo]:
    if user.role not in ("owner", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")
    settings = request.app.state.settings
    values: dict[str, object] = {"updated_at": func.now()}
    changes: dict[str, object] = {}
    if body.enabled is not None:
        values["enabled"] = changes["enabled"] = body.enabled
    if body.priority is not None:
        values["priority"] = changes["priority"] = body.priority
    if body.accept_terms is not None:
        if provider not in NEEDS_TERMS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "This source has no terms to accept"
            )
        values["tos_accepted_at"] = func.now() if body.accept_terms else None
        values["tos_accepted_by"] = user.id if body.accept_terms else None
        changes["terms_accepted"] = body.accept_terms
    if body.api_key is not None or body.remove_key:
        if provider not in NEEDS_KEY:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This source takes no key")
        if body.api_key is not None:
            sealed = seal_key(settings.master_key_bytes, provider, body.api_key)
            values |= {
                "key_ciphertext": sealed.ciphertext,
                "key_nonce": sealed.nonce,
                "key_wrapped_dek": sealed.wrapped_dek,
                "key_dek_nonce": sealed.dek_nonce,
                "key_version": sealed.key_version,
                "key_hint": vault.hint(body.api_key),
            }
            changes["key"] = "set"
        else:
            values |= dict.fromkeys(
                ("key_ciphertext", "key_nonce", "key_wrapped_dek", "key_dek_nonce", "key_version")
            ) | {"key_hint": ""}
            changes["key"] = "removed"
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing to change")
    result = await conn.execute(
        update(data_sources).where(data_sources.c.provider == provider).values(values)
    )
    if result.rowcount != 1:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown source")
    await audit.record(
        conn, request, "data_source.changed", user_id=user.id, target=provider, metadata=changes
    )
    # Apply at once, from what this transaction now sees.
    await _hub(request).reload_sources(await _configs(conn, settings.master_key_bytes))
    return await list_sources(request, user, conn)


async def _configs(conn: Conn, master_key: bytes) -> list[SourceConfig]:
    rows = await conn.execute(
        select(data_sources).where(data_sources.c.enabled).order_by(data_sources.c.priority)
    )
    return [config_from_row(r, r.tos_accepted_at is not None, master_key) for r in rows]
