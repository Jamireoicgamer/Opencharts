# SPDX-License-Identifier: AGPL-3.0-or-later
"""Security audit fixes (October 2026).

* The app role can no longer read ``users.password_hash``. Sign-in reads it
  through ``auth_login_lookup`` only, so a SQL injection elsewhere cannot dump
  password hashes even for owners/admins, who can see every user row.
* ``auth_revoke_session`` revokes a session by its token hash. Holding the
  token proves ownership, so it is safe to call before the user is known: it
  ends the old session when a browser signs in again.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

from openchart_api.migrations.sql import app_role, run

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = """
REVOKE SELECT ON users FROM {role};
GRANT SELECT (id, email, display_name, role, created_at, disabled_at) ON users TO {role};

CREATE FUNCTION auth_revoke_session(p_token_hash bytea) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS
$$ UPDATE sessions SET revoked_at = now()
   WHERE token_hash = p_token_hash AND revoked_at IS NULL $$;
REVOKE ALL ON FUNCTION auth_revoke_session(bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_revoke_session(bytea) TO {role};
"""

DOWNGRADE = """
DROP FUNCTION auth_revoke_session(bytea);
REVOKE SELECT (id, email, display_name, role, created_at, disabled_at) ON users FROM {role};
GRANT SELECT ON users TO {role};
"""


def upgrade() -> None:
    run(op, UPGRADE.format(role=app_role()))


def downgrade() -> None:
    run(op, DOWNGRADE.format(role=app_role()))
