# OpenChart AI — Master plan

This plan turns the V4.1 single-file prototype into a working, self-hostable AI investment terminal: real market data, an AI that actually researches and challenges you, server-side storage with multi-device sync, and a 24/7 monitor mode with local voice commands.

It is written to be executed in **small, reviewable pull requests** (most by the owner working with Claude). Every milestone in §13 is a list of PR-sized tasks with acceptance criteria. The checklist version lives in [ROADMAP.md](ROADMAP.md); scope and tone live in [PRODUCT_BRIEF.md](PRODUCT_BRIEF.md).

---

## 1. Vision and principles

OpenChart AI is a **local-first, open-source investment terminal** that anyone can run on a laptop, gaming PC, home server or Raspberry Pi display. A paid hosted cloud tier may follow later, built from the same codebase.

Principles, in priority order:

1. **Security and privacy first.** Secrets never reach the browser. Personal data only leaves the server when the user allows that category. Voice never leaves the local network.
2. **Never mislead.** Simulated data is never presented as live. Every quote shows its source, timestamp and delay. Every AI claim is labelled as verified evidence (with a dated citation), a deterministic calculation, or interpretation.
3. **The AI advises, the user decides.** The AI researches, challenges and remembers. It never edits a thesis by itself and never places a real trade. Trading is paper-only.
4. **Chart-first, minimal.** Keep the V4 near-black, no-gradient visual language. Secondary panels stay hidden until needed. Motion is subtle and respects reduced-motion.
5. **Runs on anything.** Hardware is detected and the right profile is suggested (§9). The Pi is a first-class display client.
6. **User owns the costs.** Bring your own data keys and AI keys, or run local models. Spending limits are fully user-defined.

---

## 2. Decision log

Decisions agreed during planning (October 2026):

| Area | Decision |
|---|---|
| Scope | Everything: real data, real AI, backend + sync, UI polish |
| Frontend | React + TypeScript + Vite monorepo. Installable PWA now; native mobile app later (Capacitor or React Native) |
| Charts | **Both**: TradingView Lightweight Charts (Apache-2.0, attribution in `NOTICE`) as the rendering engine, plus a custom canvas overlay for drawings, AI annotations, event markers and the V4 look |
| Backend | FastAPI + PostgreSQL (TimescaleDB for candles, pgvector for AI memory). An embedded **lite mode** (SQLite, in-process jobs) for laptops and small installs |
| Market data | Keyless sources first (crypto exchange WebSockets, delayed equities), bring-your-own-key adapters (Finnhub, Twelve Data, Alpha Vantage, Polygon, Tiingo), read-only broker sync, CSV import |
| Live-ness | Stream where the provider supports it; poll as a fallback |
| Markets | UK (LSE, GBP/GBX), US (NYSE/NASDAQ), crypto, ETFs/funds/FX/indices |
| AI providers | Ollama, LM Studio, Anthropic Claude, any OpenAI-compatible endpoint, Google Gemini |
| AI tiers | A small, cheap **scout** model gathers and summarises; a large **analyst** model synthesises. Spending is entirely user-controlled. A focused fine-tuned model comes later |
| AI powers | Continuous deep research on watched stocks, web research with citations, thesis challenger, drawing on the chart, personal assistant that learns from past outcomes |
| Pushback | User-adjustable slider from Gentle to Brutal |
| Trading | Paper trading only. No real orders |
| Learning | Decision-journal outcomes, thesis track record, user preferences, paper-trade results |
| Broker | Trading 212 first (commission-free, UK, official API); Interactive Brokers second |
| Auth | Multi-user from day one. Google sign-in, email + password, TOTP and passkeys |
| Security | Encrypted secrets vault, 2FA/passkeys, audit log, encrypted backups |
| Remote access | Tailscale/WireGuard and Cloudflare Tunnel + Access, both documented. No raw port exposure by default |
| Privacy | Per-category toggles for what may be sent to cloud AI. Money amounts sent as percentages by default |
| Monitor mode | 24/7 kiosk: rotating watchlist charts, multi-chart grid, AI news ticker + alerts, portfolio P&L with privacy blur |
| Voice | Local only. Wake word **or** push-to-talk, chosen per device. View + safe actions, with spoken confirmation for writes |
| Notifications | In-app + web push, email, ntfy/Gotify |
| Hardware | All tiers supported and auto-detected (§9) |
| Install | Docker Compose with profiles, plus native installers |
| Licence | **AGPLv3 + Contributor Licence Agreement + trademark policy** for the "OpenChart" name |
| Funding | Donations (GitHub Sponsors / Ko-fi) and a future paid hosted cloud tier |
| Prototype | Moves to `legacy/index.html` and stays as the design reference |
| Build order | Foundation → Data → AI → Monitor → Brokers/Learning |

