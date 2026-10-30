# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run Alembic migrations programmatically (no alembic.ini needed)."""

from alembic import command
from alembic.config import Config


def alembic_config(url: str, app_role: str) -> Config:
    config = Config()
    config.set_main_option("script_location", "openchart_api:migrations")
    config.attributes["url"] = url
    config.attributes["app_role"] = app_role
    return config


def upgrade(url: str, app_role: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(url, app_role), revision)


def downgrade(url: str, app_role: str, revision: str) -> None:
    command.downgrade(alembic_config(url, app_role), revision)
