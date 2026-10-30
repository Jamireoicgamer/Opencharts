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

## M1b — Stronger sign-in
- [ ] Google sign-in (OIDC)
- [ ] TOTP two-factor authentication
- [ ] Passkeys (WebAuthn)

## M2 — Web app shell
- [ ] React + TypeScript port of every V4 panel, backed by the API
- [ ] Import existing browser-local data
- [ ] Installable PWA

## M3 — Live market data
- [ ] Provider interface, canonical instrument IDs, GBX/GBP handling
- [ ] Crypto WebSockets, opt-in delayed equities, first bring-your-own-key adapter
- [ ] TimescaleDB candles, Redis fan-out, client WebSocket with polling fallback
- [ ] Source, timestamp and delay labels on every quote

## M4 — Pro charting
- [ ] Lightweight Charts engine with custom overlay canvas
- [ ] Deterministic indicators (SMA, EMA, VWAP, RSI, MACD, Bollinger, volume)
- [ ] Drawing tools, multi-chart layouts, saved workspaces, event markers

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
- [ ] Security, accessibility and Raspberry Pi performance audits
- [ ] Native installers (.deb/AppImage, Homebrew, winget)
- [ ] Financial regulatory and data redistribution review

## M11 — Future
- [ ] Paid hosted cloud tier
- [ ] Native mobile app
- [ ] Fine-tuned, focused research model
