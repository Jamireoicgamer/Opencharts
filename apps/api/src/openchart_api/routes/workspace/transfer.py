# SPDX-License-Identifier: AGPL-3.0-or-later
"""Moving workspace data in and out: a full export, and importing what the
V4.1 prototype saved in the browser."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import insert, select, update

from openchart_api import audit, legacy_import
from openchart_api.auth import User
from openchart_api.db import Conn
from openchart_api.routes.workspace import preferences as prefs_module
from openchart_api.routes.workspace.alerts import list_alerts
from openchart_api.routes.workspace.positions import list_positions
from openchart_api.routes.workspace.research import ensure_research
from openchart_api.tables import (
    alerts,
    instruments,
    positions,
    research_notes,
    research_tasks,
    thesis_versions,
    watchlist_items,
)

router = APIRouter(tags=["transfer"])

IMPORT_NOTE = "Imported from the prototype"


class ImportResult(BaseModel):
    watchlist: int
    theses: int
    research: int
    positions: int
    alerts: int
    preferences: bool
    skipped_symbols: list[str]


@router.get("/export")
async def export_workspace(user: User, request: Request, conn: Conn) -> dict[str, Any]:
    """Everything in the user's workspace, as JSON they can keep."""
    watch = list(
        await conn.scalars(
            select(watchlist_items.c.instrument_id).order_by(watchlist_items.c.position)
        )
    )
    theses: dict[str, list[dict[str, Any]]] = {}
    for row in await conn.execute(select(thesis_versions).order_by(thesis_versions.c.created_at)):
        version = dict(row._mapping)
        for key in ("id", "user_id", "instrument_id"):
            version.pop(key)
        theses.setdefault(row.instrument_id, []).append(version)
    research: dict[str, dict[str, Any]] = {
        r.instrument_id: {"notes": r.body, "tasks": []}
        for r in await conn.execute(select(research_notes))
    }
    for t in await conn.execute(select(research_tasks).order_by(research_tasks.c.position)):
        research.setdefault(t.instrument_id, {"notes": "", "tasks": []})["tasks"].append(
            {"label": t.label, "done": t.done}
        )
    await audit.record(conn, request, "workspace.exported", user_id=user.id)
    return {
        "format": "openchart-export",
        "version": 1,
        "exported_at": datetime.now(UTC),
        "account": {"email": user.email, "display_name": user.display_name},
        "preferences": (await prefs_module.load(conn)).model_dump(),
        "watchlist": watch,
        "theses": theses,
        "research": research,
        "positions": [p.model_dump() for p in await list_positions(user, conn)],
        "alerts": [a.model_dump() for a in await list_alerts(user, conn)],
    }


@router.post("/import/legacy")
async def import_legacy(
    payload: dict[str, Any], user: User, request: Request, conn: Conn
) -> ImportResult:
    """Merge data from the prototype. Importing the same data twice adds nothing."""
    catalogue = {
        r.symbol.upper(): r.id
        for r in await conn.execute(select(instruments.c.id, instruments.c.symbol))
    }
    try:
        data = legacy_import.parse(payload, catalogue)
    except legacy_import.LegacyFormatError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None

    added_watch = 0
    existing = set(await conn.scalars(select(watchlist_items.c.instrument_id)))
    top = len(existing)
    for iid in data.watchlist:
        if iid not in existing:
            await conn.execute(
                insert(watchlist_items).values(user_id=user.id, instrument_id=iid, position=top)
            )
            existing.add(iid)
            top += 1
            added_watch += 1

    added_theses = 0
    for iid, versions in data.theses.items():
        seen = set(
            await conn.scalars(
                select(thesis_versions.c.created_at).where(thesis_versions.c.instrument_id == iid)
            )
        )
        for v in versions:
            if v.created_at not in seen:
                await conn.execute(
                    insert(thesis_versions).values(user_id=user.id, instrument_id=iid, **v.__dict__)
                )
                added_theses += 1

    touched_research = 0
    for iid in set(data.research_notes) | set(data.research_done):
        await ensure_research(conn, user.id, iid)
        if notes := data.research_notes.get(iid):
            current = await conn.scalar(
                select(research_notes.c.body).where(research_notes.c.instrument_id == iid)
            )
            if current and notes not in current:
                notes = f"{current}\n\n— {IMPORT_NOTE} —\n{notes}"
            if notes != current:
                await conn.execute(
                    update(research_notes)
                    .where(research_notes.c.instrument_id == iid)
                    .values(body=notes[:50000])
                )
        if done := data.research_done.get(iid):
            # The prototype stored which of its three default tasks were done.
            task_ids = (
                await conn.scalars(
                    select(research_tasks.c.id)
                    .where(research_tasks.c.instrument_id == iid)
                    .order_by(research_tasks.c.position)
                )
            ).all()
            chosen = [task_ids[i] for i in done if i < len(task_ids)]
            if chosen:
                await conn.execute(
                    update(research_tasks).where(research_tasks.c.id.in_(chosen)).values(done=True)
                )
        touched_research += 1

    added_positions = 0
    for iid, quantity in data.positions:
        duplicate = await conn.scalar(
            select(positions.c.id).where(
                positions.c.instrument_id == iid,
                positions.c.quantity == quantity,
                positions.c.note == IMPORT_NOTE,
            )
        )
        if duplicate is None:
            await conn.execute(
                insert(positions).values(
                    user_id=user.id, instrument_id=iid, quantity=quantity, note=IMPORT_NOTE
                )
            )
            added_positions += 1

    added_alerts = 0
    for iid, direction, price in data.alerts:
        duplicate = await conn.scalar(
            select(alerts.c.id).where(
                alerts.c.instrument_id == iid,
                alerts.c.direction == direction,
                alerts.c.price == price,
            )
        )
        if duplicate is None:
            await conn.execute(
                insert(alerts).values(
                    user_id=user.id,
                    instrument_id=iid,
                    direction=direction,
                    price=price,
                    note=IMPORT_NOTE,
                )
            )
            added_alerts += 1

    if data.preferences:
        current_prefs = await prefs_module.load(conn)
        merged = current_prefs.model_copy(update=data.preferences)
        await prefs_module.save(
            conn, user.id, prefs_module.Preferences.model_validate(merged.model_dump())
        )

    result = ImportResult(
        watchlist=added_watch,
        theses=added_theses,
        research=touched_research,
        positions=added_positions,
        alerts=added_alerts,
        preferences=bool(data.preferences),
        skipped_symbols=sorted(data.skipped)[:50],
    )
    await audit.record(
        conn, request, "workspace.imported", user_id=user.id, metadata=result.model_dump()
    )
    return result
