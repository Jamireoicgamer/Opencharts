# SPDX-License-Identifier: AGPL-3.0-or-later
"""The contract every market data adapter fulfils.

Adapters translate between canonical instrument ids (``LSE:BA.``) and the
provider's own symbols, and turn untrusted provider responses into
:class:`~openchart_api.market.models.Quote` and ``Candle`` values, refusing
anything malformed rather than guessing.
"""

import math
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar, Protocol

import httpx2

from openchart_api.market.models import Candle, InstrumentRef, Interval, Quote

USER_AGENT = "OpenChart/0.1 (self-hosted; +https://github.com/Jamireoicgamer/Opencharts)"
TIMEOUT = httpx2.Timeout(10.0, connect=5.0)
# Larger than any sane price; protects numeric(28,10) columns.
_MAX_AMOUNT = Decimal("1e17")


class ProviderError(Exception):
    """The provider failed or answered with something unusable."""


class MarketDataProvider(Protocol):
    name: ClassVar[str]
    label: ClassVar[str]
    streams: ClassVar[bool]

    def supports(self, instrument: InstrumentRef) -> bool: ...

    async def quote(self, instrument: InstrumentRef) -> Quote: ...

    async def history(
        self, instrument: InstrumentRef, interval: Interval, start: datetime, end: datetime
    ) -> list[Candle]: ...

    def stream(self, instruments: Sequence[InstrumentRef]) -> AsyncIterator[Quote]:
        """Live quotes for these instruments until cancelled. Only for ``streams``."""
        ...

    async def aclose(self) -> None: ...


def amount(value: Any, *, allow_zero: bool = False) -> Decimal:
    """A provider's number as a Decimal; refuses NaN, infinities, negatives and junk."""
    if isinstance(value, bool) or value is None:
        raise ProviderError(f"not a number: {value!r}")
    if isinstance(value, float) and not math.isfinite(value):
        raise ProviderError("not a finite number")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ProviderError(f"not a number: {str(value)[:20]!r}") from exc
    if not number.is_finite() or number < 0 or number >= _MAX_AMOUNT:
        raise ProviderError("number out of range")
    if number == 0 and not allow_zero:
        raise ProviderError("zero price")
    return number


def optional_amount(value: Any) -> Decimal | None:
    try:
        return amount(value)
    except ProviderError:
        return None


def from_unix(seconds: Any) -> datetime:
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise ProviderError("bad timestamp")
    if not 0 < seconds < 32503680000:  # before year 3000
        raise ProviderError("timestamp out of range")
    return datetime.fromtimestamp(seconds, UTC)


def from_iso(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ProviderError("bad timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderError("bad timestamp") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def candle(t: datetime, o: Any, h: Any, low: Any, c: Any, v: Any) -> Candle:
    return Candle(
        t=t,
        open=amount(o),
        high=amount(h),
        low=amount(low),
        close=amount(c),
        volume=None if v is None else amount(v, allow_zero=True),
    )


def new_client() -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=False
    )


async def get_json(client: httpx2.AsyncClient, url: str, params: dict[str, Any]) -> Any:
    """GET a JSON document, turning every failure into ProviderError."""
    try:
        response = await client.get(url, params=params)
    except httpx2.HTTPError as exc:
        raise ProviderError(f"request failed: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise ProviderError(f"HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError("response is not JSON") from exc