---

## 3. Architecture

### Repository layout

A monorepo: pnpm workspaces for TypeScript, uv for Python.

```
apps/
  web/            React + TS + Vite PWA
                  routes: /  /monitor  /research  /journal  /paper  /settings
  api/            FastAPI: REST + WebSocket, auth, vault, audit log, OpenAPI schema
  worker/         background jobs (arq on Redis): ingestion, research agents,
                  alerts, outcome scoring, backups
  voice/          local-only voice service: wake word, STT, intent, TTS
                  (container has no internet egress)
packages/
  ui/             design tokens ported from V4, components, motion + reduced-motion
  chart/          Lightweight Charts wrapper + overlay canvas
                  (drawings, AI annotations, event markers)
  indicators/     deterministic TS indicators, cross-checked against Python
  api-client/     typed client generated from the API's OpenAPI schema
legacy/
  index.html      V4.1 prototype (design reference)
deploy/
  compose.yaml    with profiles (§11)
  guides/         Tailscale, Cloudflare Tunnel, Caddy, Raspberry Pi kiosk
  installers/     .deb / AppImage, Homebrew, winget
docs/
```

### Runtime components

```
 data providers ──► worker (adapters, normaliser) ──► Postgres/Timescale
        │                                                   │
        └──── live ticks ──► Redis pub/sub ──► api WebSocket ──► web / monitor clients
                                                    ▲
 AI providers ◄──── worker (research) / api (chat) ─┘
 voice (LAN only) ──► api (scoped device token, safe-action allowlist)
```

- **api** is stateless and horizontally scalable (important for the cloud tier).
- **worker** owns everything scheduled or long-running.
- **Lite mode** collapses api + worker into one process with SQLite and an in-process scheduler, for laptops and Macs. It has the same API surface, without Timescale or pgvector optimisations.

---

## 4. Market data layer

### Provider interface

Each adapter implements `MarketDataProvider` and declares capability flags:
`search`, `quote`, `history`, `stream`, `fundamentals`, `events` (earnings, dividends, splits).

### Canonical instruments

- Canonical IDs, e.g. `LSE:BA.`, `NASDAQ:NVDA`, `CRYPTO:BTC-USD`, `FX:GBP-USD`. Each adapter maps to and from its own symbols.
- Currency handled explicitly, including LSE pence (GBX) → pounds (GBP) normalisation.
- Every quote carries `source`, `exchange`, `currency`, `timestamp` and `delay` (real-time / 15-minute delayed / end-of-day), and the UI always displays them.

### Routing

- A provider router picks a provider per instrument by user priority and capability, with automatic failover.
- Per-provider rate-limit budgets; history is cached in Timescale so it's fetched once.
- Streaming providers publish ticks to Redis; others are polled on a per-provider interval. The client sees one WebSocket either way.

### Sources

| Type | Sources | Notes |
|---|---|---|
| Keyless | Binance, Coinbase, Kraken WebSockets (crypto); delayed equity sources | Delayed equity sources are **opt-in** with a terms-of-use warning |
| Bring your own key | Finnhub, Twelve Data, Alpha Vantage, Polygon, Tiingo | Key stored in the vault (§10) |
| Broker (read-only) | Trading 212, then IBKR | Holdings and quotes only, never orders |
| Import | CSV (OHLC files, broker exports) | Mapped to the same schema |

Each adapter ships with recorded-fixture contract tests and a short note on the provider's terms of use.

