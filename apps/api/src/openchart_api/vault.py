# SPDX-License-Identifier: AGPL-3.0-or-later
"""Encrypted storage for API keys and other user secrets.

Envelope encryption: each secret gets its own random data key (DEK) that
encrypts the value with AES-256-GCM. The DEK is itself encrypted ("wrapped")
with the server's master key, which never touches the database. The value's
associated data binds the ciphertext to its owner and name, so rows cannot be
swapped between users or secrets.

Plaintext only ever leaves this module through :func:`reveal`, for server-side
use such as calling a data provider. API routes must never return it.
"""

import os
from dataclasses import dataclass
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from openchart_api.tables import vault_secrets

KEY_VERSION = 1
_NONCE_BYTES = 12
# Secrets shorter than this get no hint at all, so the hint never reveals
# most of a short value.
_HINT_MIN_LENGTH = 12


@dataclass(frozen=True)
class Sealed:
    ciphertext: bytes
    nonce: bytes
    wrapped_dek: bytes
    dek_nonce: bytes
    key_version: int


def _aad(user_id: UUID, name: str) -> bytes:
    return f"openchart:secret:v1:{user_id}:{name}".encode()


def _dek_aad(key_version: int) -> bytes:
    return f"openchart:dek:v{key_version}".encode()


def seal(master_key: bytes, user_id: UUID, name: str, value: str) -> Sealed:
    dek = AESGCM.generate_key(bit_length=256)
    nonce, dek_nonce = os.urandom(_NONCE_BYTES), os.urandom(_NONCE_BYTES)
    return Sealed(
        ciphertext=AESGCM(dek).encrypt(nonce, value.encode(), _aad(user_id, name)),
        nonce=nonce,
        wrapped_dek=AESGCM(master_key).encrypt(dek_nonce, dek, _dek_aad(KEY_VERSION)),
        dek_nonce=dek_nonce,
        key_version=KEY_VERSION,
    )


def unseal(master_key: bytes, user_id: UUID, name: str, sealed: Sealed) -> str:
    """Decrypt a secret. Raises ``cryptography.exceptions.InvalidTag`` if tampered."""
    dek = AESGCM(master_key).decrypt(
        sealed.dek_nonce, sealed.wrapped_dek, _dek_aad(sealed.key_version)
    )
    return AESGCM(dek).decrypt(sealed.nonce, sealed.ciphertext, _aad(user_id, name)).decode()


def hint(value: str) -> str:
    return f"…{value[-4:]}" if len(value) >= _HINT_MIN_LENGTH else ""


async def store(
    conn: AsyncConnection,
    master_key: bytes,
    user_id: UUID,
    name: str,
    value: str,
    provider: str | None,
) -> None:
    sealed = seal(master_key, user_id, name, value)
    values = {
        "ciphertext": sealed.ciphertext,
        "nonce": sealed.nonce,
        "wrapped_dek": sealed.wrapped_dek,
        "dek_nonce": sealed.dek_nonce,
        "key_version": sealed.key_version,
        "hint": hint(value),
        "provider": provider,
    }
    stmt = insert(vault_secrets).values(user_id=user_id, name=name, **values)
    await conn.execute(
        stmt.on_conflict_do_update(
            index_elements=[vault_secrets.c.user_id, vault_secrets.c.name],
            set_={**values, "updated_at": func.now()},
        )
    )


async def reveal(conn: AsyncConnection, master_key: bytes, user_id: UUID, name: str) -> str | None:
    """Server-side access to a secret's plaintext. Never return this to a client."""
    row = (
        await conn.execute(
            select(vault_secrets).where(
                vault_secrets.c.user_id == user_id, vault_secrets.c.name == name
            )
        )
    ).one_or_none()
    if row is None:
        return None
    sealed = Sealed(row.ciphertext, row.nonce, row.wrapped_dek, row.dek_nonce, row.key_version)
    return unseal(master_key, user_id, name, sealed)
