# OpenChart AI

A minimal, near-black, chart-first, self-hosted investment terminal with AI research — in early development.

> **Status:** the new app currently provides accounts and security foundations (milestone M1a): owner setup, invite-only accounts, signed-in device management, an encrypted vault for API keys and a security activity log. **Market data, charts and AI arrive in later milestones**; nothing in the new app is simulated, so the chart area stays empty until a data source exists. Nothing here is investment advice. See the [roadmap](docs/ROADMAP.md).

The V4.1 interface prototype — simulated prices and scripted AI, browser storage only — is kept in `legacy/` as the design reference.

## Run on your server with Docker

You need Docker with the Compose plugin. From the repository root, create the secrets (database passwords and the vault master key) once:

```bash
sh scripts/gen-secrets.sh
```

Then build and start the stack:

```bash
docker compose up -d --build
```

Open `http://localhost:8080` on the server. The first visit asks for a **setup token** to create the owner account; it is printed in the API logs:

```bash
docker compose logs api | grep "setup token"
```

After that, add other people from **Account → Invites**; there is no open sign-up.

**Back up `secrets/openchart_master_key`.** Without it, saved API keys cannot be decrypted. The `secrets/` folder is private to you and ignored by git.

### Reaching it from other devices

By default the app listens on `127.0.0.1` only. To open it to your local network (for a phone or a Raspberry Pi display), set the bind address when starting:

```bash
OPENCHART_BIND=0.0.0.0 docker compose up -d
```

For a Raspberry Pi monitor, open the URL in Chromium; for fullscreen kiosk use `chromium-browser --kiosk http://YOUR_SERVER_IP:8080` (the executable may be `chromium`).

For access from outside your home, use [Tailscale](https://tailscale.com/) or a [Cloudflare Tunnel with Access](https://developers.cloudflare.com/cloudflare-one/) rather than opening a port on your router. When serving over HTTPS on a domain, set `OPENCHART_PUBLIC_ORIGIN=https://your.domain` so cookies are marked Secure and requests are checked against that origin. See [SECURITY.md](SECURITY.md) for the security model.

### The V4.1 prototype

```bash
docker compose --profile legacy up -d legacy
```

It is served on port 8081. It has **no authentication**; do not enter real data or keys into it.

## Design goals

Modern near-black UI, chart-first focus, optional panels, no gradients, lightweight motion with reduced-motion support, responsive layout, and low-overhead operation on Raspberry Pi displays.

## Planned architecture

- React + TypeScript + Vite installable web app (PWA), with TradingView Lightweight Charts plus a custom overlay layer
- FastAPI backend and background worker, PostgreSQL (TimescaleDB, pgvector), Redis; a lite SQLite mode for laptops
- Multi-user accounts with Google sign-in, passkeys and 2FA; encrypted secrets vault and audit log
- Live market data: keyless sources, bring-your-own-key providers, read-only broker sync (Trading 212 first) and CSV import
- AI via Ollama, LM Studio, Anthropic, OpenAI-compatible or Gemini, with a small "scout" model for research and a larger "analyst" model for synthesis
- Continuous deep research with citations, a thesis challenger, decision journal, paper trading and learning from outcomes
- Always-on monitor mode with local-only voice commands
- Docker Compose profiles and native installers

Accounts, sessions, the vault, the audit log and the Docker stack are implemented; the rest is planned. See the [master plan](docs/PLAN.md) for architecture and decisions, the [roadmap](docs/ROADMAP.md) for milestones, and the [product brief](docs/PRODUCT_BRIEF.md) for project scope.

## Funding

The intention is voluntary donations to support development and infrastructure. Users bring their own API credentials or run local models; no paid API is required.

## Licence

Copyright (C) 2026 Jamireoicgamer (RemnantCore). OpenChart AI is free software, licensed under the [GNU Affero General Public License v3.0 or later](LICENSE). If you run a modified version as a network service, the AGPL requires you to offer its source code to your users.

- Contributors sign the [Contributor Licence Agreement](CLA.md). It lets the project offer a hosted or commercial edition alongside the open-source one.
- The "OpenChart" and "RemnantCore" names and logos are not covered by the AGPL; see the [trademark policy](TRADEMARKS.md).
- Third-party attributions are listed in [NOTICE](NOTICE).

Review third-party dependency and market-data terms before redistributing the project.

## Development

The new app is being built in a monorepo alongside the prototype:

| Path | What it is |
|---|---|
| `apps/web` | React + TypeScript + Vite web app |
| `apps/api` | FastAPI service, database migrations and tests |
| `packages/ui` | Design tokens and shared UI |
| `legacy/` | V4.1 prototype (design reference) |
| `deploy/`, `scripts/` | nginx and Postgres setup, secrets and smoke-test scripts |

You need Node.js 22+, pnpm 10 and [uv](https://docs.astral.sh/uv/). Install dependencies:

```bash
pnpm install
```

```bash
uv sync
```

The API needs PostgreSQL 16. Create a database with an owner role and a separate, least-privilege app role (the API refuses to start as a superuser or as the schema owner), then copy `.env.example` to `.env` and fill it in. Apply migrations:

```bash
uv run openchart-api migrate
```

Start the API on `http://127.0.0.1:8000` (it prints the setup token on first run):

```bash
uv run uvicorn --factory openchart_api.main:create_app --reload
```

In another terminal, start the web app on `http://localhost:5173` (it proxies `/api` to the API):

```bash
pnpm dev
```

Run all checks (CI runs the same ones):

```bash
pnpm lint && pnpm typecheck && pnpm test && pnpm build && pnpm e2e
```

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest
```

```bash
python3 -m unittest discover -s tests -v
```

The API tests need a PostgreSQL superuser connection; each run creates and drops its own database and roles. Without it, the database tests are skipped:

```bash
OPENCHART_TEST_ADMIN_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres uv run pytest
```

To test the whole Docker stack end to end (builds, starts, checks and removes it):

```bash
sh scripts/compose-smoke.sh
```

The first `pnpm e2e` run needs a browser: `pnpm --filter @opencharts/web exec playwright install chromium`.

For issues, describe browser/version, what you expected, what happened, and steps to reproduce. Never submit API keys, credentials or sensitive portfolio data in an issue.

## Motion design (V4.1)

Micro-interactions, short sidebar/popover entrances, and focus feedback use mostly opacity and transforms. Animations are automatically disabled when the system requests reduced motion. Chart rendering, data, and navigation logic were intentionally left unchanged.