---

## 5. Charts and UI

- **Design system:** port the V4 tokens (near-black backgrounds, charcoal panels, subtle borders, accent greens/reds, no gradients) into `packages/ui`.
- **Engine:** Lightweight Charts for candles/line/area, a live-updating last bar, crosshair and OHLC readout.
- **Overlay canvas** (custom, on top of the engine) for:
  - drawing tools: trendline, horizontal level, Fibonacci retracement, rectangle, text note. Saved per user per instrument;
  - AI annotations, received as structured tool output and drawn with an "AI" badge. The user accepts or dismisses them;
  - event markers: earnings, dividends, news, your paper trades, thesis revisions.
- **Indicators:** SMA, EMA, VWAP, RSI, MACD, Bollinger Bands, volume. Computed deterministically in `packages/indicators`, never by the AI.
- **Layouts:** 1 / 2 / 2×2 / 3×3 grids, compare mode, saved workspaces per user and per device.
- **Raspberry Pi budget:** under 200KB of JS on `/monitor`, a 30fps cap, devicePixelRatio clamped to 2.

---

## 6. AI system

### Providers and roles

A thin in-house adapter per provider (streaming + tool calls), rather than a large third-party abstraction library. This keeps dependencies small and auditable.

Settings map each **role** to any provider and model:

| Role | Typical choice | Used for |
|---|---|---|
| scout | small/fast tier (e.g. a Haiku-class model, or a local 3–8B model) | reading sources, extraction, summarising, relevance scoring |
| analyst | large tier (cloud frontier model, or a local 14B+ model on capable hardware) | daily briefs, thesis challenges, chat |
| embedder | local embedding model | deduplication and memory retrieval |
| voice-intent | small local model | voice command fallback parsing (§9) |

### Research pipeline (worker)

1. **Collect.** For each watched instrument, poll sources: news RSS, GDELT, SEC EDGAR, LSE RNS announcements, Companies House, company investor-relations pages, and price/volume anomalies detected by code.
2. **Scout.** The small model extracts facts, summarises, and scores relevance and novelty. Near-duplicates are removed with pgvector.
3. **Analyst.** The large model writes daily and urgent briefs and checks each new finding against the user's thesis.
4. **Notify.** Findings go to the in-app feed, web push, email or ntfy/Gotify, depending on urgency and user settings.

### Evidence rules

- Every claim is labelled **Verified** (with source link and date), **Calculation** (done by deterministic code) or **Interpretation**.
- Fetched web content is untrusted. The scout stage has **no tools**, so instructions hidden in a web page can't trigger actions (prompt-injection defence).
- Uncertainty is stated, not hidden.

### Thesis challenger

Compares new evidence against the stored thesis, its bull/bear cases and invalidation conditions. It **proposes** changes as a diff that the user approves or rejects. It never auto-edits.

### Pushback slider

Five levels, Gentle → Brutal. The level changes the system prompt, how often the AI asks probing questions, and how prominent the bear case is.

### Chat assistant

- Context: the current instrument, visible candles, active indicators, thesis, portfolio (subject to privacy toggles) and relevant memories (§7).
- Tools: draw annotation, set alert, log journal entry, fetch research, open layout.

### Cost controls

Token metering per provider and per role, optional budgets with automatic fallback to a local model, and a usage dashboard. All of it is user-defined; nothing is enforced by default.

---

## 7. Learning and memory

- **Decision journal:** every buy/sell/skip/paper trade records the action, reasoning, confidence (%), tags and a market snapshot.
- **Outcome scoring:** at 1 week, 1 month, 3 months and 1 year, compared with a benchmark (e.g. FTSE All-Share, S&P 500, BTC).
- **Bias statistics**, all computed deterministically: hit rate, disposition effect (selling winners early, holding losers), holding-period asymmetry, and confidence calibration.
- **Thesis track record:** which theses were right or wrong, and which signals and sources were predictive for this user.
- **Source reliability scores:** feed back into research ranking.
- **Preference memory:** style, risk tolerance, sectors, preferred tone.
- **Retrieval:** relevant history is pulled into prompts, e.g. "the last three times you bought on a breakout, two lost money within a month".
- **Later (M11):** an opt-in, anonymised dataset to fine-tune (LoRA) a small, focused open model. It runs locally and is specialised for this job rather than large.

