# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Python reference against textbook values, and the fixtures being current."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate
import indicators as ref

# J. Welles Wilder's RSI worked example as published by StockCharts
# (ChartSchool, "Relative Strength Index (RSI)"): its closes, and the 14-day
# RSI it lists from the 15th close on.
WILDER = [44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245,
          45.8433, 46.0826, 45.8931, 46.0328, 45.6140, 46.2820, 46.2820, 46.0028,
          46.0328, 46.4116, 46.2222, 45.6439]  # fmt: skip
PUBLISHED = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97]


def test_rsi_matches_wilders_example() -> None:
    values = ref.rsi(WILDER, 14)
    assert values[:14] == [None] * 14
    assert values[14:] == pytest.approx(PUBLISHED, abs=0.005)


def test_moving_averages_by_hand() -> None:
    data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert ref.sma(data, 3) == [None, None, 2.0, 3.0, 4.0, 5.0]
    # Seeded with the SMA (2), then k = 2/(3+1) = 0.5.
    assert ref.ema(data, 3) == [None, None, 2.0, 3.0, 4.0, 5.0]
    assert ref.ema([2.0, 4.0, 6.0, 0.0], 3) == [None, None, 4.0, 2.0]


def test_bollinger_and_vwap_by_hand() -> None:
    upper, middle, lower = ref.bollinger([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0], 8, 2)
    assert (middle[-1], upper[-1], lower[-1]) == (5.0, 9.0, 1.0)  # population sd = 2
    day = 86400
    bars = [
        {"t": 0, "high": 3, "low": 1, "close": 2, "volume": 1},
        {"t": 60, "high": 6, "low": 2, "close": 4, "volume": 3},
        {"t": day, "high": 9, "low": 9, "close": 9, "volume": 2},  # a new UTC day
        {"t": day + 60, "high": 1, "low": 1, "close": 1, "volume": None},
    ]
    assert ref.vwap(bars) == [2.0, 3.5, 9.0, None]


def test_fixtures_are_current() -> None:
    for name in ("btc_1d", "btc_5m"):
        bars = json.loads((generate.FIXTURES / f"{name}.json").read_text())["bars"]
        stored = json.loads((generate.FIXTURES / f"{name}.expected.json").read_text())
        assert stored == json.loads(json.dumps(generate.expected(bars))), name
