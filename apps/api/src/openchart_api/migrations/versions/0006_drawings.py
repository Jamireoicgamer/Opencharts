# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chart drawings (milestone M4): trend lines, levels, rectangles,
Fibonacci retracements and notes, saved per user and instrument.

Points are stored in price and time, so a drawing stays put however the
chart is scrolled or zoomed. Colours are theme names, never raw CSS.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-02
"""

from collections.abc import Sequence

from alembic import op

from openchart_api.migrations.sql import app_role, run

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = """
CREATE TABLE drawings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    instrument_id text NOT NULL REFERENCES instruments (id),
    kind text NOT NULL CHECK (kind IN ('trend', 'hline', 'rect', 'fib', 'note')),
    points jsonb NOT NULL CHECK (
        jsonb_typeof(points) = 'array' AND jsonb_array_length(points) BETWEEN 1 AND 2
    ),
    color text NOT NULL DEFAULT 'accent'
        CHECK (color IN ('accent', 'amber', 'blue', 'pink', 'green', 'red', 'muted')),
    text text NOT NULL DEFAULT '' CHECK (length(text) <= 200),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX drawings_lookup ON drawings (user_id, instrument_id, created_at);

ALTER TABLE drawings ENABLE ROW LEVEL SECURITY;
CREATE POLICY drawings_own ON drawings FOR ALL
    USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());
"""

GRANTS = """
GRANT SELECT, INSERT, UPDATE, DELETE ON drawings TO {role};
"""

DROP = """
DROP TABLE drawings;
"""


def upgrade() -> None:
    run(op, SCHEMA)
    run(op, GRANTS.format(role=app_role()))


def downgrade() -> None:
    run(op, DROP)
