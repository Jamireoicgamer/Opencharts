# OpenChart AI — Product brief

OpenChart AI is a donation-supported, local-first, open-source financial terminal, designed for self-hosting on Linux, macOS or Windows and viewing from browsers on desktops, phones and Raspberry Pi monitors. A paid hosted cloud tier may follow, built from the same codebase. The implementation plan is in [PLAN.md](PLAN.md).

## Main features
- **Charts:** Minimalist interactive charts, indicators, drawing tools, multi-chart workspaces, event markers, multiple displays and fullscreen focus mode.
- **Market data:** Keyless sources where possible, bring-your-own provider keys, read-only broker sync and CSV import. Clearly label quotes by source, currency, exchange, timestamp and delay.
- **AI:** Bring-your-own cloud API (Anthropic, OpenAI-compatible, Gemini) or local Ollama/LM Studio model, with privacy controls and user-defined cost limits. A small, cheap model does the reading; a larger model does the analysis.
- **Deep research:** Continuous monitoring of the stocks you pick — filings, earnings, announcements and news — with citations and uncertainty labels.
- **Challenge:** The AI challenges your theses with an adjustable pushback level from gentle to brutal.
- **Learning:** A decision journal and paper trading. Outcomes are scored over time so the AI can learn what has and hasn't worked for you.
- **Thesis:** Store versioned investment theses, conviction, entry/fair value, scenarios, catalysts and invalidation conditions.
- **Risk:** Portfolio holdings, concentration, exposure and user-defined rules. Compute metrics deterministically.
- **Alerts:** Price, risk, technical and thesis-relevant events; scheduled research. Delivered in-app, by web push, email or ntfy/Gotify.
- **Monitor mode:** An always-on display for a room or desk — rotating charts, grids, an AI news ticker and P&L with a privacy blur — with local-only voice commands.
- **Accounts:** Multi-user, Google sign-in, passkeys and two-factor authentication.
- **Settings:** API configuration, privacy toggles, import/export, workspaces and optional donation links.

## Visual direction
Near-black backgrounds, charcoal panels, subtle borders, clear typography, restrained accent colours, no gradients. Chart is the primary surface; secondary panels remain hidden until needed. Motion must be subtle and responsive, and respect reduced-motion preferences. Raspberry Pi performance matters.

## V4.1 prototype limitations
Frontend demonstration only: simulated prices and AI responses, local browser storage, no backend or financial-data subscriptions. Docker currently serves static HTML.

## Reliability and security
Never represent simulated information as live. Preserve source dates and citations; AI must distinguish verified evidence, calculations and interpretations. Do not automatically rewrite investment theses. Trading is paper-only: never execute real trades. Voice audio never leaves the local network. Secrets are encrypted at rest and never sent to the browser. Review securities data rights and UK regulatory obligations before public distribution or personalised investment recommendations.
