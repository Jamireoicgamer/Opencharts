# SPDX-License-Identifier: AGPL-3.0-or-later
"""Accounts, sessions, invites, secrets vault and audit log.

Security model:

* The schema is owned by the migration role. The API connects as a separate
  least-privilege role (``app_role``) that row-level security applies to.
* Each request sets ``app.user_id`` / ``app.user_role`` for its transaction;
  policies only expose that user's rows (owners/admins see a little more).
* Lookups that must happen before a user is known (login, session cookie,
  first-run setup, invite redemption) go through narrow SECURITY DEFINER
  functions instead of broad table access.
* The audit log is append-only: no UPDATE/DELETE grants and a trigger that
  rejects them even for the owner.

Revision ID: 0001
Revises:
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

from openchart_api.migrations.sql import app_role, run

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS citext;

CREATE FUNCTION app_user_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;

CREATE FUNCTION app_user_role() RETURNS text LANGUAGE sql STABLE AS
$$ SELECT coalesce(nullif(current_setting('app.user_role', true), ''), 'anonymous') $$;

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email citext NOT NULL UNIQUE CHECK (length(email) BETWEEN 3 AND 254),
    display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 100),
    password_hash text,
    role text NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
    created_at timestamptz NOT NULL DEFAULT now(),
    disabled_at timestamptz
);
CREATE UNIQUE INDEX users_single_owner ON users ((true)) WHERE role = 'owner';

CREATE TABLE sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash bytea NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    user_agent text CHECK (length(user_agent) <= 512),
    ip text CHECK (length(ip) <= 64)
);
CREATE INDEX sessions_user_id ON sessions (user_id);

CREATE TABLE invites (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash bytea NOT NULL UNIQUE,
    created_by uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    email citext,
    role text NOT NULL CHECK (role IN ('admin', 'member')),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    used_by uuid REFERENCES users (id) ON DELETE SET NULL
);

CREATE TABLE vault_secrets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name text NOT NULL CHECK (name ~ '^[a-z0-9][a-z0-9_.-]{0,63}$'),
    provider text CHECK (length(provider) <= 64),
    ciphertext bytea NOT NULL,
    nonce bytea NOT NULL,
    wrapped_dek bytea NOT NULL,
    dek_nonce bytea NOT NULL,
    key_version integer NOT NULL,
    hint text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

CREATE TABLE audit_log (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid,
    action text NOT NULL,
    target text,
    ip text,
    user_agent text,
    metadata jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_user_id ON audit_log (user_id, id DESC);

CREATE FUNCTION audit_log_append_only() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN RAISE EXCEPTION 'audit_log is append-only'; END $$;
CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only();

-- Row-level security -------------------------------------------------------

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY users_visible ON users FOR SELECT
    USING (id = app_user_id() OR app_user_role() IN ('owner', 'admin'));
CREATE POLICY users_update_self ON users FOR UPDATE
    USING (id = app_user_id()) WITH CHECK (id = app_user_id());

ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY sessions_own ON sessions FOR ALL
    USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());

ALTER TABLE invites ENABLE ROW LEVEL SECURITY;
CREATE POLICY invites_admins ON invites FOR ALL
    USING (app_user_role() IN ('owner', 'admin'))
    WITH CHECK (app_user_role() IN ('owner', 'admin') AND created_by = app_user_id());

ALTER TABLE vault_secrets ENABLE ROW LEVEL SECURITY;
CREATE POLICY vault_secrets_own ON vault_secrets FOR ALL
    USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_log_read ON audit_log FOR SELECT
    USING (user_id = app_user_id() OR app_user_role() = 'owner');
CREATE POLICY audit_log_write ON audit_log FOR INSERT
    WITH CHECK (user_id IS NULL OR user_id = app_user_id());

-- Pre-authentication entry points ------------------------------------------

CREATE FUNCTION auth_needs_setup() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT NOT EXISTS (SELECT 1 FROM users) $$;

CREATE FUNCTION auth_login_lookup(p_email citext)
RETURNS TABLE (id uuid, email citext, display_name text, password_hash text, role text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT u.id, u.email, u.display_name, u.password_hash, u.role FROM users u
   WHERE u.email = p_email AND u.disabled_at IS NULL $$;

CREATE FUNCTION auth_session_lookup(p_token_hash bytea)
RETURNS TABLE (session_id uuid, user_id uuid, email citext, display_name text, role text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT s.id, u.id, u.email, u.display_name, u.role
   FROM sessions s JOIN users u ON u.id = s.user_id
   WHERE s.token_hash = p_token_hash
     AND s.revoked_at IS NULL
     AND s.expires_at > now()
     AND u.disabled_at IS NULL $$;

CREATE FUNCTION auth_bootstrap_owner(p_email citext, p_display_name text, p_password_hash text)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS
$$
DECLARE
    v_id uuid;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('openchart.bootstrap_owner'));
    IF EXISTS (SELECT 1 FROM users) THEN
        RETURN NULL;
    END IF;
    INSERT INTO users (email, display_name, password_hash, role)
    VALUES (p_email, p_display_name, p_password_hash, 'owner')
    RETURNING id INTO v_id;
    RETURN v_id;
END
$$;

CREATE FUNCTION auth_redeem_invite(
    p_token_hash bytea, p_email citext, p_display_name text, p_password_hash text
) RETURNS TABLE (new_user_id uuid, new_user_role text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS
$$
DECLARE
    v_invite invites%ROWTYPE;
BEGIN
    SELECT * INTO v_invite FROM invites
    WHERE token_hash = p_token_hash AND used_at IS NULL AND expires_at > now()
    FOR UPDATE;
    IF NOT FOUND OR (v_invite.email IS NOT NULL AND v_invite.email <> p_email) THEN
        RETURN;
    END IF;
    INSERT INTO users (email, display_name, password_hash, role)
    VALUES (p_email, p_display_name, p_password_hash, v_invite.role)
    RETURNING id INTO new_user_id;
    UPDATE invites SET used_at = now(), used_by = new_user_id WHERE id = v_invite.id;
    new_user_role := v_invite.role;
    RETURN NEXT;
END
$$;

REVOKE ALL ON FUNCTION auth_needs_setup() FROM PUBLIC;
REVOKE ALL ON FUNCTION auth_login_lookup(citext) FROM PUBLIC;
REVOKE ALL ON FUNCTION auth_session_lookup(bytea) FROM PUBLIC;
REVOKE ALL ON FUNCTION auth_bootstrap_owner(citext, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION auth_redeem_invite(bytea, citext, text, text) FROM PUBLIC;
"""

