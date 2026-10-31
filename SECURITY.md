# Security

OpenChart AI is built to hold sensitive data — API keys, portfolios, investment theses — on hardware you control. Security problems are taken seriously.

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through GitHub's [private vulnerability reporting](https://github.com/Jamireoicgamer/Opencharts/security/advisories/new) for this repository, with steps to reproduce and the version or commit you tested. You will get an acknowledgement, and a fix will be prepared before details are made public.

This is an early-stage project maintained by one person, so there is no bug bounty.

## Audits

- [October 2026](docs/security/AUDIT-2026-10.md): everything up to milestone M1a. 13 findings (4 medium, 6 low, 3 informational), all medium and low ones fixed.

## Security model (current)

- **Accounts.** The first account (the owner) can only be created with a one-time setup token printed in the server logs (wrong tokens are rate limited). After that, accounts are created from invite links only; the token travels in the URL fragment, so it never reaches server logs. Passwords are hashed with argon2id, with at most two hashes running at once so requests cannot exhaust memory.
- **Two-factor and passkeys.** Optional per user, and the owner can require it for everyone (until set up, only the security settings are reachable). Authenticator-app secrets are sealed with the vault; codes are accepted within ±30 seconds and never twice; five wrong codes end the sign-in attempt. Recovery codes are stored as keyed hashes and work once. Passkeys (WebAuthn) are bound to the site, require user verification for passwordless sign-in, and a signature counter that goes backwards (a cloned key) is rejected. Sensitive changes (two-factor, passkeys, password, Google link, the owner's switch) need a sign-in within the last 10 minutes.
- **Google sign-in.** Optional. Authorization code flow with PKCE, state and nonce, bound to the browser by a cookie; ID tokens are verified against Google's keys and the email must be verified by Google. A Google account never creates or takes over an account by itself: it must be linked by its signed-in owner, or come with an invite. Two-factor still applies.
- **Sessions.** A random 256-bit token in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` and `__Host-`-prefixed when served over HTTPS), stored server-side only as a SHA-256 hash, so sessions can be listed and revoked. Signing in again ends the browser's previous session. Failed sign-ins and registrations are rate limited and recorded.
- **Cross-site requests.** Every state-changing request must come from the app's own origin (`Origin` and `Sec-Fetch-Site` checks). With `OPENCHART_PUBLIC_ORIGIN` set, requests for any other host name are refused, which stops DNS rebinding.
- **Isolation between users.** PostgreSQL row-level security on every table. The API connects as a least-privilege role that cannot read password hashes, and refuses to start as a superuser, a role with `BYPASSRLS`, or the schema owner.
- **API keys.** Encrypted with AES-256-GCM using a per-secret key, itself encrypted with a master key kept outside the database (a Docker secret). Keys are write-only through the API: they are never sent back to a browser.
- **Audit log.** Sign-ins, failed attempts, invites and key changes are recorded in an append-only table that even the schema owner cannot modify.
- **Deployment.** Only the web container is published, on `127.0.0.1` by default. Containers run as non-root users with read-only filesystems, no Linux capabilities (except Postgres, which needs them briefly at start) and `no-new-privileges`. nginx sends a strict Content-Security-Policy and other security headers, and rate limits the endpoints that check passwords, codes, passkeys or the setup token. API responses are never cached. The app loads no third-party scripts, and the interactive API docs are off by default.
- **Supply chain.** Dependencies must be at least 14 days old, GitHub Actions are pinned to commit SHAs, and CI audits JavaScript and Python dependencies.

## Your responsibilities when self-hosting

- Keep `secrets/` private and back up `secrets/openchart_master_key`.
- Do not expose the server directly to the internet. Use Tailscale/WireGuard or a Cloudflare Tunnel with Access, and serve it over HTTPS with `OPENCHART_PUBLIC_ORIGIN` set.
- Keep the host, Docker and this project up to date.

Known gaps (password reset, master-key rotation, encrypted backups, digest-pinned images) are listed in the audit and tracked in the [roadmap](docs/ROADMAP.md).
