// SPDX-License-Identifier: AGPL-3.0-or-later
// Deterministic technical indicators. Every function returns one value per
// input bar, null until it has enough history ("warm-up"). The same
// formulas are implemented in Python (reference/indicators.py) and the two
// are checked against each other on recorded market data.

export interface Bar {
  /** Bar start, Unix seconds (UTC). */
  t: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
}

export type Series = (number | null)[];

/** values[i], for indexes the loops below keep in range. */
const at = (values: readonly number[], i: number): number => values[i] as number;

/** series[i] where the caller has already checked it isn't null. */
const num = (series: Series, i: number): number => series[i] as number;

function checkPeriod(n: number): void {
  if (!Number.isInteger(n) || n < 1) throw new RangeError(`period must be a positive integer`);
}

/** Simple moving average of the last n values. */
export function sma(values: readonly number[], n: number): Series {
  checkPeriod(n);
  const out: Series = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += at(values, i);
    if (i >= n) sum -= at(values, i - n);
    if (i >= n - 1) out[i] = sum / n;
  }
  return out;
}

/** Exponential moving average, k = 2/(n+1), seeded with the SMA of the first n values. */
export function ema(values: readonly number[], n: number): Series {
  checkPeriod(n);
  const out: Series = new Array(values.length).fill(null);
  if (values.length < n) return out;
  const k = 2 / (n + 1);
  let prev = 0;
  for (let i = 0; i < n; i++) prev += at(values, i);
  prev /= n;
  out[n - 1] = prev;
  for (let i = n; i < values.length; i++) {
    prev = at(values, i) * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

/** EMA over a series that starts with nulls (used for MACD's signal line). */
function emaOfSeries(values: Series, n: number): Series {
  const start = values.findIndex((v) => v !== null);
  const out: Series = new Array(values.length).fill(null);
  if (start < 0) return out;
  const tail = ema(values.slice(start) as number[], n);
  tail.forEach((v, i) => (out[start + i] = v));
  return out;
}

/** Relative strength index with Wilder's smoothing. */
export function rsi(closes: readonly number[], n = 14): Series {
  checkPeriod(n);
  const out: Series = new Array(closes.length).fill(null);
  if (closes.length <= n) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= n; i++) {
    const change = at(closes, i) - at(closes, i - 1);
    if (change > 0) gain += change;
    else loss -= change;
  }
  gain /= n;
  loss /= n;
  const value = () => (loss === 0 ? (gain === 0 ? 50 : 100) : 100 - 100 / (1 + gain / loss));
  out[n] = value();
  for (let i = n + 1; i < closes.length; i++) {
    const change = at(closes, i) - at(closes, i - 1);
    gain = (gain * (n - 1) + Math.max(change, 0)) / n;
    loss = (loss * (n - 1) + Math.max(-change, 0)) / n;
    out[i] = value();
  }
  return out;
}

export interface Macd {
  macd: Series;
  signal: Series;
  histogram: Series;
}

/** MACD line (fast EMA − slow EMA), its signal EMA, and their difference. */
export function macd(closes: readonly number[], fast = 12, slow = 26, signal = 9): Macd {
  checkPeriod(fast);
  checkPeriod(slow);
  checkPeriod(signal);
  if (fast >= slow) throw new RangeError('the fast period must be shorter than the slow one');
  const f = ema(closes, fast);
  const s = ema(closes, slow);
  const line: Series = closes.map((_, i) =>
    f[i] == null || s[i] == null ? null : num(f, i) - num(s, i),
  );
  const sig = emaOfSeries(line, signal);
  const histogram: Series = line.map((m, i) =>
    m == null || sig[i] == null ? null : m - num(sig, i),
  );
  return { macd: line, signal: sig, histogram };
}

export interface Bands {
  upper: Series;
  middle: Series;
  lower: Series;
}

/** Bollinger Bands: SMA ± k population standard deviations. */
export function bollinger(closes: readonly number[], n = 20, k = 2): Bands {
  checkPeriod(n);
  const middle = sma(closes, n);
  const upper: Series = new Array(closes.length).fill(null);
  const lower: Series = new Array(closes.length).fill(null);
  for (let i = n - 1; i < closes.length; i++) {
    const mean = num(middle, i);
    let squares = 0;
    for (let j = i - n + 1; j <= i; j++) squares += (at(closes, j) - mean) ** 2;
    const sd = Math.sqrt(squares / n);
    upper[i] = mean + k * sd;
    lower[i] = mean - k * sd;
  }
  return { upper, middle, lower };
}

/**
 * Volume-weighted average price of the typical price (high+low+close)/3,
 * restarting at each UTC day. Null where the source gives no volume.
 */
export function vwap(bars: readonly Bar[]): Series {
  const out: Series = new Array(bars.length).fill(null);
  let day = -1;
  let priceVolume = 0;
  let volume = 0;
  bars.forEach((bar, i) => {
    const today = Math.floor(bar.t / 86400);
    if (today !== day) {
      day = today;
      priceVolume = 0;
      volume = 0;
    }
    if (bar.volume == null) return;
    priceVolume += ((bar.high + bar.low + bar.close) / 3) * bar.volume;
    volume += bar.volume;
    out[i] = volume > 0 ? priceVolume / volume : null;
  });
  return out;
}