GRANTS = """
GRANT USAGE ON SCHEMA public TO {role};
GRANT SELECT ON users TO {role};
GRANT UPDATE (display_name, password_hash) ON users TO {role};
GRANT SELECT, INSERT, UPDATE, DELETE ON sessions, invites, vault_secrets TO {role};
GRANT SELECT, INSERT ON audit_log TO {role};
GRANT EXECUTE ON FUNCTION auth_needs_setup() TO {role};
GRANT EXECUTE ON FUNCTION auth_login_lookup(citext) TO {role};
GRANT EXECUTE ON FUNCTION auth_session_lookup(bytea) TO {role};
GRANT EXECUTE ON FUNCTION auth_bootstrap_owner(citext, text, text) TO {role};
GRANT EXECUTE ON FUNCTION auth_redeem_invite(bytea, citext, text, text) TO {role};
"""

DROP = """
DROP FUNCTION auth_redeem_invite(bytea, citext, text, text);
DROP FUNCTION auth_bootstrap_owner(citext, text, text);
DROP FUNCTION auth_session_lookup(bytea);
DROP FUNCTION auth_login_lookup(citext);
DROP FUNCTION auth_needs_setup();
DROP TABLE audit_log, vault_secrets, invites, sessions, users;
DROP FUNCTION audit_log_append_only();
DROP FUNCTION app_user_role();
DROP FUNCTION app_user_id();
"""


def upgrade() -> None:
    run(op, SCHEMA)
    run(op, GRANTS.format(role=app_role()))


def downgrade() -> None:
    run(op, DROP)
