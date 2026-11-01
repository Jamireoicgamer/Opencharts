# SPDX-License-Identifier: AGPL-3.0-or-later
"""Moving workspace data in and out: a full export, importing an export
(from another OpenChart, such as the desktop app or a server), and
importing what the V4.1 prototype saved in the browser."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, insert, select, update

from openchart_api import audit, legacy_import
from openchart_api.auth import User
from openchart_api.db import Conn
from openchart_api.routes.workspace import preferences as prefs_module
from openchart_api.routes.workspace.alerts import (
    MAX_ALERTS,
    Direction,
    alerts_changed,
    list_alerts,
)
from openchart_api.routes.workspace.alerts import Note as AlertNote
from openchart_api.routes.workspace.common import InstrumentIdField, Money
from openchart_api.routes.workspace.positions import (
    MAX_POSITIONS,
    Account,
    Note,
    list_positions,
)
from openchart_api.routes.workspace.research import MAX_TASKS, Label, ensure_research
from openchart_api.routes.workspace.thesis import HISTORY_LIMIT, ThesisInput
from openchart_api.routes.workspace.watchlist import MAX_ITEMS
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
IMPORT_NOTE_EXPORT = "Imported from another OpenChart"


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


class _Loose(BaseModel):
    # Exports carry display fields (names, ids, timestamps) that importing ignores.
    model_config = ConfigDict(extra="ignore")


class _InstrumentRef(_Loose):
    id: InstrumentIdField


class _ExportedThesis(ThesisInput, _Loose):
    created_at: datetime


class _ExportedTask(_Loose):
    label: Label
    done: bool = False


class _ExportedResearch(_Loose):
    notes: Annotated[str, Field(max_length=50000)] = ""
    tasks: Annotated[list[_ExportedTask], Field(max_length=MAX_TASKS)] = []


class _ExportedPosition(_Loose):
    instrument: _InstrumentRef
    quantity: Money
    average_price: Money | None = None
    account: Account = "other"
    note: Note = ""


class _ExportedAlert(_Loose):
    instrument: _InstrumentRef
    direction: Direction
    price: Money
    note: AlertNote = ""
    active: bool = True


class WorkspaceExport(_Loose):
    """The file ``GET /export`` produces."""

    format: Literal["openchart-export"]
    version: Literal[1]
    preferences: dict[str, Any] = {}
    watchlist: Annotated[list[InstrumentIdField], Field(max_length=MAX_ITEMS)] = []
    theses: Annotated[
        dict[InstrumentIdField, Annotated[list[_ExportedThesis], Field(max_length=HISTORY_LIMIT)]],
        Field(max_length=MAX_ITEMS),
    ] = {}
    research: Annotated[
        dict[InstrumentIdField, _ExportedResearch], Field(max_length=MAX_ITEMS)
    ] = {}
    positions: Annotated[list[_ExportedPosition], Field(max_length=MAX_POSITIONS)] = []
    alerts: Annotated[list[_ExportedAlert], Field(max_length=MAX_ALERTS)] = []


def _same(a: Decimal | None, b: Decimal | None) -> bool:
    return (a is None and b is None) or (a is not None and b is not None and a == b)


@router.post("/import")
async def import_workspace(
    data: WorkspaceExport, user: User, request: Request, conn: Conn
) -> ImportResult:
    """Merge an OpenChart export. Importing the same file twice adds nothing."""
    known = set(await conn.scalars(select(instruments.c.id)))
    skipped: set[str] = set()
    # Check the preferences before changing anything.
    prefs = {
        k: v for k, v in data.preferences.items() if k in prefs_module.Preferences.model_fields
    }
    if prefs.get("last_instrument") is not None and prefs["last_instrument"] not in known:
        prefs.pop("last_instrument")
    current_prefs = await prefs_module.load(conn)
    try:
        merged = prefs_module.Preferences.model_validate({**current_prefs.model_dump(), **prefs})
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The file's preferences are not valid"
        ) from None

    def usable(iid: str) -> bool:
        if iid in known:
            return True
        skipped.add(iid)
        return False

    existing = set(await conn.scalars(select(watchlist_items.c.instrument_id)))
    top = len(existing)
    added_watch = 0
    for iid in data.watchlist:
        if usable(iid) and iid not in existing and top < MAX_ITEMS:
            await conn.execute(
                insert(watchlist_items).values(user_id=user.id, instrument_id=iid, position=top)
            )
            existing.add(iid)
            top += 1
            added_watch += 1

    added_theses = 0
    for iid, versions in data.theses.items():
        if not usable(iid):
            continue
        seen = set(
            await conn.scalars(
                select(thesis_versions.c.created_at).where(thesis_versions.c.instrument_id == iid)
            )
        )
        for version in versions:
            if version.created_at not in seen:
                await conn.execute(
                    insert(thesis_versions).values(
                        user_id=user.id, instrument_id=iid, **version.model_dump()
                    )
                )
                seen.add(version.created_at)
                added_theses += 1

    touched_research = 0
    for iid, page in data.research.items():
        if not usable(iid):
            continue
        await ensure_research(conn, user.id, iid)
        changed = False
        current = (
            await conn.scalar(
                select(research_notes.c.body).where(research_notes.c.instrument_id == iid)
            )
            or ""
        )
        if page.notes and page.notes not in current:
            notes = (
                f"{current}\n\n— {IMPORT_NOTE_EXPORT} —\n{page.notes}" if current else page.notes
            )
            await conn.execute(
                update(research_notes)
                .where(research_notes.c.instrument_id == iid)
                .values(body=notes[:50000])
            )
            changed = True
        tasks = {
            t.label: (t.id, t.done)
            for t in await conn.execute(
                select(research_tasks.c.id, research_tasks.c.label, research_tasks.c.done).where(
                    research_tasks.c.instrument_id == iid
                )
            )
        }
        count = len(tasks)
        for task in page.tasks:
            if task.label in tasks:
                task_id, done = tasks[task.label]
                if task.done and not done:
                    await conn.execute(
                        update(research_tasks)
                        .where(research_tasks.c.id == task_id)
                        .values(done=True)
                    )
                    changed = True
            elif count < MAX_TASKS:
                await conn.execute(
                    insert(research_tasks).values(
                        user_id=user.id,
                        instrument_id=iid,
                        label=task.label,
                        done=task.done,
                        position=count,
                    )
                )
                tasks[task.label] = (None, task.done)
                count += 1
                changed = True
        touched_research += changed

    added_positions = 0
    held = [
        (r.instrument_id, r.quantity, r.average_price, r.account, r.note)
        for r in await conn.execute(select(positions))
    ]
    for p in data.positions:
        if not usable(p.instrument.id) or len(held) >= MAX_POSITIONS:
            continue
        if any(
            h[0] == p.instrument.id
            and h[1] == p.quantity
            and _same(h[2], p.average_price)
            and h[3:] == (p.account, p.note)
            for h in held
        ):
            continue
        await conn.execute(
            insert(positions).values(
                user_id=user.id,
                instrument_id=p.instrument.id,
                quantity=p.quantity,
                average_price=p.average_price,
                account=p.account,
                note=p.note,
            )
        )
        held.append((p.instrument.id, p.quantity, p.average_price, p.account, p.note))
        added_positions += 1

    added_alerts = 0
    alert_count = await conn.scalar(select(func.count()).select_from(alerts)) or 0
    for a in data.alerts:
        if not usable(a.instrument.id) or alert_count >= MAX_ALERTS:
            continue
        duplicate = await conn.scalar(
            select(alerts.c.id).where(
                alerts.c.instrument_id == a.instrument.id,
                alerts.c.direction == a.direction,
                alerts.c.price == a.price,
            )
        )
        if duplicate is None:
            await conn.execute(
                insert(alerts).values(
                    user_id=user.id,
                    instrument_id=a.instrument.id,
                    direction=a.direction,
                    price=a.price,
                    note=a.note,
                    active=a.active,
                )
            )
            alert_count += 1
            added_alerts += 1
    if added_alerts:
        alerts_changed(request)

    if prefs:
        await prefs_module.save(conn, user.id, merged)

    result = ImportResult(
        watchlist=added_watch,
        theses=added_theses,
        research=touched_research,
        positions=added_positions,
        alerts=added_alerts,
        preferences=bool(prefs),
        skipped_symbols=sorted(skipped)[:50],
    )
    await audit.record(
        conn, request, "workspace.imported", user_id=user.id, metadata=result.model_dump()
    )
    return result


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
