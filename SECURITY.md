# Security

OpenChart AI is built to hold sensitive data — API keys, portfolios, investment theses — on hardware you control. Security problems are taken seriously.

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through GitHub's [private vulnerability reporting](https://github.com/Jamireoicgamer/Opencharts/security/advisories/new) for this repository, with steps to reproduce and the version or commit you tested. You will get an acknowledgement, and a fix will be prepared before details are made public.

This is an early-stage project maintained by one person, so there is no bug bounty.

## Security model (current)

- **Accounts.** The first account (the owner) can only be created with a one-time setup token printed in the server logs. After that, accounts are created from invite links only. Passwords are hashed with argon2id.
- **Sessions.** A random 256-bit token in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` when served over HTTPS), stored server-side only as a SHA-256 hash, so sessions can be listed and revoked. Failed sign-ins are rate limited and recorded.
- **Cross-site requests.** Every state-changing request must come from the app's own origin (`Origin` and `Sec-Fetch-Site` checks).
- **Isolation between users.** PostgreSQL row-level security on every table. The API connects as a least-privilege role and refuses to start as a superuser, a role with `BYPASSRLS`, or the schema owner.
- **API keys.** Encrypted with AES-256-GCM using a per-secret key, itself encrypted with a master key kept outside the database (a Docker secret). Keys are write-only through the API: they are never sent back to a browser.
- **Audit log.** Sign-ins, failed attempts, invites and key changes are recorded in an append-only table that even the schema owner cannot modify.
- **Deployment.** Only the web container is published, on `127.0.0.1` by default. nginx sends a strict Content-Security-Policy and other security headers; the app loads no third-party scripts.
- **Supply chain.** Dependencies must be at least 14 days old, GitHub Actions are pinned to commit SHAs, and CI audits JavaScript and Python dependencies.

## Your responsibilities when self-hosting

- Keep `secrets/` private and back up `secrets/openchart_master_key`.
- Do not expose the server directly to the internet. Use Tailscale/WireGuard or a Cloudflare Tunnel with Access, and serve it over HTTPS with `OPENCHART_PUBLIC_ORIGIN` set.
- Keep the host, Docker and this project up to date.

Planned hardening (two-factor sign-in, passkeys, encrypted backups, digest-pinned images) is tracked in the [roadmap](docs/ROADMAP.md).
