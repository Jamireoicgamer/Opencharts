# SPDX-License-Identifier: AGPL-3.0-or-later
"""Password hashing, opaque tokens and login rate limiting."""

import hashlib
import secrets
import time
from collections import deque
from dataclasses import dataclass, field

from anyio import to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 256

# argon2id with the library's RFC 9106 "low memory" profile (64 MiB, t=3).
_hasher = PasswordHasher()
# Verified against when the email is unknown, so response time does not reveal
# which accounts exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


async def hash_password(password: str) -> str:
    return await to_thread.run_sync(_hasher.hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    def verify() -> bool:
        try:
            return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
        except (VerificationError, InvalidHashError):
            return False

    return await to_thread.run_sync(verify)


def new_token() -> str:
    """A 256-bit random token for cookies and invite links."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    """Tokens are stored only as SHA-256 hashes."""
    return hashlib.sha256(token.encode()).digest()


@dataclass
class LoginRateLimiter:
    """Counts failed logins per (IP, email) and per IP in a sliding window.

    State lives in this process only. That is fine for the single API process
    of a self-hosted install; a shared store (Redis) replaces it when the API
    scales out.
    """

    max_per_account: int = 5
    max_per_ip: int = 30
    window_seconds: float = 15 * 60
    _failures: dict[tuple[str, str], deque[float]] = field(default_factory=dict)

    def _recent(self, key: tuple[str, str], now: float) -> deque[float]:
        hits = self._failures.setdefault(key, deque())
        while hits and hits[0] <= now - self.window_seconds:
            hits.popleft()
        return hits

    def retry_after(self, ip: str, email: str) -> int:
        """Seconds until another attempt is allowed, or 0 if allowed now."""
        now = time.monotonic()
        waits = [0.0]
        for key, limit in (
            (("acct", f"{ip}|{email.lower()}"), self.max_per_account),
            (("ip", ip), self.max_per_ip),
        ):
            hits = self._recent(key, now)
            if len(hits) >= limit:
                waits.append(hits[0] + self.window_seconds - now)
        return int(max(waits)) + (1 if max(waits) > 0 else 0)

    def record_failure(self, ip: str, email: str) -> None:
        now = time.monotonic()
        self._recent(("acct", f"{ip}|{email.lower()}"), now).append(now)
        self._recent(("ip", ip), now).append(now)

    def reset(self, ip: str, email: str) -> None:
        self._failures.pop(("acct", f"{ip}|{email.lower()}"), None)
