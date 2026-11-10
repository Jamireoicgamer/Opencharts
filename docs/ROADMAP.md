# Development roadmap

The full plan, including architecture, decisions and acceptance criteria for each milestone, is in [PLAN.md](PLAN.md).

## Current state — V4.1 UI prototype
- [x] Minimal chart-first interface, smooth subtle animations
- [x] Watchlist, thesis, AI, research, portfolio, alerts and settings demo panels
- [x] Browser-local persistence and static Docker hosting
- [x] Master plan agreed ([PLAN.md](PLAN.md))

## M0 — Foundation
- [x] AGPLv3 `LICENSE`, CLA + CLA Assistant, `TRADEMARKS.md`, `NOTICE`
- [x] Move prototype to `legacy/index.html`
- [x] Monorepo scaffold (pnpm workspaces + uv)
- [x] CI: lint, type-check, unit, e2e and dependency audits

## M1a — Accounts and security foundations
- [x] FastAPI, PostgreSQL, migrations, row-level security with a least-privilege app role
- [x] Owner setup with a one-time token, invite-only accounts, email/password (argon2id)
- [x] Server-side sessions, device list and sign-out everywhere, CSRF protection, login rate limiting
- [x] Encrypted secrets vault and append-only audit log
- [x] Web pages for setup, sign-in, invites, devices, API keys and activity
- [x] Docker Compose stack (Postgres, migrate, API, nginx), localhost-only by default, smoke-tested in CI
- [x] Security audit and fixes ([October 2026 report](security/AUDIT-2026-10.md))

## M1b — Stronger sign-in
- [x] Two-factor with an authenticator app (TOTP) and single-use recovery codes
- [x] Passkeys (WebAuthn): passwordless sign-in and second factor
- [x] Google sign-in (OIDC with PKCE): explicit linking or joining by invite
- [x] Owner switch to require two-factor for everyone; recent sign-in needed for sensitive changes

## M2 — Web app shell
- [x] React + TypeScript port of every V4 panel, backed by the API: watchlist, versioned thesis journal, research checklist and notes, holdings, price alerts, settings
- [x] Shared instrument catalogue with canonical IDs (`LSE:BA.`, `NASDAQ:NVDA`, `CRYPTO:BTC-USD`) and Ctrl/⌘ K search
- [x] Import existing browser-local data from the prototype ([guide](guides/import-from-prototype.md)); full JSON export
- [x] Installable PWA with an offline app shell (the API is never cached)

## M3 — Live market data
- [x] Provider interface, canonical instrument IDs, GBX/GBP handling
- [x] Crypto WebSockets (Coinbase, Kraken fallback), opt-in delayed equities (Yahoo Finance), first bring-your-own-key adapter (Twelve Data)
- [x] Candle cache in Postgres, in-process hub, client WebSocket with polling fallback ([decision](PLAN.md#decision-2026-11-one-process-for-market-data); Timescale and Redis when scaling needs them)
- [x] Source, timestamp and delay labels on every quote; candlestick/line charts; live watchlist and holding values; server-side price alerts
- [x] Checked against the live providers (1 November 2026): Coinbase streaming, Kraken failover, Yahoo delayed UK/US quotes, history served from the cache, an alert firing on a live price
- [ ] Twelve Data checked with a real key

## M3½ — Desktop app
- [x] Windows and macOS app (Tauri) that runs everything on one computer, with no server or Docker ([guide](guides/desktop.md))
- [x] Bundled PostgreSQL 16 and frozen API on 127.0.0.1, keys in the system keychain, crash recovery, smoke-tested on each platform in CI
- [x] Signed automatic updates; GitHub makes the password-encrypted update key, and a `desktop-vX.Y.Z` tag publishes a release every install picks up
- [x] Opens straight to the workspace with no sign-in, using a fresh per-launch key only the window gets (servers still sign in)
- [x] The same workspace export/import moves data between the desktop app and a server
- [ ] Code-signed and notarised builds (needs Apple and Windows certificates)
- [ ] Hands-on install check on a fresh Windows and macOS machine
- [ ] Intel Mac build (the bundled OpenSSL is older than the cryptography library needs)

## M4 — Pro charting
- [x] Lightweight Charts engine with an overlay for drawings (a series primitive, so no extra canvas)
- [x] Deterministic indicators (SMA, EMA, VWAP, RSI, MACD, Bollinger, volume), cross-checked against a Python reference ([guide](guides/charts.md))
- [x] Drawing tools: trend line, horizontal level, rectangle, Fibonacci retracement, note; saved per instrument and synced
- [ ] Multi-chart layouts (1, 2, 2×2, 3×3), saved workspaces, compare mode, event markers

## M5 — AI chat
- [ ] Ollama, LM Studio, Anthropic, OpenAI-compatible and Gemini adapters
- [ ] Scout / analyst model roles, privacy toggles, token metering and budgets
- [ ] Chart-aware chat, AI chart annotations, pushback slider

## M6 — Research agents
- [ ] Source collectors (news, GDELT, SEC EDGAR, LSE RNS, Companies House)
- [ ] Scout → analyst pipeline with citations and evidence labels
- [ ] Thesis challenger with user-approved diffs
- [ ] Notifications: web push, email, ntfy/Gotify

## M7 — Journal, paper trading and learning
- [ ] Decision journal and paper trading
- [ ] Outcome scoring and deterministic bias statistics
- [ ] Memory retrieval into AI prompts

## M8 — Monitor mode and voice
- [ ] `/monitor` kiosk route, device pairing, read-only device tokens
- [ ] Scenes: rotating charts, grid, AI ticker, P&L with privacy blur
- [ ] Local voice service: wake word or push-to-talk, STT, intents, TTS
- [ ] Hardware detection and profile suggestions

## M9 — Brokers and import
- [ ] Trading 212 read-only sync
- [ ] CSV import
- [ ] Interactive Brokers adapter

## M10 — Hardening and installers
- [ ] Encrypted backups with restore drill
- [ ] Password reset / owner recovery command, master-key rotation, session cleanup job
- [ ] Base images pinned by digest
- [ ] Security, accessibility and Raspberry Pi performance audits
- [ ] Native installers (.deb/AppImage, Homebrew, winget)
- [ ] Financial regulatory and data redistribution review

## M11 — Future
- [ ] Paid hosted cloud tier
- [ ] Native mobile app
- [ ] Fine-tuned, focused research model
