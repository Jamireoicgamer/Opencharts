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

- Browser-first React/TypeScript client (planned migration from V4 standalone HTML)
- FastAPI backend, with Docker deployment
- SQLite as initial server-side persistence
- User-controlled market-data and AI providers
- Ollama, OpenAI-compatible, and other optional AI integrations
- Research with source citations and user-editable investment theses
- Saved monitor-specific dashboards and alerts

The V4 prototype is **standalone HTML**. The planned stack has not yet been implemented. See [roadmap](docs/ROADMAP.md) for implementation milestones and [product brief](docs/PRODUCT_BRIEF.md) for project scope.

## Funding

The intention is voluntary donations to support development and infrastructure. Users bring their own API credentials or run local models; no paid API is automatically required by this prototype.

## Licence

**Licence decision pending before public open-source release.** This is initially a private development repository. The project goal is an open-source licence (AGPLv3 is under consideration). Do not assume the code is already licensed for redistribution. Review third-party dependency and data terms before opening the repository.

## Development

Run the basic static repository checks:

```bash
python3 -m unittest discover -s tests -v
```

For issues, describe browser/version, what you expected, what happened, and steps to reproduce. Never submit API keys, credentials or sensitive portfolio data in an issue.

## Motion design (V4.1)

Micro-interactions, short sidebar/popover entrances, and focus feedback use mostly opacity and transforms. Animations are automatically disabled when the system requests reduced motion. Chart rendering, data, and navigation logic were intentionally left unchanged.