---

## 8. Paper trading

- Market, limit and stop orders, filled against live quotes, with slippage and fees modelled.
- Multi-currency (GBP/USD); ISA/GIA account tags; realised and unrealised P&L.
- Every order creates a journal entry automatically, which feeds learning (§7).
- Clearly labelled "Paper" everywhere. There is no code path to a real order.

---

## 9. Monitor mode, voice and hardware

### Monitor mode (`/monitor`)

- A device pairs with the server via a QR code or short code and receives a scoped, revocable **read-only device token**.
- Scenes, configurable per device:
  - rotating watchlist charts;
  - fixed multi-chart grid;
  - AI news ticker + alerts;
  - portfolio P&L dashboard with a privacy-blur toggle.
- Burn-in protection: periodic pixel shift and a night dimming schedule.
- Survives network drops: reconnects and shows "stale" labels rather than old prices as live.

### Voice (local only)

- Runs in `apps/voice` on the LAN. The container has **no outbound internet access**, and audio is processed in memory and **never stored**.
- Per-device choice of **wake word** ("Hey OpenChart", openWakeWord) or **push-to-talk**.
- Speech-to-text: faster-whisper on GPU, whisper.cpp on CPU.
- Intent: a grammar-first parser ("show NVIDIA daily", "switch to grid", "set alert BAE above 20"), with a small local LLM as fallback.
- Replies: Piper text-to-speech.
- Permissions: an allowlist of view actions and safe actions (switch instrument/layout, ask the AI, set an alert, log a paper trade). Any write needs a spoken confirmation. Account, settings and key changes are blocked by voice.

### Hardware tiers

On first run the app detects CPU, RAM and GPU and suggests a profile.

| Tier | Example | Suggested setup |
|---|---|---|
| Laptop / Mac | M-series Mac, 16GB laptop | Lite mode; cloud AI or a small local model; whisper.cpp tiny/base |
| Gaming PC / GPU server | Ryzen 5, RTX 3060 12GB, 32–40GB RAM | Full stack; 7–14B local models via Ollama; faster-whisper; wake word |
| Raspberry Pi 4/5 | Pi + monitor | Display client only (`/monitor` in Chromium kiosk); push-to-talk, with the server doing STT |
| Cloud | Hosted tier | Full stack, cloud AI providers, no voice |

---

## 10. Security and privacy

- **Multi-user isolation:** a `user_id` on every row plus PostgreSQL row-level security. Roles: owner, admin, member, device.
  - Two database roles: the schema owner (used only by the one-shot `migrate` container) and a least-privilege app role. The API refuses to start if its role is a superuser, has `BYPASSRLS`, or owns the schema.
  - Lookups needed before a user is known (sign-in, session cookie, first-run setup, invite redemption) go through narrow `SECURITY DEFINER` functions.
- **Authentication:** Google sign-in (OIDC), email + password (argon2id), TOTP, WebAuthn passkeys. httpOnly SameSite cookies, CSRF protection, and a session/device list with revoke.
- **Secrets vault:** API keys and broker tokens use AES-256-GCM envelope encryption. The master key comes from a Docker secret or key file, never the database. Secrets are never returned to the browser; the UI only shows the last four characters.
- **Audit log:** append-only record of logins, key use, AI calls, data exports and setting changes, viewable in settings.
- **Encrypted backups:** scheduled restic/age backups to local disk or S3-compatible storage, with a documented restore drill.
- **Hardening:**
  - strict Content-Security-Policy and no third-party scripts;
  - rate limiting;
  - an outbound egress allowlist per service;
  - dependency audits (pnpm audit, pip-audit), Dependabot with a 14-day cooldown, a 14-day minimum release age in pnpm and uv, GitHub Actions pinned to commit SHAs, and an SBOM, container image scanning and base images pinned by digest (M10).
