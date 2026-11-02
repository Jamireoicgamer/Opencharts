# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write the expected indicator values for the recorded bars in fixtures/.

    python packages/indicators/reference/generate.py

The TypeScript tests compare packages/indicators against these files.
"""

import json
from pathlib import Path

import indicators as ref

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def expected(bars: list[dict[str, float]]) -> dict[str, object]:
    closes = [b["close"] for b in bars]
    line, signal, hist = ref.macd(closes)
    upper, middle, lower = ref.bollinger(closes)
    return {
        "sma20": ref.sma(closes, 20),
        "ema20": ref.ema(closes, 20),
        "ema50": ref.ema(closes, 50),
        "rsi14": ref.rsi(closes, 14),
        "macd": {"macd": line, "signal": signal, "histogram": hist},
        "bollinger": {"upper": upper, "middle": middle, "lower": lower},
        "vwap": ref.vwap(bars),
    }


def main() -> None:
    for name in ("btc_1d", "btc_5m"):
        bars = json.loads((FIXTURES / f"{name}.json").read_text())["bars"]
        out = FIXTURES / f"{name}.expected.json"
        out.write_text(json.dumps(expected(bars)) + "\n")
        print(f"wrote {out.name}")


if __name__ == "__main__":
    main()
