# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provider adapters: symbol mapping, parsing, currency and refusing junk.

No network: REST goes through httpx2.MockTransport and WebSockets through a
fake connection. See ``market_fixtures`` for where the responses come from.
"""

import json
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx2
import pytest

from openchart_api.market.models import InstrumentRef
from openchart_api.market.providers.base import ProviderError, amount
from openchart_api.market.providers.coinbase import Coinbase
from openchart_api.market.providers.kraken import Kraken
from openchart_api.market.providers.twelvedata import RateLimiter, TwelveData
from openchart_api.market.providers.yahoo import Yahoo

from . import market_fixtures as fx

pytestmark = pytest.mark.anyio

BTC = InstrumentRef("CRYPTO:BTC-USD", "BTC-USD", "CRYPTO", "USD", "crypto")
DOGE = InstrumentRef("CRYPTO:DOGE-USD", "DOGE-USD", "CRYPTO", "USD", "crypto")
BAE = InstrumentRef("LSE:BA.", "BA.", "LSE", "GBX", "equity")
BT = InstrumentRef("LSE:BT.A", "BT.A", "LSE", "GBX", "equity")
VUSA = InstrumentRef("LSE:VUSA", "VUSA", "LSE", "GBP", "etf")
NVDA = InstrumentRef("NASDAQ:NVDA", "NVDA", "NASDAQ", "USD", "equity")
BRK = InstrumentRef("NYSE:BRK.B", "BRK.B", "NYSE", "USD", "equity")
FTSE = InstrumentRef("INDEX:UKX", "UKX", "INDEX", "GBP", "index")
CABLE = InstrumentRef("FX:GBP-USD", "GBP/USD", "FX", "USD", "fx")

Seen = list[httpx2.Request]


def client_for(routes: Callable[[httpx2.Request], Any]) -> tuple[httpx2.AsyncClient, Seen]:
    seen: Seen = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        answer = routes(request)
        if isinstance(answer, httpx2.Response):
            return answer
        return httpx2.Response(200, json=answer)

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handle)), seen


def test_amounts_refuse_junk() -> None:
    assert amount("67843.21") == Decimal("67843.21")
    assert amount(1986.5) == Decimal("1986.5")
    for bad in ("NaN", "Infinity", "-1", "1e20", True, None, "abc", float("nan"), 0):
        with pytest.raises(ProviderError):
            amount(bad)
    assert amount(0, allow_zero=True) == 0


# Coinbase -------------------------------------------------------------------


async def test_coinbase_quote() -> None:
    def routes(r: httpx2.Request) -> Any:
        return fx.COINBASE_STATS if r.url.path.endswith("/stats") else fx.COINBASE_TICKER

    client, seen = client_for(routes)
    quote = await Coinbase(client).quote(BTC)
    assert [r.url.path for r in seen] == ["/products/BTC-USD/ticker", "/products/BTC-USD/stats"]
    assert quote.price == Decimal("67843.21")
    assert quote.previous_close == Decimal("68640.00")
    assert quote.change_pct is not None and round(quote.change_pct, 2) == Decimal("-1.16")
    assert (quote.source, quote.delay, quote.currency) == ("coinbase", "realtime", "USD")
    assert quote.at == datetime(2026, 10, 31, 14, 3, 22, 418000, tzinfo=UTC)


async def test_coinbase_history_pages_and_sorts() -> None:
    pages = iter([fx.COINBASE_CANDLES_PAGE_1, fx.COINBASE_CANDLES_PAGE_2])
    client, seen = client_for(lambda r: next(pages))
    start = datetime(2026, 10, 30, tzinfo=UTC)
    end = start + timedelta(days=300 + 2)  # more than 300 daily bars: two requests
    bars = await Coinbase(client).history(BTC, "1d", start, end)
    assert len(seen) == 2
    assert seen[0].url.params["granularity"] == "86400"
    assert [b.t.day for b in bars] == [30, 31, 1]
    first = bars[0]
    assert (first.open, first.high, first.low, first.close) == (
        Decimal("66900.0"),
        Decimal("68300.0"),
        Decimal("66500.0"),
        Decimal("68100.0"),
    )


class FakeSocket:
    def __init__(self, messages: Sequence[object]) -> None:
        self.sent: list[dict[str, Any]] = []
        self._messages = [json.dumps(m) for m in messages]

    async def __aenter__(self) -> "FakeSocket":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def send(self, text: str) -> None:
        self.sent.append(json.loads(text))

    def __aiter__(self) -> AsyncIterator[str]:
        async def gen() -> AsyncIterator[str]:
            for m in self._messages:
                yield m

        return gen()


async def test_coinbase_stream_skips_bad_ticks() -> None:
    socket = FakeSocket(fx.COINBASE_WS_MESSAGES)
    client, _ = client_for(lambda r: {})
    provider = Coinbase(client, connector=lambda url: socket)
    quotes = [q async for q in provider.stream([BTC])]
    assert socket.sent == [
        {"type": "subscribe", "product_ids": ["BTC-USD"], "channels": ["ticker"]}
    ]
    # The NaN tick is dropped; the stream carries on.
    assert [q.price for q in quotes] == [Decimal("67850.00"), Decimal("67851.50")]


async def test_coinbase_stream_error_raises() -> None:
    socket = FakeSocket([{"type": "error", "message": "Failed to subscribe"}])
    client, _ = client_for(lambda r: {})
    with pytest.raises(ProviderError, match="Failed to subscribe"):
        [q async for q in Coinbase(client, connector=lambda url: socket).stream([BTC])]


async def test_coinbase_covers_crypto_only() -> None:
    provider = Coinbase(client_for(lambda r: {})[0])
    assert provider.supports(BTC)
    assert not provider.supports(BAE)


# Kraken ---------------------------------------------------------------------


async def test_kraken_pairs_and_quote() -> None:
    assert Kraken.pair(BTC) == "XBTUSD"
    assert Kraken.pair(DOGE) == "XDGUSD"
    client, seen = client_for(lambda r: fx.KRAKEN_TICKER)
    quote = await Kraken(client).quote(BTC)
    assert seen[0].url.params["pair"] == "XBTUSD"
    assert quote.price == Decimal("67843.20000")
    assert quote.previous_close == Decimal("68640.00000")


async def test_kraken_history_and_errors() -> None:
    client, _ = client_for(lambda r: fx.KRAKEN_OHLC)
    start = datetime(2026, 10, 29, tzinfo=UTC)
    bars = await Kraken(client).history(BTC, "1d", start, start + timedelta(days=5))
    assert [b.close for b in bars] == [Decimal("68100.0"), Decimal("68640.0")]
    assert bars[0].volume == Decimal("905.2")

    client, _ = client_for(lambda r: fx.KRAKEN_ERROR)
    with pytest.raises(ProviderError, match="Unknown asset pair"):
        await Kraken(client).quote(BTC)


# Yahoo ----------------------------------------------------------------------


def test_yahoo_symbols() -> None:
    assert Yahoo.symbol(BAE) == "BA.L"
    assert Yahoo.symbol(BT) == "BT-A.L"
    assert Yahoo.symbol(BRK) == "BRK-B"
    assert Yahoo.symbol(FTSE) == "^FTSE"
    assert Yahoo.symbol(CABLE) == "GBPUSD=X"
    assert Yahoo.symbol(BTC) == "BTC-USD"


async def test_yahoo_quote_in_pence_is_labelled_delayed() -> None:
    client, seen = client_for(lambda r: fx.YAHOO_QUOTE_BA)
    quote = await Yahoo(client).quote(BAE)
    assert seen[0].url.path == "/v8/finance/chart/BA.L"
    assert (quote.price, quote.currency) == (Decimal("1986.5"), "GBX")
    assert quote.previous_close == Decimal("1962.5")
    assert (quote.source, quote.delay, quote.delay_minutes) == ("yahoo", "delayed", None)
    assert quote.at == datetime.fromtimestamp(1793455200, UTC)


async def test_yahoo_converts_pounds_and_pence_but_refuses_other_currencies() -> None:
    in_pounds = json.loads(json.dumps(fx.YAHOO_QUOTE_BA))
    in_pounds["chart"]["result"][0]["meta"].update(currency="GBP", regularMarketPrice=19.865)
    client, _ = client_for(lambda r: in_pounds)
    assert (await Yahoo(client).quote(BAE)).price == Decimal("1986.500")

    # A GBP-quoted ETF reported in pence becomes pounds.
    client, _ = client_for(lambda r: fx.YAHOO_QUOTE_BA)
    assert (await Yahoo(client).quote(VUSA)).price == Decimal("19.865")

    in_euros = json.loads(json.dumps(fx.YAHOO_QUOTE_BA))
    in_euros["chart"]["result"][0]["meta"]["currency"] = "EUR"
    client, _ = client_for(lambda r: in_euros)
    with pytest.raises(ProviderError, match="currency mismatch"):
        await Yahoo(client).quote(BAE)


async def test_yahoo_history_skips_gaps_and_keys_days_by_exchange_date() -> None:
    client, seen = client_for(lambda r: fx.YAHOO_HISTORY_NVDA)
    end = datetime(2026, 11, 1, tzinfo=UTC)
    bars = await Yahoo(client).history(NVDA, "1d", end - timedelta(days=5), end)
    assert seen[0].url.params["interval"] == "1d"
    assert [b.t for b in bars] == [
        datetime(2026, 10, 29, tzinfo=UTC),
        datetime(2026, 10, 31, tzinfo=UTC),
    ]
    assert bars[1].close == Decimal("206.6")


async def test_yahoo_not_found_and_garbage() -> None:
    client, _ = client_for(lambda r: fx.YAHOO_NOT_FOUND)
    with pytest.raises(ProviderError, match="Yahoo error"):
        await Yahoo(client).quote(NVDA)
    client, _ = client_for(lambda r: httpx2.Response(200, text="<html>"))
    with pytest.raises(ProviderError, match="not JSON"):
        await Yahoo(client).quote(NVDA)
    client, _ = client_for(lambda r: httpx2.Response(429))
    with pytest.raises(ProviderError, match="429"):
        await Yahoo(client).quote(NVDA)


# Twelve Data ----------------------------------------------------------------


async def test_twelvedata_quote_and_coverage() -> None:
    client, seen = client_for(lambda r: fx.TWELVEDATA_QUOTE)
    provider = TwelveData("secret-key-123", client)
    quote = await provider.quote(NVDA)
    assert seen[0].url.params["symbol"] == "NVDA"
    assert quote.price == Decimal("206.60000")
    assert quote.market_state == "closed"
    assert provider.supports(CABLE)
    assert TwelveData.symbol(BTC) == "BTC/USD"
    assert not provider.supports(BAE)  # LSE needs a paid plan; left to other sources


async def test_twelvedata_errors_never_echo_the_key() -> None:
    client, _ = client_for(lambda r: fx.TWELVEDATA_ERROR)
    with pytest.raises(ProviderError) as caught:
        await TwelveData("secret-key-123", client).quote(NVDA)
    assert "secret-key-123" not in str(caught.value)
    assert "apikey" not in str(caught.value)


async def test_twelvedata_history() -> None:
    client, _ = client_for(lambda r: fx.TWELVEDATA_SERIES)
    end = datetime(2026, 11, 1, tzinfo=UTC)
    bars = await TwelveData("k" * 12, client).history(NVDA, "1d", end - timedelta(days=5), end)
    assert [b.t.day for b in bars] == [30, 31]


async def test_rate_limiter_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        limiter._calls.popleft()  # time passes: the oldest call expires

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    limiter = RateLimiter(2, period=60)
    await limiter.wait()
    await limiter.wait()
    assert slept == []
    await limiter.wait()
    assert len(slept) == 1 and 0 < slept[0] <= 60
