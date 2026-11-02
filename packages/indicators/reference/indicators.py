# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reference implementations of OpenChart's indicators (standard library only).

They follow the same definitions as ``packages/indicators/src/index.ts``,
written independently, so the two can be checked against each other.
Values are ``None`` until an indicator has enough history.
"""

from collections.abc import Sequence
from math import floor, sqrt

Series = list[float | None]


def sma(values: Sequence[float], n: int) -> Series:
    out: Series = []
    for i in range(len(values)):
        out.append(sum(values[i - n + 1 : i + 1]) / n if i >= n - 1 else None)
    return out


def ema(values: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(values)
    if len(values) < n:
        return out
    k = 2 / (n + 1)
    prev = sum(values[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes: Sequence[float], n: int = 14) -> Series:
    out: Series = [None] * len(closes)
    if len(closes) <= n:
        return out
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gain = sum(c for c in changes[:n] if c > 0) / n
    loss = sum(-c for c in changes[:n] if c < 0) / n

    def value() -> float:
        if loss == 0:
            return 50.0 if gain == 0 else 100.0
        return 100 - 100 / (1 + gain / loss)

    out[n] = value()
    for i in range(n + 1, len(closes)):
        change = changes[i - 1]
        gain = (gain * (n - 1) + max(change, 0)) / n
        loss = (loss * (n - 1) + max(-change, 0)) / n
        out[i] = value()
    return out


def macd(
    closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[Series, Series, Series]:
    f, s = ema(closes, fast), ema(closes, slow)
    line: Series = [None if a is None or b is None else a - b for a, b in zip(f, s, strict=True)]
    start = next((i for i, v in enumerate(line) if v is not None), len(line))
    tail = ema([v for v in line[start:] if v is not None], signal)
    sig: Series = [None] * start + tail
    hist: Series = [
        None if a is None or b is None else a - b for a, b in zip(line, sig, strict=True)
    ]
    return line, sig, hist


def bollinger(closes: Sequence[float], n: int = 20, k: float = 2) -> tuple[Series, Series, Series]:
    upper: Series = []
    middle: Series = []
    lower: Series = []
    for i in range(len(closes)):
        if i < n - 1:
            upper.append(None)
            middle.append(None)
            lower.append(None)
            continue
        window = closes[i - n + 1 : i + 1]
        mean = sum(window) / n
        sd = sqrt(sum((x - mean) ** 2 for x in window) / n)
        upper.append(mean + k * sd)
        middle.append(mean)
        lower.append(mean - k * sd)
    return upper, middle, lower


def vwap(bars: Sequence[dict[str, float | None]]) -> Series:
    out: Series = []
    day = None
    pv = vol = 0.0
    for bar in bars:
        today = floor(float(bar["t"] or 0) / 86400)
        if today != day:
            day, pv, vol = today, 0.0, 0.0
        volume = bar["volume"]
        if volume is None:
            out.append(None)
            continue
        high, low, close = float(bar["high"] or 0), float(bar["low"] or 0), float(bar["close"] or 0)
        pv += (high + low + close) / 3 * volume
        vol += volume
        out.append(pv / vol if vol > 0 else None)
    return out
