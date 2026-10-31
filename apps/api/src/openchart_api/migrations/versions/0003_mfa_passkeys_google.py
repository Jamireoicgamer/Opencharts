# SPDX-License-Identifier: AGPL-3.0-or-later
"""Two-factor authentication, passkeys and Google sign-in (milestone M1b).

* ``mfa_totp``, ``mfa_recovery_codes``, ``webauthn_credentials`` and
  ``oauth_identities`` belong to one user each and use the usual RLS policy.
  The TOTP secret is sealed with the vault; recovery codes are stored as
  keyed hashes.
* ``auth_flows`` holds short-lived, single-use state for sign-in steps that
  happen before a user is known (pending second factor, WebAuthn challenges,
  OAuth state). The app role has no access to the table itself, only to the
  ``auth_flow_*`` functions, which look flows up by token hash.
* ``server_settings`` is a single row; only the owner can change it.
* ``sessions.reauth_at`` records the last time the session's user proved
  who they are, for actions that need a recent sign-in.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

from openchart_api.migrations.sql import app_role, run

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = """
ALTER TABLE sessions ADD COLUMN reauth_at timestamptz NOT NULL DEFAULT now();

CREATE TABLE mfa_totp (
    user_id uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    ciphertext bytea NOT NULL,
    nonce bytea NOT NULL,
    wrapped_dek bytea NOT NULL,
    dek_nonce bytea NOT NULL,
    key_version integer NOT NULL,
    confirmed_at timestamptz,
    last_used_step bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE mfa_recovery_codes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    code_hash bytea NOT NULL,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mfa_recovery_codes_user_id ON mfa_recovery_codes (user_id);

CREATE TABLE webauthn_credentials (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    credential_id bytea NOT NULL UNIQUE,
    public_key bytea NOT NULL,
    sign_count bigint NOT NULL DEFAULT 0,
    transports text[] NOT NULL DEFAULT '{}',
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 64),
    backed_up boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz
);
CREATE INDEX webauthn_credentials_user_id ON webauthn_credentials (user_id);

CREATE TABLE oauth_identities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    provider text NOT NULL CHECK (provider IN ('google')),
    subject text NOT NULL CHECK (length(subject) BETWEEN 1 AND 255),
    email citext,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    UNIQUE (provider, subject),
    UNIQUE (user_id, provider)
);

CREATE TABLE server_settings (
    id boolean PRIMARY KEY DEFAULT true CHECK (id),
    require_mfa boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO server_settings DEFAULT VALUES;

CREATE TABLE auth_flows (
    token_hash bytea PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('mfa', 'passkey_login', 'passkey_register',
                                       'reauth_passkey', 'mfa_passkey', 'oauth')),
    user_id uuid REFERENCES users (id) ON DELETE CASCADE,
    data jsonb NOT NULL DEFAULT '{}',
    attempts integer NOT NULL DEFAULT 0,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Row-level security -------------------------------------------------------

ALTER TABLE mfa_totp ENABLE ROW LEVEL SECURITY;
CREATE POLICY mfa_totp_own ON mfa_totp FOR ALL
    USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());

ALTER TABLE mfa_recovery_codes ENABLE ROW LEVEL SECURITY;
CREATE POLICY mfa_recovery_codes_own ON mfa_recovery_codes FOR ALL
    USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());

ALTER TABLE webauthn_credentials ENABLE ROW LEVEL SECURITY;
CREATE POLICY webauthn_credentials_own ON webauthn_credentials FOR ALL
    USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());

ALTER TABLE oauth_identities ENABLE ROW LEVEL SECURITY;
CREATE POLICY oauth_identities_own ON oauth_identities FOR ALL
    USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());

ALTER TABLE server_settings ENABLE ROW LEVEL SECURITY;
CREATE POLICY server_settings_read ON server_settings FOR SELECT USING (true);
CREATE POLICY server_settings_owner ON server_settings FOR UPDATE
    USING (app_user_role() = 'owner') WITH CHECK (app_user_role() = 'owner');

-- No policies and no grants: reachable only through the functions below.
ALTER TABLE auth_flows ENABLE ROW LEVEL SECURITY;

-- Pre-authentication flows ---------------------------------------------------

CREATE FUNCTION auth_flow_start(
    p_token_hash bytea, p_kind text, p_user_id uuid, p_data jsonb, p_ttl_seconds integer
) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS
$$
    DELETE FROM auth_flows WHERE expires_at < now();
    INSERT INTO auth_flows (token_hash, kind, user_id, data, expires_at)
    VALUES (p_token_hash, p_kind, p_user_id, p_data,
            now() + make_interval(secs => least(p_ttl_seconds, 900)));
$$;

CREATE FUNCTION auth_flow_get(p_token_hash bytea, p_kind text)
RETURNS TABLE (user_id uuid, data jsonb, attempts integer)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT f.user_id, f.data, f.attempts FROM auth_flows f
   WHERE f.token_hash = p_token_hash AND f.kind = p_kind AND f.expires_at > now() $$;

