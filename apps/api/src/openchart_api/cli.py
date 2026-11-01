# SPDX-License-Identifier: AGPL-3.0-or-later
"""Command-line entry point: ``openchart-api migrate`` and ``openchart-api serve``."""

import argparse
import sys
import threading

from pydantic import ValidationError

from openchart_api import migrate
from openchart_api.config import MigrateSettings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openchart-api")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply database migrations as the schema owner")
    commands.add_parser(
        "bootstrap",
        help="create the database and roles on a fresh Postgres (used by the desktop app)",
    )
    serve = commands.add_parser("serve", help="run the API (and the web app, if static_dir is set)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--exit-with-stdin",
        action="store_true",
        help="stop when standard input closes, so the API never outlives the desktop app",
    )
    args = parser.parse_args(argv)

    if args.command == "bootstrap":
        return _bootstrap()
    if args.command == "serve":
        return _serve(args.host, args.port, exit_with_stdin=args.exit_with_stdin)

    if args.command == "migrate":
        try:
            settings = MigrateSettings()  # values come from the environment or Docker secrets
        except ValidationError:
            print("OPENCHART_MIGRATE_DATABASE_URL is not set", file=sys.stderr)
            return 2
        migrate.upgrade(settings.migrate_database_url.get_secret_value(), settings.app_role)
        print("Database is up to date.")
    return 0


def _bootstrap() -> int:
    import asyncio
    import os

    from openchart_api.bootstrap import bootstrap

    names = (
        "OPENCHART_BOOTSTRAP_ADMIN_URL",
        "OPENCHART_BOOTSTRAP_OWNER_PASSWORD",
        "OPENCHART_BOOTSTRAP_APP_PASSWORD",
    )
    values = [os.environ.get(name, "") for name in names]
    if missing := [name for name, value in zip(names, values, strict=True) if not value]:
        print(f"{', '.join(missing)} not set", file=sys.stderr)
        return 2
    asyncio.run(bootstrap(*values))
    print("Database and roles are ready.")
    return 0


def _serve(host: str, port: int, *, exit_with_stdin: bool) -> int:
    import uvicorn

    from openchart_api.main import create_app

    try:
        app = create_app()
    except ValidationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, proxy_headers=False, server_header=False)
    )
    if exit_with_stdin:

        def watch() -> None:
            while sys.stdin.buffer.read(4096):
                pass
            server.should_exit = True

        threading.Thread(target=watch, daemon=True).start()
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
