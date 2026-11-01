# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which providers are switched on, in what order, and with which keys.

Configuration lives in the ``data_sources`` table and is changed by owners
and admins. Provider keys are sealed with the vault's envelope encryption
under a fixed system identity, so they can only be opened with the master
key, which is never stored in the database.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidTag
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from openchart_api import vault
from openchart_api.market.models import InstrumentRef
from openchart_api.market.providers.base import MarketDataProvider
from openchart_api.market.providers.coinbase import Coinbase
from openchart_api.market.providers.kraken import Kraken
from openchart_api.market.providers.twelvedata import TwelveData
from openchart_api.market.providers.yahoo import Yahoo

log = logging.getLogger(__name__)

# Provider keys belong to the server, not to a user.
SYSTEM_USER = UUID(int=0)
PROVIDERS = ("coinbase", "kraken", "yahoo", "twelvedata")
LABELS = {
    "coinbase": "Coinbase",
    "kraken": "Kraken",
    "yahoo": "Yahoo Finance",
    "twelvedata": "Twelve Data",
}
NEEDS_TERMS = frozenset({"yahoo"})
NEEDS_KEY = frozenset({"twelvedata"})
# How long a provider is skipped for an instrument after repeated failures.
COOLDOWN_SECONDS = 300.0


def key_name(provider: str) -> str:
    return f"data.{provider}"


def seal_key(master_key: bytes, provider: str, value: str) -> vault.Sealed:
    return vault.seal(master_key, SYSTEM_USER, key_name(provider), value)


@dataclass(frozen=True)
class SourceConfig:
    provider: str
    priority: int
    tos_accepted: bool
    key: str | None


def config_from_row(row: Any, tos_accepted: bool, master_key: bytes) -> SourceConfig:
    """A source's settings with its key unsealed (if it has one that opens)."""
    key = None
    if row.key_ciphertext is not None:
        try:
            key = vault.unseal(
                master_key,
                SYSTEM_USER,
                key_name(row.provider),
                vault.Sealed(
                    row.key_ciphertext,
                    row.key_nonce,
                    row.key_wrapped_dek,
                    row.key_dek_nonce,
                    row.key_version,
                ),
            )
        except InvalidTag:
            log.error("The stored %s key cannot be decrypted; ignoring it", row.provider)
    return SourceConfig(row.provider, row.priority, tos_accepted, key)


async def load_config(engine: AsyncEngine, master_key: bytes) -> list[SourceConfig]:
    """Enabled sources in priority order, read without a user via a narrow function."""
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT * FROM market_data_sources()"))).all()
    return [config_from_row(r, r.tos_accepted, master_key) for r in rows]


def build(config: SourceConfig) -> MarketDataProvider | None:
    """A provider for a usable configuration, or None if it is not ready."""
    if config.provider in NEEDS_TERMS and not config.tos_accepted:
        return None
    if config.provider in NEEDS_KEY and not config.key:
        return None
    match config.provider:
        case "coinbase":
            return Coinbase()
        case "kraken":
            return Kraken()
        case "yahoo":
            return Yahoo()
        case "twelvedata":
            return TwelveData(config.key) if config.key else None
    return None


class Router:
    """Chooses providers for an instrument: by priority, skipping ones that
    recently failed for it (unless nothing else is left)."""

    def __init__(
        self,
        providers: list[MarketDataProvider],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.providers = providers
        self._clock = clock
        self._failed: dict[tuple[str, str], float] = {}

    def candidates(self, instrument: InstrumentRef) -> list[MarketDataProvider]:
        able = [p for p in self.providers if p.supports(instrument)]
        now = self._clock()
        healthy = [p for p in able if self._failed.get((p.name, instrument.id), 0.0) <= now]
        # Prefer healthy providers, but fall back to cooling ones rather than nothing.
        return healthy + [p for p in able if p not in healthy]

    def mark_failed(self, provider: MarketDataProvider, instrument: InstrumentRef) -> None:
        self._failed[(provider.name, instrument.id)] = self._clock() + COOLDOWN_SECONDS

    def mark_ok(self, provider: MarketDataProvider, instrument: InstrumentRef) -> None:
        self._failed.pop((provider.name, instrument.id), None)
