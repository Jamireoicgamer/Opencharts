# SPDX-License-Identifier: AGPL-3.0-or-later
"""Record real provider responses for the adapter tests (developer tool).

    uv run python apps/api/scripts/record_market_fixtures.py

Fetches public, keyless endpoints with the same User-Agent the app uses,
trims long arrays so the files stay small, and writes them to
``tests/fixtures/market``. The tests then check the adapters against what
the providers really send. Twelve Data needs a key and is not recorded.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
from websockets.asyncio.client import connect

from openchart_api.market.providers.base import USER_AGENT

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "market"
KEEP = 3  # bars per series


async def get(client: httpx2.AsyncClient, url: str, **params: Any) -> Any:
    response = await client.get(url, params=params)
    response.raise_for_status()
    return response.json()


def trim_yahoo(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload["chart"]["result"][0]
    result.pop("events", None)
    result["meta"].pop("validRanges", None)
    result["meta"].pop("tradingPeriods", None)
    if "timestamp" in result:
        result["timestamp"] = result["timestamp"][-KEEP:]
        quote = result["indicators"]["quote"][0]
        for key in quote:
            quote[key] = quote[key][-KEEP:]
        result["indicators"].pop("adjclose", None)
    return payload


async def record() -> dict[str, Any]:
    async with httpx2.AsyncClient(timeout=15, headers={"User-Agent": USER_AGENT}) as client:
        coinbase = "https://api.exchange.coinbase.com/products/BTC-USD"
        kraken = "https://api.kraken.com/0/public"
        yahoo = "https://query1.finance.yahoo.com/v8/finance/chart"
        ohlc = await get(client, f"{kraken}/OHLC", pair="XBTUSD", interval=1440)
        pair = next(k for k in ohlc["result"] if k != "last")
        ohlc["result"][pair] = ohlc["result"][pair][-KEEP:]
        files = {
            "coinbase_ticker": await get(client, f"{coinbase}/ticker"),
            "coinbase_stats": await get(client, f"{coinbase}/stats"),
            "coinbase_candles_1d": (await get(client, f"{coinbase}/candles", granularity=86400))[
                :KEEP
            ],
            "kraken_ticker": await get(client, f"{kraken}/Ticker", pair="XBTUSD"),
            "kraken_ohlc_1d": ohlc,
            "yahoo_quote_BA.L": trim_yahoo(
                await get(client, f"{yahoo}/BA.L", range="5d", interval="1d")
            ),
            "yahoo_quote_NVDA": trim_yahoo(
                await get(client, f"{yahoo}/NVDA", range="5d", interval="1d")
            ),
            "yahoo_history_NVDA": trim_yahoo(
                await get(client, f"{yahoo}/NVDA", range="1mo", interval="1d")
            ),
        }
    messages: list[Any] = []
    async with connect("wss://ws-feed.exchange.coinbase.com") as ws:
        await ws.send(
            json.dumps({"type": "subscribe", "product_ids": ["BTC-USD"], "channels": ["ticker"]})
        )
        async for raw in ws:
            messages.append(json.loads(raw))
            if sum(m.get("type") == "ticker" for m in messages) >= 2:
                break
    files["coinbase_ws"] = messages
    return files


def main() -> None:
    files = asyncio.run(record())
    OUT.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        (OUT / f"{name}.json").write_text(json.dumps(payload, indent=1) + "\n")
    (OUT / "RECORDED.txt").write_text(
        f"Recorded {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by scripts/record_market_fixtures.py\n"
    )
    print(f"Wrote {len(files)} files to {OUT}")


if __name__ == "__main__":
    main()
