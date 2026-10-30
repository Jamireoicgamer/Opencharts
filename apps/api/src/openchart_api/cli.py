# SPDX-License-Identifier: AGPL-3.0-or-later
"""Command-line entry point: ``openchart-api migrate``."""

import argparse
import sys

from openchart_api import migrate
from openchart_api.config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openchart-api")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply database migrations as the schema owner")
    args = parser.parse_args(argv)

    if args.command == "migrate":
        settings = Settings()  # values come from the environment
        if settings.migrate_database_url is None:
            print("OPENCHART_MIGRATE_DATABASE_URL is not set", file=sys.stderr)
            return 2
        migrate.upgrade(settings.migrate_database_url.get_secret_value(), settings.app_role)
        print("Database is up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
