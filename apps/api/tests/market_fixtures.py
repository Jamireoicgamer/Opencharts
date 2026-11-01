# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provider responses for adapter tests.

Coinbase, Kraken and Yahoo responses were recorded from the live services
by ``scripts/record_market_fixtures.py`` (see ``fixtures/market/RECORDED.txt``
for when) and trimmed to a few bars. Error responses, and Twelve Data
(which needs a key), are written by hand from the providers' documented
formats; they are marked below.
"""

import json
from pathlib import Path
from typing import Any

_DIR = Path(__file__).parent / "fixtures" / "market"


def _load(name: str) -> Any:
    return json.loads((_DIR / f"{name}.json").read_text())


# Recorded ---------------------------------------------------------------------

COINBASE_TICKER = _load("coinbase_ticker")
COINBASE_STATS = _load("coinbase_stats")
# [time, low, high, open, close, volume], newest first
COINBASE_CANDLES = _load("coinbase_candles_1d")
COINBASE_WS_MESSAGES = _load("coinbase_ws")
KRAKEN_TICKER = _load("kraken_ticker")
KRAKEN_OHLC = _load("kraken_ohlc_1d")
YAHOO_QUOTE_BA = _load("yahoo_quote_BA.L")
YAHOO_QUOTE_NVDA = _load("yahoo_quote_NVDA")
YAHOO_HISTORY_NVDA = _load("yahoo_history_NVDA")

# Hand-written -----------------------------------------------------------------

KRAKEN_ERROR = {"error": ["EQuery:Unknown asset pair"]}
YAHOO_NOT_FOUND = {
    "chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}
}
# A malformed tick, as a broken or hostile feed might send.
COINBASE_BAD_TICK = {"type": "ticker", "product_id": "BTC-USD", "price": "NaN", "time": "x"}

# Twelve Data needs a key, so these follow its documentation.
TWELVEDATA_QUOTE = {
    "symbol": "NVDA",
    "name": "NVIDIA Corp",
    "exchange": "NASDAQ",
    "currency": "USD",
    "datetime": "2026-10-31",
    "timestamp": 1793455200,
    "open": "204.00000",
    "high": "207.90000",
    "low": "203.10000",
    "close": "206.60000",
    "volume": "160500000",
    "previous_close": "204.20000",
    "change": "2.40000",
    "percent_change": "1.17532",
    "is_market_open": False,
}
TWELVEDATA_SERIES = {
    "meta": {"symbol": "NVDA", "interval": "1day", "currency": "USD", "exchange": "NASDAQ"},
    "values": [
        {
            "datetime": "2026-10-30",
            "open": "201.10",
            "high": "205.30",
            "low": "199.80",
            "close": "204.20",
            "volume": "181000000",
        },
        {
            "datetime": "2026-10-31",
            "open": "204.00",
            "high": "207.90",
            "low": "203.10",
            "close": "206.60",
            "volume": "160500000",
        },
    ],
    "status": "ok",
}
TWELVEDATA_ERROR = {"code": 401, "message": "**apikey** parameter is incorrect", "status": "error"}
