# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provider responses for adapter tests.

These were written by hand from each provider's documented response format
because this development environment cannot reach the providers. Values are
illustrative, not real prices. Replace them with recorded responses when
network access allows.
"""

COINBASE_TICKER = {
    "trade_id": 86326522,
    "price": "67843.21",
    "size": "0.00042",
    "time": "2026-10-31T14:03:22.418Z",
    "bid": "67843.20",
    "ask": "67843.21",
    "volume": "10234.5",
}
COINBASE_STATS = {"open": "68640.00", "high": "69010.00", "low": "67120.00", "last": "67843.21"}
# [time, low, high, open, close, volume], newest first
COINBASE_CANDLES_PAGE_1 = [
    [1793404800, "67000.1", "68900.5", "68100.0", "68640.0", "812.4"],
    [1793318400, "66500.0", "68300.0", "66900.0", "68100.0", "905.2"],
]
COINBASE_CANDLES_PAGE_2 = [
    [1793491200, "67100.0", "69010.0", "68640.0", "67843.2", "640.9"],
]
COINBASE_WS_MESSAGES = [
    {"type": "subscriptions", "channels": [{"name": "ticker", "product_ids": ["BTC-USD"]}]},
    {
        "type": "ticker",
        "sequence": 1,
        "product_id": "BTC-USD",
        "price": "67850.00",
        "open_24h": "68640.00",
        "time": "2026-10-31T14:03:23.001Z",
    },
    {"type": "ticker", "product_id": "BTC-USD", "price": "NaN", "time": "2026-10-31T14:03:24Z"},
    {
        "type": "ticker",
        "product_id": "BTC-USD",
        "price": "67851.50",
        "open_24h": "68640.00",
        "time": "2026-10-31T14:03:25.000Z",
    },
]

KRAKEN_TICKER = {
    "error": [],
    "result": {
        "XXBTZUSD": {
            "a": ["67843.30000", "1", "1.000"],
            "b": ["67843.20000", "2", "2.000"],
            "c": ["67843.20000", "0.00100000"],
            "o": "68640.00000",
        }
    },
}
KRAKEN_OHLC = {
    "error": [],
    "result": {
        "XXBTZUSD": [
            [1793318400, "66900.0", "68300.0", "66500.0", "68100.0", "67400.0", "905.2", 41023],
            [1793404800, "68100.0", "68900.5", "67000.1", "68640.0", "68010.0", "812.4", 38110],
        ],
        "last": 1793404800,
    },
}
KRAKEN_ERROR = {"error": ["EQuery:Unknown asset pair"]}

# /v8/finance/chart/BA.L?range=1d&interval=1d
YAHOO_QUOTE_BA = {
    "chart": {
        "result": [
            {
                "meta": {
                    "currency": "GBp",
                    "symbol": "BA.L",
                    "exchangeName": "LSE",
                    "regularMarketPrice": 1986.5,
                    "regularMarketTime": 1793455200,
                    "previousClose": 1962.5,
                    "chartPreviousClose": 1962.5,
                    "gmtoffset": 0,
                    "currentTradingPeriod": {
                        "regular": {"start": 1793433600, "end": 1793464200, "gmtoffset": 0}
                    },
                },
                "timestamp": [1793433600],
                "indicators": {
                    "quote": [
                        {
                            "open": [1965.0],
                            "high": [1990.0],
                            "low": [1958.5],
                            "close": [1986.5],
                            "volume": [3104222],
                        }
                    ]
                },
            }
        ],
        "error": None,
    }
}
# /v8/finance/chart/NVDA?period1=..&interval=1d ; gmtoffset is New York (-4h)
YAHOO_HISTORY_NVDA = {
    "chart": {
        "result": [
            {
                "meta": {"currency": "USD", "symbol": "NVDA", "gmtoffset": -14400},
                "timestamp": [1793280600, 1793367000, 1793453400],
                "indicators": {
                    "quote": [
                        {
                            "open": [201.1, None, 204.0],
                            "high": [205.3, None, 207.9],
                            "low": [199.8, None, 203.1],
                            "close": [204.2, None, 206.6],
                            "volume": [181000000, None, 160500000],
                        }
                    ]
                },
            }
        ],
        "error": None,
    }
}
YAHOO_NOT_FOUND = {
    "chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}
}

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
