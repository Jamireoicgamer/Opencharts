# OpenChart AI

A minimal, near-black, chart-first self-hosted investment terminal — **V4.1 interface prototype**.

![OpenChart V4 panel designs](assets/panels.png)

> **Prototype disclaimer:** This repository currently contains a frontend demonstration, not a connected trading platform. Price charts, quotes and AI responses are simulated. Nothing here constitutes live market data, automated research or investment advice. Do not enter API keys or other secrets.

## What works in V4.1

- Interactive custom canvas-based chart with zoom/pan and timeframe changes
- Instrument search, watchlist and locally saved preferences
- AI assistant interface (scripted demo responses, not a real model)
- Investment thesis editor, valuation assumptions and revision journal
- Research checklist and notes
- Manual portfolio tracking and risk preferences, demo valuations
- Demo price alerts and local one-off checking
- Layout/settings controls, workspace data export
- Minimalist dark UI with responsive/mobile support

> Persistence currently uses **browser localStorage**: each browser and Raspberry Pi stores its own state. This project does **not** yet synchronise data between devices or store data on the host server.

## Run locally

Double-click `index.html` in a modern browser, or serve the directory:

```bash
python3 -m http.server 8080
```

Then open `http://localhost:8080`.

## Run on your server using Docker

```bash
docker compose up -d
```

Access it on the server at `http://localhost:8080`, or on another machine on the **same trusted local network** at `http://YOUR_SERVER_IP:8080`.

For a Raspberry Pi monitor, open the URL in Chromium. For fullscreen kiosk use:

```bash
chromium-browser --kiosk http://YOUR_SERVER_IP:8080
```

The Chromium executable may be `chromium` rather than `chromium-browser`, depending on your distribution.

### Security warning

This static prototype has **no authentication or TLS**. Only use it within a trusted LAN. Do not directly expose port 8080 to the internet or place personal financial details into the demo. When a backend is implemented, secure authentication, HTTPS, access controls and API secret handling are required before public access.

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

The V4 prototype is **standalone HTML**. The planned stack has not yet been implemented. See the [master plan](docs/PLAN.md) for architecture and decisions, the [roadmap](docs/ROADMAP.md) for milestones, and the [product brief](docs/PRODUCT_BRIEF.md) for project scope.

## Funding

The intention is voluntary donations to support development and infrastructure. Users bring their own API credentials or run local models; no paid API is automatically required by this prototype.

## Licence

Copyright (C) 2026 Jamireoicgamer (RemnantCore). OpenChart AI is free software, licensed under the [GNU Affero General Public License v3.0 or later](LICENSE). If you run a modified version as a network service, the AGPL requires you to offer its source code to your users.

- Contributors sign the [Contributor Licence Agreement](CLA.md). It lets the project offer a hosted or commercial edition alongside the open-source one.
- The "OpenChart" and "RemnantCore" names and logos are not covered by the AGPL; see the [trademark policy](TRADEMARKS.md).
- Third-party attributions are listed in [NOTICE](NOTICE).

Review third-party dependency and market-data terms before redistributing the project.

## Development

Run the basic static repository checks:

```bash
python3 -m unittest discover -s tests -v
```

For issues, describe browser/version, what you expected, what happened, and steps to reproduce. Never submit API keys, credentials or sensitive portfolio data in an issue.

## Motion design (V4.1)

Micro-interactions, short sidebar/popover entrances, and focus feedback use mostly opacity and transforms. Animations are automatically disabled when the system requests reduced motion. Chart rendering, data, and navigation logic were intentionally left unchanged.