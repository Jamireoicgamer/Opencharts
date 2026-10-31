# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLAlchemy Core table definitions used to build queries.

The schema itself is defined by the Alembic migrations (row-level security,
functions and grants do not fit SQLAlchemy's model). ``test_schema.py``
checks that these definitions match the migrated database.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    FetchedValue,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("email", CITEXT, nullable=False),
    Column("display_name", Text, nullable=False),
    Column("password_hash", Text),
    Column("role", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=FetchedValue()),
    Column("disabled_at", DateTime(timezone=True)),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("user_id", Uuid, nullable=False),
    Column("token_hash", LargeBinary, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=FetchedValue()),
    Column("last_seen_at", DateTime(timezone=True), nullable=False, server_default=FetchedValue()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("user_agent", Text),
    Column("ip", Text),
    Column("reauth_at", DateTime(timezone=True), nullable=False, server_default=FetchedValue()),
)

invites = Table(
    "invites",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("token_hash", LargeBinary, nullable=False),
    Column("created_by", Uuid, nullable=False),
    Column("email", CITEXT),
    Column("role", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=FetchedValue()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
    Column("used_by", Uuid),
)

vault_secrets = Table(
    "vault_secrets",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("user_id", Uuid, nullable=False),
    Column("name", Text, nullable=False),
    Column("provider", Text),
    Column("ciphertext", LargeBinary, nullable=False),
    Column("nonce", LargeBinary, nullable=False),
    Column("wrapped_dek", LargeBinary, nullable=False),
    Column("dek_nonce", LargeBinary, nullable=False),
    Column("key_version", Integer, nullable=False),
    Column("hint", Text, nullable=False, server_default=FetchedValue()),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=FetchedValue()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=FetchedValue()),
)

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", BigInteger, primary_key=True, server_default=FetchedValue()),
    Column("user_id", Uuid),
    Column("action", Text, nullable=False),
    Column("target", Text),
    Column("ip", Text),
    Column("user_agent", Text),
    Column("metadata", JSONB, nullable=False, server_default=FetchedValue()),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=FetchedValue()),
    # Anonymous events (user_id NULL) are not readable by the app role, and
    # Postgres checks the read policy on RETURNING rows, so never use it here.
    implicit_returning=False,
)

mfa_totp = Table(
    "mfa_totp",
    metadata,
    Column("user_id", Uuid, primary_key=True),
    Column("ciphertext", LargeBinary, nullable=False),
    Column("nonce", LargeBinary, nullable=False),
    Column("wrapped_dek", LargeBinary, nullable=False),
    Column("dek_nonce", LargeBinary, nullable=False),
    Column("key_version", Integer, nullable=False),
    Column("confirmed_at", DateTime(timezone=True)),
    Column("last_used_step", BigInteger, nullable=False, server_default=FetchedValue()),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=FetchedValue()),
)

mfa_recovery_codes = Table(
    "mfa_recovery_codes",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("user_id", Uuid, nullable=False),
    Column("code_hash", LargeBinary, nullable=False),
    Column("used_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=FetchedValue()),
)

webauthn_credentials = Table(
    "webauthn_credentials",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("user_id", Uuid, nullable=False),
    Column("credential_id", LargeBinary, nullable=False),
    Column("public_key", LargeBinary, nullable=False),
    Column("sign_count", BigInteger, nullable=False, server_default=FetchedValue()),
    Column("transports", ARRAY(Text), nullable=False, server_default=FetchedValue()),
    Column("name", Text, nullable=False),
    Column("backed_up", Boolean, nullable=False, server_default=FetchedValue()),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=FetchedValue()),
    Column("last_used_at", DateTime(timezone=True)),
)

oauth_identities = Table(
    "oauth_identities",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("user_id", Uuid, nullable=False),
    Column("provider", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("email", CITEXT),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=FetchedValue()),
    Column("last_used_at", DateTime(timezone=True)),
)

server_settings = Table(
    "server_settings",
    metadata,
    Column("id", Boolean, primary_key=True),
    Column("require_mfa", Boolean, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=FetchedValue()),
)

# Only reachable through the auth_flow_* SQL functions; defined here so the
# schema check covers it.
auth_flows = Table(
    "auth_flows",
    metadata,
    Column("token_hash", LargeBinary, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("user_id", Uuid),
    Column("data", JSONB, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
