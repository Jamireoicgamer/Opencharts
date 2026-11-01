# SPDX-License-Identifier: AGPL-3.0-or-later
"""The workspace: instruments, watchlist, theses, research, positions,
alerts and preferences (milestone M2).

``instruments`` is a shared catalogue: readable by everyone, changed only by
migrations. Everything else belongs to one user and uses the usual RLS policy.
Thesis versions are a journal: the app can add versions but not change them.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from openchart_api.migrations.data.instruments_2026_10 import INSTRUMENTS
from openchart_api.migrations.sql import app_role, run

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = """
CREATE TABLE instruments (
    id text PRIMARY KEY CHECK (id ~ '^[A-Z]+:[A-Z0-9./-]+$'),
    symbol text NOT NULL,
    name text NOT NULL,
    exchange text NOT NULL,
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    asset_class text NOT NULL CHECK (asset_class IN ('equity', 'etf', 'crypto', 'fx', 'index')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE watchlist_items (
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    instrument_id text NOT NULL REFERENCES instruments (id),
    position integer NOT NULL,
    added_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, instrument_id)
);

CREATE TABLE thesis_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    instrument_id text NOT NULL REFERENCES instruments (id),
    summary text NOT NULL DEFAULT '' CHECK (length(summary) <= 10000),
    key_risk text NOT NULL DEFAULT '' CHECK (length(key_risk) <= 5000),
    bull_case text NOT NULL DEFAULT '' CHECK (length(bull_case) <= 5000),
    bear_case text NOT NULL DEFAULT '' CHECK (length(bear_case) <= 5000),
    fair_value numeric(28, 10) CHECK (fair_value > 0),
    entry_price numeric(28, 10) CHECK (entry_price > 0),
    conviction text NOT NULL DEFAULT 'not_assessed'
        CHECK (conviction IN ('not_assessed', 'low', 'moderate', 'high')),
    horizon text NOT NULL DEFAULT 'not_set'
        CHECK (horizon IN ('not_set', 'under_1y', '1_3y', '3_5y', 'over_5y')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX thesis_versions_lookup ON thesis_versions (user_id, instrument_id, created_at DESC);

CREATE TABLE research_notes (
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    instrument_id text NOT NULL REFERENCES instruments (id),
    body text NOT NULL DEFAULT '' CHECK (length(body) <= 50000),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, instrument_id)
);

CREATE TABLE research_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    instrument_id text NOT NULL REFERENCES instruments (id),
    label text NOT NULL CHECK (length(label) BETWEEN 1 AND 200),
    done boolean NOT NULL DEFAULT false,
    position integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX research_tasks_lookup ON research_tasks (user_id, instrument_id, position);

CREATE TABLE positions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    instrument_id text NOT NULL REFERENCES instruments (id),
    quantity numeric(28, 10) NOT NULL CHECK (quantity > 0),
    average_price numeric(28, 10) CHECK (average_price > 0),
    account text NOT NULL DEFAULT 'other' CHECK (account IN ('isa', 'gia', 'sipp', 'other')),
    note text NOT NULL DEFAULT '' CHECK (length(note) <= 500),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX positions_user_id ON positions (user_id);

CREATE TABLE alerts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    instrument_id text NOT NULL REFERENCES instruments (id),
    direction text NOT NULL CHECK (direction IN ('above', 'below')),
    price numeric(28, 10) NOT NULL CHECK (price > 0),
    note text NOT NULL DEFAULT '' CHECK (length(note) <= 200),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    triggered_at timestamptz
);
CREATE INDEX alerts_user_id ON alerts (user_id);

CREATE TABLE user_preferences (
    user_id uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    data jsonb NOT NULL DEFAULT '{}' CHECK (pg_column_size(data) <= 8192),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Row-level security -------------------------------------------------------

ALTER TABLE instruments ENABLE ROW LEVEL SECURITY;
CREATE POLICY instruments_read ON instruments FOR SELECT USING (true);

ALTER TABLE watchlist_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY watchlist_items_own ON watchlist_items FOR ALL
    USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());

ALTER TABLE thesis_versions ENABLE ROW LEVEL SECURITY;
CREATE POLICY thesis_versions_own ON thesis_versions FOR ALL
    USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());

ALTER TABLE research_notes ENABLE ROW LEVEL SECURITY;
CREATE POLICY research_notes_own ON research_notes FOR ALL
    USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());

ALTER TABLE research_tasks ENABLE ROW LEVEL SECURITY;
CREATE POLICY research_tasks_own ON research_tasks FOR ALL
    USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());

ALTER TABLE positions ENABLE ROW LEVEL SECURITY;
CREATE POLICY positions_own ON positions FOR ALL
    USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());

ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
CREATE POLICY alerts_own ON alerts FOR ALL
    USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());

ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_preferences_own ON user_preferences FOR ALL
    USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());
"""

GRANTS = """
GRANT SELECT ON instruments TO {role};
GRANT SELECT, INSERT, UPDATE, DELETE
    ON watchlist_items, research_notes, research_tasks, positions, alerts, user_preferences
    TO {role};
-- A journal: versions can be added and read, not changed. Deleting an
-- instrument's whole history is allowed.
GRANT SELECT, INSERT, DELETE ON thesis_versions TO {role};
"""

DROP = """
DROP TABLE user_preferences, alerts, positions, research_tasks, research_notes,
    thesis_versions, watchlist_items, instruments;
"""

instruments = sa.table(
    "instruments",
    sa.column("id", sa.Text),
    sa.column("symbol", sa.Text),
    sa.column("name", sa.Text),
    sa.column("exchange", sa.Text),
    sa.column("currency", sa.Text),
    sa.column("asset_class", sa.Text),
)


def upgrade() -> None:
    run(op, SCHEMA)
    op.bulk_insert(
        instruments,
        [
            dict(
                zip(
                    ("id", "symbol", "name", "exchange", "currency", "asset_class"),
                    row,
                    strict=True,
                )
            )
            for row in INSTRUMENTS
        ],
    )
    run(op, GRANTS.format(role=app_role()))


def downgrade() -> None:
    run(op, DROP)
