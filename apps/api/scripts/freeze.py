# SPDX-License-Identifier: AGPL-3.0-or-later
"""Freeze the API into one folder for the desktop app.

    uv sync --group desktop
    uv run python apps/api/scripts/freeze.py [--out DIR]

The result, ``DIR/openchart-api/openchart-api[.exe]``, runs ``migrate`` and
``serve`` with no Python installed. The desktop app ships that folder.
"""

import argparse
import sys
import tempfile
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[3]

ENTRY = """\
import sys
from openchart_api.cli import main
sys.exit(main())
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "apps" / "desktop" / "build" / "api")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as work:
        entry = Path(work) / "openchart_api_main.py"
        entry.write_text(ENTRY)
        PyInstaller.__main__.run(
            [
                str(entry),
                "--name=openchart-api",
                "--onedir",
                "--noconfirm",
                "--clean",
                "--console",
                f"--distpath={args.out}",
                f"--workpath={Path(work) / 'build'}",
                f"--specpath={work}",
                # Alembic reads migrations from files; uvicorn and the
                # providers load modules by name.
                "--collect-all=openchart_api",
                "--collect-submodules=uvicorn",
                "--collect-submodules=websockets",
                "--copy-metadata=openchart-api",
                "--hidden-import=asyncpg.pgproto.pgproto",
            ]
        )
    print(f"Frozen API: {args.out / 'openchart-api'}", file=sys.stderr)


if __name__ == "__main__":
    main()
