# SPDX-License-Identifier: AGPL-3.0-or-later
"""Research notes and a checklist per instrument."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from openchart_api.auth import User
from openchart_api.db import Conn
from openchart_api.routes.workspace.common import InstrumentIdPath, require_instrument
from openchart_api.tables import research_notes, research_tasks

router = APIRouter(tags=["research"])

# The prototype's checklist, used for every instrument's first visit.
DEFAULT_TASKS = (
    "Review the latest company financial results",
    "Check company guidance and regulatory filings",
    "Compare new evidence against your thesis",
)
MAX_TASKS = 50

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Task(BaseModel):
    id: UUID
    label: str
    done: bool
    position: int


class Research(BaseModel):
    notes: str
    updated_at: datetime
    tasks: list[Task]


class NotesInput(BaseModel):
    body: Annotated[str, Field(max_length=50000)]


class NewTask(BaseModel):
    label: Label


class TaskChange(BaseModel):
    label: Label | None = None
    done: bool | None = None


async def ensure_research(conn: AsyncConnection, user_id: UUID, instrument_id: str) -> None:
    """Create the notes row and default checklist the first time.

    The notes row marks the instrument as set up, so deleting every task later
    does not bring the defaults back.
    """
    created = await conn.execute(
        pg_insert(research_notes)
        .values(user_id=user_id, instrument_id=instrument_id, body="")
        .on_conflict_do_nothing()
    )
    if created.rowcount:
        await conn.execute(
            insert(research_tasks),
            [
                {"user_id": user_id, "instrument_id": instrument_id, "label": label, "position": i}
                for i, label in enumerate(DEFAULT_TASKS)
            ],
        )


async def _research(conn: AsyncConnection, instrument_id: str) -> Research:
    note = (
        await conn.execute(
            select(research_notes.c.body, research_notes.c.updated_at).where(
                research_notes.c.instrument_id == instrument_id
            )
        )
    ).one()
    tasks = await conn.execute(
        select(
            research_tasks.c.id,
            research_tasks.c.label,
            research_tasks.c.done,
            research_tasks.c.position,
        )
        .where(research_tasks.c.instrument_id == instrument_id)
        .order_by(research_tasks.c.position)
    )
    return Research(
        notes=note.body,
        updated_at=note.updated_at,
        tasks=[Task.model_validate(t, from_attributes=True) for t in tasks],
    )


@router.get("/instruments/{instrument_id}/research")
async def get_research(instrument_id: InstrumentIdPath, user: User, conn: Conn) -> Research:
    await require_instrument(conn, instrument_id)
    await ensure_research(conn, user.id, instrument_id)
    return await _research(conn, instrument_id)


@router.put("/instruments/{instrument_id}/research/notes")
async def save_notes(
    instrument_id: InstrumentIdPath, body: NotesInput, user: User, conn: Conn
) -> Research:
    await require_instrument(conn, instrument_id)
    await ensure_research(conn, user.id, instrument_id)
    await conn.execute(
        update(research_notes)
        .where(research_notes.c.instrument_id == instrument_id)
        .values(body=body.body, updated_at=func.now())
    )
    return await _research(conn, instrument_id)


@router.post("/instruments/{instrument_id}/research/tasks", status_code=status.HTTP_201_CREATED)
async def add_task(
    instrument_id: InstrumentIdPath, body: NewTask, user: User, conn: Conn
) -> Research:
    await require_instrument(conn, instrument_id)
    await ensure_research(conn, user.id, instrument_id)
    count, top = (
        await conn.execute(
            select(func.count(), func.coalesce(func.max(research_tasks.c.position), -1)).where(
                research_tasks.c.instrument_id == instrument_id
            )
        )
    ).one()
    if count >= MAX_TASKS:
        raise HTTPException(status.HTTP_409_CONFLICT, "This checklist is full")
    await conn.execute(
        insert(research_tasks).values(
            user_id=user.id, instrument_id=instrument_id, label=body.label, position=top + 1
        )
    )
    return await _research(conn, instrument_id)


async def _task_instrument(conn: AsyncConnection, task_id: UUID) -> str:
    instrument_id = await conn.scalar(
        select(research_tasks.c.instrument_id).where(research_tasks.c.id == task_id)
    )
    if instrument_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return str(instrument_id)


@router.patch("/research/tasks/{task_id}")
async def change_task(task_id: UUID, body: TaskChange, user: User, conn: Conn) -> Research:
    instrument_id = await _task_instrument(conn, task_id)
    values = body.model_dump(exclude_none=True)
    if values:
        await conn.execute(
            update(research_tasks).where(research_tasks.c.id == task_id).values(**values)
        )
    return await _research(conn, instrument_id)


@router.delete("/research/tasks/{task_id}")
async def delete_task(task_id: UUID, user: User, conn: Conn) -> Research:
    instrument_id = await _task_instrument(conn, task_id)
    await conn.execute(delete(research_tasks).where(research_tasks.c.id == task_id))
    return await _research(conn, instrument_id)