- **Safe defaults:** Docker publishes the web app on localhost only unless `OPENCHART_BIND` says otherwise; the API and database ports are never published. Creating the owner account needs a one-time **setup token** printed in the API logs, so nobody else on the network can claim the server first. After that, accounts are invite-only.
- **Privacy toggles:** per category (tickers, theses, journal, portfolio sizes). Money amounts are sent as percentages unless the user allows otherwise.
- **Remote access:** guides for Tailscale/WireGuard and Cloudflare Tunnel + Access. Opening ports directly is documented only as an advanced option with a hardening checklist.

---

## 11. Deployment

- **Docker Compose profiles:**
  - `core`: api, worker, web, postgres, redis;
  - `ollama`: local models;
  - `gpu`: NVIDIA runtime for Ollama and STT;
  - `voice`: local voice service;
  - `monitor`: kiosk helper for Pi/display machines.
- **First-run wizard:** create the owner account, set up 2FA, detect hardware, choose data and AI providers, set privacy toggles.
- **Native installers (M10):** `.deb`/AppImage, Homebrew and winget packages. They either drive Docker or run lite mode.
- **Cloud mode:** `DEPLOYMENT_MODE=cloud` enables billing, managed data licences and organisation features for the future paid tier. The self-hosted edition stays free and complete.

---

## 12. Licensing, legal and funding

- **Licence:** AGPLv3. Anyone may use, study, modify and share the code, but anyone who runs a modified version as a service must publish their source.
- **CLA** (via CLA Assistant): contributors grant the project the right to offer a commercially licensed or hosted edition, so the paid cloud tier remains possible.
- **Trademark policy** (`TRADEMARKS.md`): forks may not use the "OpenChart" name or logo.
- **NOTICE:** third-party attributions, including TradingView Lightweight Charts.
- **Market data:** each adapter's terms of use are reviewed. The cloud tier does not redistribute data without proper licences.
- **UK regulation:** OpenChart is a research and journaling tool, not investment advice. No personalised recommendations; clear disclaimers; paper trading only.
- **Funding:** GitHub Sponsors and Ko-fi links in settings and the README. Self-hosting stays free; the paid tier charges for hosting and convenience.

---

## 13. Milestones

Each milestone is roughly 3–8 small PRs. A PR should be reviewable in one sitting and leave `main` working.

### M0 — Foundation
- Add `LICENSE` (AGPLv3), `CLA.md` + CLA Assistant workflow, `TRADEMARKS.md`, `NOTICE`.
- Move the prototype to `legacy/index.html`; update `compose.yaml` and `tests/test_static.py` to match.
- Scaffold the monorepo (pnpm + uv), shared lint/format config.
- CI: ruff, mypy, pytest, eslint, tsc, vitest, Playwright, dependency audits.
- **Done when:** CI is green on an empty app skeleton and the legacy demo still serves.

### M1 — Backend and authentication
- FastAPI app, settings, health check, OpenAPI generation.
- Postgres + Alembic migrations; users, roles and row-level security.
- Google sign-in, email/password, TOTP, passkeys; sessions and device list.
- Secrets vault and audit log.
- Compose `core` profile; localhost-only until auth is configured.
- **Done when:** two users can sign in and cannot see each other's data (tested).

### M2 — Web app shell (parity with V4)
- React port of every V4 panel (watchlist, thesis, AI, research, portfolio, alerts, settings) backed by the API.
- One-click import of existing `oc-*` localStorage data.
- PWA install and offline shell.
- **Done when:** everything the prototype did works against the server and syncs across two browsers.

### M3 — Live market data
- Provider interface, canonical IDs, currency/GBX handling.
- Crypto exchange WebSockets; opt-in keyless delayed equities; first bring-your-own-key adapter (Finnhub or Twelve Data).
- Timescale candle storage; Redis fan-out; client WebSocket with polling fallback.
- Source / timestamp / delay labels in the UI.
- **Done when:** BTC streams live, NVDA and BAE show correctly labelled delayed quotes, and history loads from cache.

