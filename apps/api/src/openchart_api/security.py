# SPDX-License-Identifier: AGPL-3.0-or-later
"""Password hashing, opaque tokens and rate limiting of failed attempts."""

import hashlib
import secrets
import time
from collections import deque
from dataclasses import dataclass, field

from anyio import CapacityLimiter, to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 256

# argon2id with the library's RFC 9106 "low memory" profile (64 MiB, t=3).
_hasher = PasswordHasher()
# Verified against when the email is unknown, so response time does not reveal
# which accounts exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))
# Each hash needs 64 MiB, so cap how many run at once: unauthenticated
# requests must not be able to exhaust memory on a small server.
HASH_CONCURRENCY = 2
_hash_slots: CapacityLimiter | None = None


def _slots() -> CapacityLimiter:
    # Created lazily: anyio limiters must be made inside a running event loop.
    global _hash_slots
    if _hash_slots is None:
        _hash_slots = CapacityLimiter(HASH_CONCURRENCY)
    return _hash_slots


async def hash_password(password: str) -> str:
    return await to_thread.run_sync(_hasher.hash, password, limiter=_slots())


async def verify_password(password_hash: str | None, password: str) -> bool:
    def verify() -> bool:
        try:
            return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
        except (VerificationError, InvalidHashError):
            return False

    return await to_thread.run_sync(verify, limiter=_slots())


def new_token() -> str:
    """A 256-bit random token for cookies and invite links."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    """Tokens are stored only as SHA-256 hashes."""
    return hashlib.sha256(token.encode()).digest()


@dataclass
class FailureLimiter:
    """Counts failed attempts per (IP, subject) and per IP in a sliding window.

    The subject is what was attempted: an email address for sign-in, or a
    fixed name such as ``"setup"``. State lives in this process only, which
    suits the single API process of a self-hosted install; a shared store
    (Redis) replaces it when the API scales out. Memory stays bounded: expired
    entries are dropped and at most ``max_keys`` keys are tracked.
    """

    max_per_subject: int = 5
    max_per_ip: int = 30
    window_seconds: float = 15 * 60
    max_keys: int = 10_000
    _failures: dict[str, deque[float]] = field(default_factory=dict)

    @staticmethod
    def _keys(ip: str, subject: str) -> tuple[str, str]:
        return f"s|{ip}|{subject.lower()}", f"ip|{ip}"

    def _recent(self, key: str, now: float) -> deque[float]:
        hits = self._failures.get(key)
        if hits is None:
            return deque()
        while hits and hits[0] <= now - self.window_seconds:
            hits.popleft()
        if not hits:
            del self._failures[key]
        return hits

    def retry_after(self, ip: str, subject: str) -> int:
        """Seconds until another attempt is allowed, or 0 if allowed now."""
        now = time.monotonic()
        subject_key, ip_key = self._keys(ip, subject)
        wait = 0.0
        for key, limit in ((subject_key, self.max_per_subject), (ip_key, self.max_per_ip)):
            hits = self._recent(key, now)
            if len(hits) >= limit:
                wait = max(wait, hits[0] + self.window_seconds - now)
        return int(wait) + 1 if wait > 0 else 0

    def record_failure(self, ip: str, subject: str) -> None:
        now = time.monotonic()
        for key in self._keys(ip, subject):
            self._failures.setdefault(key, deque()).append(now)
        if len(self._failures) > self.max_keys:
            self._evict(now)

    def reset(self, ip: str, subject: str) -> None:
        self._failures.pop(self._keys(ip, subject)[0], None)

    def _evict(self, now: float) -> None:
        for key in list(self._failures):
            self._recent(key, now)
        overflow = len(self._failures) - self.max_keys
        if overflow > 0:
            # Forget the keys whose latest failure is oldest.
            oldest = sorted(self._failures, key=lambda k: self._failures[k][-1])[:overflow]
            for key in oldest:
                del self._failures[key]
