# SPDX-License-Identifier: AGPL-3.0-or-later
"""Authenticator-app codes (TOTP), recovery codes, and a user's sign-in methods.

All functions expect the RLS context to be set to the user concerned.
"""

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from uuid import UUID

import pyotp
import segno
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from openchart_api import vault
from openchart_api.tables import mfa_recovery_codes, mfa_totp

ISSUER = "OpenChart AI"
TOTP_PERIOD = 30
RECOVERY_CODE_COUNT = 10
# No 0/o, 1/l/i: easy to read back from paper.
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_TOTP_SECRET_NAME = "mfa:totp"  # noqa: S105 (a vault entry name, not a secret)
# Replaceable in tests, which need codes that do not change mid-test.
clock = time.time


@dataclass(frozen=True)
class Methods:
    """How a user can sign in. Owner of the RLS context only."""

    has_password: bool
    totp: bool
    passkeys: int
    google: bool
    recovery_codes_left: int

    @property
    def has_second_factor(self) -> bool:
        return self.totp or self.passkeys > 0

    @property
    def sign_in_methods(self) -> int:
        return int(self.has_password) + self.passkeys + int(self.google)


async def methods(conn: AsyncConnection, user_id: UUID) -> Methods:
    row = (
        await conn.execute(
            text(
                "SELECT"
                " auth_has_password() AS has_password,"
                " EXISTS (SELECT 1 FROM mfa_totp WHERE user_id = :u AND confirmed_at IS NOT NULL)"
                "   AS totp,"
                " (SELECT count(*) FROM webauthn_credentials WHERE user_id = :u) AS passkeys,"
                " EXISTS (SELECT 1 FROM oauth_identities WHERE user_id = :u) AS google,"
                " (SELECT count(*) FROM mfa_recovery_codes WHERE user_id = :u AND used_at IS NULL)"
                "   AS recovery_codes_left"
            ),
            {"u": user_id},
        )
    ).one()
    return Methods(**row._mapping)


# TOTP --------------------------------------------------------------------------


def _normalise_code(code: str) -> str:
    return "".join(ch for ch in code if ch.isdigit())


def _matching_step(secret: str, code: str, after_step: int, now: float) -> int | None:
    """The time step (±1 for clock drift) whose code matches and has not been used."""
    code = _normalise_code(code)
    if len(code) != 6:
        return None
    totp = pyotp.TOTP(secret, interval=TOTP_PERIOD)
    current = int(now // TOTP_PERIOD)
    for step in (current - 1, current, current + 1):
        if step > after_step and hmac.compare_digest(totp.at(step * TOTP_PERIOD), code):
            return step
    return None


@dataclass(frozen=True)
class TotpEnrolment:
    secret: str
    uri: str
    qr_svg: str  # data: URI


async def begin_totp(
    conn: AsyncConnection, master_key: bytes, user_id: UUID, email: str
) -> TotpEnrolment:
    """Create (or replace) an unconfirmed secret for the user to scan."""
    secret = pyotp.random_base32()
    sealed = vault.seal(master_key, user_id, _TOTP_SECRET_NAME, secret)
    values = {
        "ciphertext": sealed.ciphertext,
        "nonce": sealed.nonce,
        "wrapped_dek": sealed.wrapped_dek,
        "dek_nonce": sealed.dek_nonce,
        "key_version": sealed.key_version,
        "confirmed_at": None,
        "last_used_step": 0,
    }
    await conn.execute(
        pg_insert(mfa_totp)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(index_elements=[mfa_totp.c.user_id], set_=values)
    )
    uri = pyotp.TOTP(secret, interval=TOTP_PERIOD).provisioning_uri(name=email, issuer_name=ISSUER)
    qr = segno.make(uri, error="m").svg_data_uri(scale=5, dark="#000", light="#fff")
    return TotpEnrolment(secret=secret, uri=uri, qr_svg=qr)


async def _secret(
    conn: AsyncConnection, master_key: bytes, user_id: UUID
) -> tuple[str, int, bool] | None:
    row = (await conn.execute(select(mfa_totp).where(mfa_totp.c.user_id == user_id))).one_or_none()
    if row is None:
        return None
    sealed = vault.Sealed(
        row.ciphertext, row.nonce, row.wrapped_dek, row.dek_nonce, row.key_version
    )
    secret = vault.unseal(master_key, user_id, _TOTP_SECRET_NAME, sealed)
    return secret, row.last_used_step, row.confirmed_at is not None


async def verify_totp(
    conn: AsyncConnection,
    master_key: bytes,
    user_id: UUID,
    code: str,
    *,
    confirming: bool = False,
    now: float | None = None,
) -> bool:
    """Check a code and mark its time step used, so it cannot be replayed.

    With ``confirming`` the secret must still be unconfirmed (enrolment);
    otherwise it must be confirmed (sign-in).
    """
    found = await _secret(conn, master_key, user_id)
    if found is None:
        return False
    secret, last_step, confirmed = found
    if confirmed == confirming:
        return False
    step = _matching_step(secret, code, last_step, clock() if now is None else now)
    if step is None:
        return False
    # The WHERE clause makes concurrent use of the same code fail too.
    updated = await conn.execute(
        update(mfa_totp)
        .where(mfa_totp.c.user_id == user_id, mfa_totp.c.last_used_step < step)
        .values(
            last_used_step=step,
            confirmed_at=func.coalesce(mfa_totp.c.confirmed_at, func.now()),
        )
    )
    return updated.rowcount == 1


async def remove_totp(conn: AsyncConnection, user_id: UUID) -> bool:
    result = await conn.execute(delete(mfa_totp).where(mfa_totp.c.user_id == user_id))
    return result.rowcount > 0


# Recovery codes ------------------------------------------------------------------


def _recovery_key(master_key: bytes) -> bytes:
    return hmac.new(master_key, b"openchart:recovery-codes:v1", hashlib.sha256).digest()


def _hash_recovery_code(master_key: bytes, code: str) -> bytes:
    normalised = "".join(ch for ch in code.lower() if ch in _RECOVERY_ALPHABET)
    return hmac.new(_recovery_key(master_key), normalised.encode(), hashlib.sha256).digest()


def _new_recovery_code() -> str:
    chars = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
    return f"{chars[:5]}-{chars[5:]}"


async def replace_recovery_codes(
    conn: AsyncConnection, master_key: bytes, user_id: UUID
) -> list[str]:
    """Issue a fresh set of codes; any previous codes stop working."""
    codes = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    await conn.execute(delete(mfa_recovery_codes).where(mfa_recovery_codes.c.user_id == user_id))
    await conn.execute(
        insert(mfa_recovery_codes),
        [{"user_id": user_id, "code_hash": _hash_recovery_code(master_key, c)} for c in codes],
    )
    return codes


async def use_recovery_code(
    conn: AsyncConnection, master_key: bytes, user_id: UUID, code: str
) -> bool:
    result = await conn.execute(
        update(mfa_recovery_codes)
        .where(
            mfa_recovery_codes.c.user_id == user_id,
            mfa_recovery_codes.c.code_hash == _hash_recovery_code(master_key, code),
            mfa_recovery_codes.c.used_at.is_(None),
        )
        .values(used_at=func.now())
    )
    return result.rowcount == 1


async def remove_recovery_codes(conn: AsyncConnection, user_id: UUID) -> None:
    await conn.execute(delete(mfa_recovery_codes).where(mfa_recovery_codes.c.user_id == user_id))