### M3½ — Desktop app (added October 2026)
- A Windows and macOS app (Tauri) for people who want OpenChart on one laptop or PC without running a server or Docker.
- Bundles the API with an embedded database; one local user; signed builds with automatic updates.
- Moves data to and from a server with the workspace export/import.
- **Done when:** a fresh Windows and macOS machine can install it, sign in, keep a watchlist and see live prices with nothing else installed.

### M4 — Pro charting
- Lightweight Charts engine + overlay canvas.
- Indicators package with cross-language tests.
- Drawing tools, layouts, workspaces, compare mode, event markers.
- **Done when:** a 2×2 layout with indicators and drawings persists and reloads on another device.

### M5 — AI chat
- Provider adapters (Ollama, LM Studio, Anthropic, OpenAI-compatible, Gemini) and role mapping.
- Privacy toggles, token metering and budgets.
- Chart-aware chat with tools; AI chart annotations; pushback slider.
- **Done when:** the same question works through a local model and a cloud model, with costs shown and private data handled per the toggles.

### M6 — Research agents
- Source collectors (news RSS, GDELT, EDGAR, RNS, Companies House).
- Scout → analyst pipeline with deduplication and evidence labels.
- Thesis challenger with proposed diffs.
- Notifications: web push, email, ntfy/Gotify.
- **Done when:** a watched stock gets a cited daily brief, and a contradicting news item triggers a thesis challenge notification.

### M7 — Journal, paper trading and learning
- Decision journal; paper orders and fills; P&L.
- Outcome scoring jobs; bias statistics; memory retrieval into prompts.
- **Done when:** after a set of seeded historical decisions, the AI correctly cites the user's own patterns.

### M8 — Monitor mode and voice
- `/monitor` route, device pairing and tokens, scenes, burn-in protection.
- Voice service (wake word / push-to-talk, STT, intent, TTS) with the safe-action allowlist.
- Hardware detection and profile suggestion.
- **Done when:** a Pi shows the rotating scene for 72 hours without leaks, and "Hey OpenChart, show Rolls-Royce weekly" works offline.

### M9 — Brokers and import
- Trading 212 read-only holdings sync.
- CSV import (OHLC and broker exports).
- Interactive Brokers adapter.
- **Done when:** real holdings appear in the portfolio and feed P&L and risk views.

### M10 — Hardening and installers
- Encrypted backups and restore drill.
- Security review, accessibility audit (WCAG 2.1 AA), Raspberry Pi performance pass.
- Native installers (.deb/AppImage, Homebrew, winget).
- **Done when:** a fresh machine goes from installer to a working dashboard in under 10 minutes.

### M11 — Future
- Paid hosted cloud tier (billing, organisations, data licensing).
- Native mobile app.
- Fine-tuned, focused research model.

---

## 14. Testing strategy

- **Python:** pytest unit tests; provider contract tests on recorded fixtures (no live network in CI).
- **TypeScript:** vitest; indicator results cross-checked against Python reference values.
- **End-to-end:** Playwright, covering sign-in → chart → AI question → alert.
- **Security:** tests proving row-level isolation between users, vault round-trips, and that voice and device tokens can't reach blocked actions.
- **Quality gates:** axe accessibility checks; a Lighthouse performance budget on `/monitor`.
- The existing `tests/test_static.py` keeps guarding the legacy prototype.

---

## 15. Risks and open questions

| Risk | Mitigation |
|---|---|
| Keyless equity data terms of use | Opt-in with a warning; recommend BYOK providers; never redistribute in the cloud tier |
| LSE real-time data is expensive | Default to delayed data, clearly labelled |
| Trading 212 API is in beta (Invest/ISA only) | Read-only scope; IBKR as a second adapter |
| Wake-word false triggers | Per-device sensitivity; push-to-talk option; spoken confirmation for writes |
| Google OAuth verification for the public cloud | Start verification during M11; self-host uses the user's own OAuth client |
| AGPL obligations for the hosted tier | The CLA allows the project to offer a hosted/commercial edition |
| AI hallucination | Evidence labels, mandatory citations, deterministic calculations, thesis changes need approval |
| Scope is large for a small team | Strict milestone order; each PR leaves `main` working |
