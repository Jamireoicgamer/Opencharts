# SPDX-License-Identifier: AGPL-3.0-or-later
"""Desktop sign-in: find the owner without a password.

The desktop app opens straight to the workspace. Its shell starts the API
with a random token that only the app window receives; presenting it signs
in as the owner. Before a session exists, row-level security shows the API
no users, so ``auth_desktop_owner()`` returns just the owner's id and role.
It reveals nothing else, and on its own it signs nobody in: the API calls
it only after the desktop token has been checked.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

from openchart_api.migrations.sql import app_role, run

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = """
CREATE FUNCTION auth_desktop_owner() RETURNS TABLE (id uuid, role text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT u.id, u.role FROM users u
   WHERE u.role = 'owner' AND u.disabled_at IS NULL
   ORDER BY u.created_at LIMIT 1 $$;
REVOKE ALL ON FUNCTION auth_desktop_owner() FROM PUBLIC;
"""

GRANTS = """
GRANT EXECUTE ON FUNCTION auth_desktop_owner() TO {role};
"""

DROP = """
DROP FUNCTION auth_desktop_owner();
"""


def upgrade() -> None:
    run(op, SCHEMA)
    run(op, GRANTS.format(role=app_role()))


def downgrade() -> None:
    run(op, DROP)
