# SPDX-License-Identifier: AGPL-3.0-or-later
"""Runtime configuration.

Every setting can come from an ``OPENCHART_*`` environment variable, a
``.env`` file, or a file of the same (lower-case) name in
``/run/secrets`` — the Docker secrets mount — so passwords and the master
key never have to live in plain environment variables.
"""

import base64
import binascii
import os
from functools import cached_property
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MASTER_KEY_BYTES = 32
MIN_SETUP_TOKEN_LENGTH = 16
MIN_DESKTOP_TOKEN_LENGTH = 32
_DOCKER_SECRETS = "/run/secrets"


_CONFIG = SettingsConfigDict(
    env_prefix="OPENCHART_",
    env_file=".env",
    secrets_dir=_DOCKER_SECRETS if os.path.isdir(_DOCKER_SECRETS) else None,
    extra="ignore",
)


class MigrateSettings(BaseSettings):
    """What `openchart-api migrate` needs: schema-owner access, nothing else."""

    model_config = _CONFIG

    migrate_database_url: SecretStr
    # Role the API connects as; the migrations grant it table access.
    app_role: str = "openchart_app"


class Settings(BaseSettings):
    model_config = _CONFIG

    # Least-privilege role the API connects as. Row-level security applies to it.
    database_url: SecretStr
    # Role that owns the schema; only used by `openchart-api migrate`.
    migrate_database_url: SecretStr | None = None
    # 32 random bytes, base64-encoded. Encrypts the secrets vault.
    master_key: SecretStr
    # Public URL of the web app, e.g. https://charts.example.com. Used for
    # the CSRF origin check and to decide whether cookies are Secure.
    public_origin: str | None = None
    # One-time token required to create the owner account. Generated and
    # logged at startup when unset and no users exist.
    setup_token: SecretStr | None = None
    # Set only by the desktop app, fresh on every launch: presenting it to
    # POST /api/auth/desktop signs in as the owner, without a password.
    # Servers never set it, and the endpoint does not exist without it.
    desktop_token: SecretStr | None = None
    # Serve interactive API docs at /api/docs. Off by default: they reveal the
    # whole API surface and load scripts from a CDN that the CSP blocks.
    api_docs: bool = False
    session_ttl_days: int = 30
    # Serve the built web app from this folder, with nginx's security
    # headers. Used by the desktop app; servers use nginx instead.
    static_dir: str | None = None
    # Run the market-data hub: live prices, history fetching and alert checks.
    market_data: bool = True
    invite_ttl_hours: int = 72
    # Google sign-in (optional). Needs public_origin: Google redirects back to
    # {public_origin}/api/auth/google/callback. See docs/guides/google-sign-in.md.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None

    @field_validator("google_client_id", "google_client_secret", mode="before")
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        # An empty Docker secret file or env var means "not configured".
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("master_key")
    @classmethod
    def _check_master_key(cls, value: SecretStr) -> SecretStr:
        try:
            raw = base64.b64decode(value.get_secret_value(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("master_key must be base64") from exc
        if len(raw) != MASTER_KEY_BYTES:
            raise ValueError(f"master_key must decode to {MASTER_KEY_BYTES} bytes")
        return value

    @field_validator("desktop_token")
    @classmethod
    def _check_desktop_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < MIN_DESKTOP_TOKEN_LENGTH:
            raise ValueError(
                f"desktop_token must be at least {MIN_DESKTOP_TOKEN_LENGTH} characters"
            )
        return value

    @field_validator("setup_token")
    @classmethod
    def _check_setup_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < MIN_SETUP_TOKEN_LENGTH:
            raise ValueError(f"setup_token must be at least {MIN_SETUP_TOKEN_LENGTH} characters")
        return value

    @field_validator("public_origin")
    @classmethod
    def _check_public_origin(cls, value: str | None) -> str | None:
        if not value:
            return None
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.path not in ("", "/"):
            raise ValueError("public_origin must look like https://host[:port]")
        return f"{parts.scheme}://{parts.netloc}"

    @cached_property
    def master_key_bytes(self) -> bytes:
        return base64.b64decode(self.master_key.get_secret_value())

    @property
    def desktop(self) -> bool:
        return self.desktop_token is not None

    @property
    def cookie_secure(self) -> bool:
        return self.public_origin is not None and self.public_origin.startswith("https://")

    @property
    def public_host(self) -> str | None:
        """Host name (without port) of ``public_origin``, if set."""
        return urlsplit(self.public_origin).hostname if self.public_origin else None

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.public_origin)

    @property
    def app_role(self) -> str:
        """Database role name of the least-privilege API connection."""
        role = urlsplit(self.database_url.get_secret_value()).username
        if not role:
            raise ValueError("database_url must include a user name")
        return role
