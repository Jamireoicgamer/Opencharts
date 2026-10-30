# OpenChart AI — Product brief

OpenChart AI is a donation-supported, local-first financial terminal, designed for self-hosting on Linux and viewing from browsers on desktops, phones and Raspberry Pi monitors.

## Main features
- **Charts:** Minimalist interactive charts, indicators, workspaces, multiple displays and fullscreen focus mode.
- **Market data:** Bring-your-own provider; clearly label quotes by source, currency, exchange, timestamp and delay.
- **AI:** Bring-your-own cloud API or local Ollama/LM Studio model, with privacy controls and cost limits.
- **Thesis:** Store versioned investment theses, conviction, entry/fair value, scenarios, catalysts and invalidation conditions.
- **Risk:** Portfolio holdings, concentration, exposure and user-defined rules. Compute metrics deterministically.
- **Research:** Company filings, earnings, announcements and news, with citations and uncertainty labels.
- **Alerts:** Price, risk, technical and thesis-relevant events; scheduled research.
- **Settings:** API configuration, import/export, workspaces and optional donation links.

## Visual direction
Near-black backgrounds, charcoal panels, subtle borders, clear typography, restrained accent colours, no gradients. Chart is the primary surface; secondary panels remain hidden until needed. Motion must be subtle and responsive, and respect reduced-motion preferences. Raspberry Pi performance matters.

## V4.1 prototype limitations
Frontend demonstration only: simulated prices and AI responses, local browser storage, no backend or financial-data subscriptions. Docker currently serves static HTML.

## Reliability and security
Never represent simulated information as live. Preserve source dates and citations; AI must distinguish verified evidence, calculations and interpretations. Do not automatically rewrite investment theses or execute trades. Review securities data rights and UK regulatory obligations before public distribution or personalised investment recommendations.
