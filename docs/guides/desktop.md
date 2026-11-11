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

OpenChart creates its database the first time it opens, which takes a few seconds, then opens straight to your workspace. There's nothing to sign up for and no password to remember. Otherwise it's the same app as on a server, with the same workspace, live prices, charts and alerts.

### Why there's no sign-in, and what keeps it private

Each time OpenChart opens, it makes a new random key (256 bits) and hands it to two things only: the OpenChart service it has just started, and its own window. The window uses the key to sign you in, then drops it from its address bar. The key is never saved to disk, and a new one replaces it at the next start.

Anything else, such as another app, a web page in your browser, or another computer on your network, doesn't have the key, so it gets the normal sign-in page and nothing else. The service only listens on this computer anyway. Wrong keys are refused, logged under **Account → Activity**, and slowed down after a few tries.

Settings that normally ask you to "confirm it's you" (changing a data-source key, for example) are confirmed the same way, without a password.

If someone else can use your computer account, they can open OpenChart too, just like your email app or files. If that matters to you, lock your computer when you step away.

**Want a password anyway?** Under **Account → Security** you can add a password, a passkey or two-factor. Those are only needed if you open the app's address in a browser yourself (sign in there with the email shown under **Account**); the window keeps signing in on its own. Accounts made with an earlier version, which asked for a password, keep their name, email and password, and now open without asking too.

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

OpenChart checks for a new version each time it starts. If there is one, it asks "OpenChart X is available… Install and restart?" and installs it only if you say yes. Your data and keys are kept.

Every update is signed. The app checks each download against the public key built into it and refuses anything else, so only the project's own releases can update it.

**One manual install first.** Builds made before the update key was set up (including the first ones) don't have the key built in, so they can't update themselves. Install the first version that does by hand, over the top of the old one: your data stays. From then on, updates arrive in the app.

## How it works

The window is a [Tauri](https://tauri.app) app. When it starts, it:
1. starts PostgreSQL 16, bundled with the app and reachable only on 127.0.0.1 with a password (no network access from other computers);
2. starts the OpenChart service, the same API as on a server, also on 127.0.0.1;
3. opens the app at `http://localhost:<port>`. Both ports are chosen at random each time.

The page in the window gets no access to the computer beyond what a browser tab has. Links to other sites open in your normal browser. Quitting the app stops the service and the database. If the app crashes, the service stops on its own, and the database is stopped and restarted cleanly the next time the app opens.

## For maintainers: building and releasing

The **Desktop app** workflow (`.github/workflows/desktop.yml`) builds on Windows and macOS (Apple silicon). On each platform it smoke-tests the stack (fresh install, desktop sign-in and a refused wrong key, a live Coinbase price, history, export, restart with a new key, and "confirm it's you") before building the installers.

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

**Setting up automatic updates** (once). GitHub makes the key; you never handle it unencrypted:
1. Choose a long password (at least 16 characters; a password manager can make one). In the repository, open **Settings → Secrets and variables → Actions → Secrets → New repository secret**. Name it `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` and paste the password.
2. Open **Actions → Create update key → Run workflow → Run workflow**. It takes about a minute.
3. On the finished run, download **update-key** and unzip it. It holds two text files:
   - `TAURI_SIGNING_PRIVATE_KEY.txt`: add it as a **secret** with that name (paste the whole file).
   - `TAURI_UPDATER_PUBKEY.txt`: add it as a **variable** (the **Variables** tab) with that name.
4. Delete the unzipped files, then delete the run (its **…** menu), so the key isn't kept there.

The private key is encrypted with your password, and the repository is public, so it is only ever uploaded encrypted; the download is useless without the password, and it expires after a day anyway. Keep the password secret where it is. If the key or password is lost, installed apps can't receive updates and must be reinstalled by hand with a new key, so the workflow refuses to replace an existing key unless you tick **Replace the existing key**.

**Releasing a version:** push a tag such as `desktop-v0.2.0` (three numbers; each release must be higher than the last). The workflow builds that version and, with the update key set up, publishes the release, which every installed app picks up next time it opens. Without the key, it makes a **draft** release instead, which stays private until you publish it.

**Code signing,** when certificates are available:
- **macOS:** add `APPLE_CERTIFICATE` (base64 .p12), `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD` (an app-specific password) and `APPLE_TEAM_ID` as secrets. The build signs and notarises when they're present.
- **Windows:** signing will be added with the chosen certificate service.