CREATE FUNCTION auth_flow_set_data(p_token_hash bytea, p_kind text, p_data jsonb)
RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS
$$ UPDATE auth_flows SET data = data || p_data
   WHERE token_hash = p_token_hash AND kind = p_kind AND expires_at > now()
   RETURNING true $$;

-- Counts a failed attempt; the flow is deleted once p_max is reached.
-- Returns the attempts left (0 when the flow is gone).
CREATE FUNCTION auth_flow_fail(p_token_hash bytea, p_kind text, p_max integer)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS
$$
DECLARE
    v_attempts integer;
BEGIN
    UPDATE auth_flows SET attempts = attempts + 1
    WHERE token_hash = p_token_hash AND kind = p_kind AND expires_at > now()
    RETURNING attempts INTO v_attempts;
    IF v_attempts IS NULL THEN
        RETURN 0;
    END IF;
    IF v_attempts >= p_max THEN
        DELETE FROM auth_flows WHERE token_hash = p_token_hash;
        RETURN 0;
    END IF;
    RETURN p_max - v_attempts;
END
$$;

-- Single use: returns the flow and deletes it.
CREATE FUNCTION auth_flow_take(p_token_hash bytea, p_kind text)
RETURNS TABLE (user_id uuid, data jsonb)
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS
$$ DELETE FROM auth_flows f
   WHERE f.token_hash = p_token_hash AND f.kind = p_kind AND f.expires_at > now()
   RETURNING f.user_id, f.data $$;

-- Pre-authentication lookups -------------------------------------------------

CREATE FUNCTION auth_passkey_lookup(p_credential_id bytea)
RETURNS TABLE (id uuid, user_id uuid, public_key bytea, sign_count bigint, role text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT c.id, c.user_id, c.public_key, c.sign_count, u.role
   FROM webauthn_credentials c JOIN users u ON u.id = c.user_id
   WHERE c.credential_id = p_credential_id AND u.disabled_at IS NULL $$;

CREATE FUNCTION auth_oauth_lookup(p_provider text, p_subject text)
RETURNS TABLE (user_id uuid, role text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT u.id, u.role FROM oauth_identities i JOIN users u ON u.id = i.user_id
   WHERE i.provider = p_provider AND i.subject = p_subject AND u.disabled_at IS NULL $$;

-- Whether the signed-in user has a password; the hash itself stays unreadable.
CREATE FUNCTION auth_has_password() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT EXISTS (SELECT 1 FROM users WHERE id = app_user_id() AND password_hash IS NOT NULL) $$;

REVOKE ALL ON FUNCTION auth_has_password() FROM PUBLIC;
REVOKE ALL ON FUNCTION auth_flow_start(bytea, text, uuid, jsonb, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION auth_flow_get(bytea, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION auth_flow_set_data(bytea, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION auth_flow_fail(bytea, text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION auth_flow_take(bytea, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION auth_passkey_lookup(bytea) FROM PUBLIC;
REVOKE ALL ON FUNCTION auth_oauth_lookup(text, text) FROM PUBLIC;
"""

GRANTS = """
GRANT SELECT, INSERT, UPDATE, DELETE
    ON mfa_totp, mfa_recovery_codes, webauthn_credentials, oauth_identities TO {role};
GRANT SELECT ON server_settings TO {role};
GRANT UPDATE (require_mfa, updated_at) ON server_settings TO {role};
GRANT EXECUTE ON FUNCTION auth_has_password() TO {role};
GRANT EXECUTE ON FUNCTION auth_flow_start(bytea, text, uuid, jsonb, integer) TO {role};
GRANT EXECUTE ON FUNCTION auth_flow_get(bytea, text) TO {role};
GRANT EXECUTE ON FUNCTION auth_flow_set_data(bytea, text, jsonb) TO {role};
GRANT EXECUTE ON FUNCTION auth_flow_fail(bytea, text, integer) TO {role};
GRANT EXECUTE ON FUNCTION auth_flow_take(bytea, text) TO {role};
GRANT EXECUTE ON FUNCTION auth_passkey_lookup(bytea) TO {role};
GRANT EXECUTE ON FUNCTION auth_oauth_lookup(text, text) TO {role};
"""

DOWNGRADE = """
DROP FUNCTION auth_has_password();
DROP FUNCTION auth_oauth_lookup(text, text);
DROP FUNCTION auth_passkey_lookup(bytea);
DROP FUNCTION auth_flow_take(bytea, text);
DROP FUNCTION auth_flow_fail(bytea, text, integer);
DROP FUNCTION auth_flow_set_data(bytea, text, jsonb);
DROP FUNCTION auth_flow_get(bytea, text);
DROP FUNCTION auth_flow_start(bytea, text, uuid, jsonb, integer);
DROP TABLE auth_flows, server_settings, oauth_identities, webauthn_credentials,
    mfa_recovery_codes, mfa_totp;
ALTER TABLE sessions DROP COLUMN reauth_at;
"""


def upgrade() -> None:
    run(op, UPGRADE)
    run(op, GRANTS.format(role=app_role()))


def downgrade() -> None:
    run(op, DOWNGRADE)
