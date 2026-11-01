# SPDX-License-Identifier: AGPL-3.0-or-later
"""Prices as the rest of the app sees them, whatever the source.

Amounts are ``Decimal`` and serialise as strings, like the rest of the API.
Every quote says where it came from, when it was priced and how delayed it
is, so the interface can always label it honestly.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

Delay = Literal["realtime", "delayed", "eod"]
Interval = Literal["5m", "1h", "1d"]
MarketState = Literal["open", "closed", "unknown"]

INTERVAL_SECONDS: dict[Interval, int] = {"5m": 300, "1h": 3600, "1d": 86400}


@dataclass(frozen=True)
class InstrumentRef:
    """What an adapter needs to know about an instrument to fetch it."""

    id: str
    symbol: str
    exchange: str
    currency: str
    asset_class: str


@dataclass(frozen=True)
class Quote:
    instrument_id: str
    price: Decimal
    # Change since the previous close (or 24 hours ago for crypto), if known.
    previous_close: Decimal | None
    currency: str
    at: datetime
    source: str
    delay: Delay
    # Minutes behind the market when the source says so; None when unknown.
    delay_minutes: int | None = None
    market_state: MarketState = "unknown"

    @property
    def change(self) -> Decimal | None:
        return None if self.previous_close is None else self.price - self.previous_close

    @property
    def change_pct(self) -> Decimal | None:
        if not self.previous_close:
            return None
        return (self.price - self.previous_close) / self.previous_close * 100


@dataclass(frozen=True)
class Candle:
    t: datetime  # start of the bar, UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
