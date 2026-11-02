# The desktop app

OpenChart for Windows and macOS runs everything on one computer: its own database, the OpenChart service and the app window. You don't need a server, Docker or anything else installed. Your workspace stays on that computer unless you export it.

> **Early builds are unsigned.** Windows and macOS warn about apps from developers they don't know. The steps below show how to open it anyway. Signed builds follow once the project has code-signing certificates.

## Install

Download the installer for your computer from the project's [releases](https://github.com/Jamireoicgamer/Opencharts/releases), or from the **Desktop app** workflow's artifacts on GitHub Actions:

| Computer | File |
|---|---|
| Windows 10 or 11 (64-bit) | `OpenChart_…_x64-setup.exe` (or the `.msi`) |
| Mac with Apple silicon (M1 or later) | `OpenChart_…_aarch64.dmg` |

Macs with an Intel processor aren't supported by the desktop app yet; run the [server version with Docker](../../README.md#run-on-your-server-with-docker) instead.

**Windows:** run the installer. If SmartScreen says "Windows protected your PC", choose **More info**, then **Run anyway**. It installs for your user only, with no administrator rights needed.

**macOS:**
1. Open the `.dmg` and drag OpenChart to Applications.
2. The first time, macOS says it can't check the app for malicious software. Open **System Settings → Privacy & Security**, scroll down, and choose **Open Anyway** next to OpenChart.

## First start

OpenChart creates its database the first time it opens, which takes a few seconds. It then asks for the name, email and password you'll sign in with. There is no setup token to find: the app passes it to the window itself. After that, it's the same app as on a server, with the same workspace, live prices, charts, alerts and two-factor options.

Prices come from the internet. Crypto works straight away. UK and US shares need Yahoo Finance or a Twelve Data key, switched on in **Settings → Data sources** (see the [market data guide](market-data.md)).

## Where things are

| | Windows | macOS |
|---|---|---|
| Your data (database, logs) | `%APPDATA%\ai.openchart.desktop` | `~/Library/Application Support/ai.openchart.desktop` |
| Keys | Windows Credential Manager, entry `ai.openchart.desktop` | Keychain, entry `ai.openchart.desktop` |

The data folder holds the database and a `logs` folder (`api.log`, `postgres.log`). If OpenChart won't start, its window says why and names the log to look at.

The **keys** are the vault's master key and the database passwords. They're kept in your system's keychain, not in the data folder. As a result:
- a copy of the data folder can't be opened by someone else's account;
- a restored data folder needs the same keychain entry. To move to another computer, use export and import (below), not a copy of the folder.

Uninstalling the app leaves your data and keys in place. Delete the folder and the keychain entry to remove everything.

## Moving between the desktop app and a server

Export and import work the same everywhere:
1. On the computer or server you're leaving: **Settings → Your data → Export my workspace**.
2. On the other one: **Settings → Your data → Import an OpenChart export**, and choose the file.

The export carries your watchlist, theses with every version, research notes and checklists, holdings, alerts, chart drawings and preferences (including indicators). Importing merges into what's already there, and importing the same file twice adds nothing. Instruments the other side doesn't know are listed as skipped. Accounts, passwords, passkeys, two-factor and data-source keys are not in the export; set those up again on the other side.

## Updates

When a build is made with the project's update key, OpenChart checks for a new version each time it starts. If there is one, it asks before installing. Each update is checked against the public key built into the app, and anything else is refused. Builds made without the key never check for updates.

## How it works

The window is a [Tauri](https://tauri.app) app. When it starts, it:
1. starts PostgreSQL 16, bundled with the app and reachable only on 127.0.0.1 with a password (no network access from other computers);
2. starts the OpenChart service, the same API as on a server, also on 127.0.0.1;
3. opens the app at `http://localhost:<port>`. Both ports are chosen at random each time.

The page in the window gets no access to the computer beyond what a browser tab has. Links to other sites open in your normal browser. Quitting the app stops the service and the database. If the app crashes, the service stops on its own, and the database is stopped and restarted cleanly the next time the app opens.

## For maintainers: building and releasing

The **Desktop app** workflow (`.github/workflows/desktop.yml`) builds on Windows and macOS (Apple silicon). On each platform it smoke-tests the stack (fresh install, setup, a live Coinbase price, history, export, restart and sign-in) before building the installers.

To build locally on Windows or macOS:

```bash
pnpm install
```

```bash
uv sync --group desktop
```

```bash
pnpm --filter @opencharts/web build
```

```bash
uv run python apps/api/scripts/freeze.py
```

```bash
pnpm --filter @opencharts/desktop stage
```

```bash
pnpm --filter @opencharts/desktop tauri build
```

**Releasing:** push a tag such as `desktop-v0.1.0`. The workflow attaches the installers to a **draft** release, and nothing is public until you publish the draft.

**Automatic updates** need a signing key pair, made once:

```bash
pnpm --filter @opencharts/desktop tauri signer generate -w ~/.tauri/openchart.key
```

1. Add the private key file's contents as the repository secret `TAURI_SIGNING_PRIVATE_KEY`, and its password, if you set one, as `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`.
2. Add the public key as the repository variable `TAURI_UPDATER_PUBKEY`.
3. Keep the private key safe: anyone with it can ship updates to every install.

**Code signing,** when certificates are available:
- **macOS:** add `APPLE_CERTIFICATE` (base64 .p12), `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD` (an app-specific password) and `APPLE_TEAM_ID` as secrets. The build signs and notarises when they're present.
- **Windows:** signing will be added with the chosen certificate service.
