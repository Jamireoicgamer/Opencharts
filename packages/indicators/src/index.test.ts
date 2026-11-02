// SPDX-License-Identifier: AGPL-3.0-or-later
// The TypeScript indicators against the Python reference
// (reference/indicators.py) on recorded Coinbase bars.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { bollinger, ema, macd, rsi, sma, vwap, type Bar, type Series } from './index';

const fixture = (name: string) => resolve(__dirname, '../fixtures', name);

function load(name: string) {
  const bars = (JSON.parse(readFileSync(fixture(`${name}.json`), 'utf8')) as { bars: Bar[] }).bars;
  const expected = JSON.parse(readFileSync(fixture(`${name}.expected.json`), 'utf8')) as {
    sma20: Series;
    ema20: Series;
    ema50: Series;
    rsi14: Series;
    macd: Record<'macd' | 'signal' | 'histogram', Series>;
    bollinger: Record<'upper' | 'middle' | 'lower', Series>;
    vwap: Series;
  };
  return { bars, closes: bars.map((b) => b.close), expected };
}

function same(actual: Series, wanted: Series) {
  expect(actual).toHaveLength(wanted.length);
  actual.forEach((value, i) => {
    const want = wanted[i] ?? null;
    if (want === null) expect(value, `index ${i}`).toBeNull();
    else
      expect(Math.abs((value ?? NaN) - want), `index ${i}`).toBeLessThan(
        1e-9 * Math.max(1, Math.abs(want)),
      );
  });
}

describe.each(['btc_1d', 'btc_5m'])('matches the Python reference on %s', (name) => {
  const { bars, closes, expected } = load(name);
  it('moving averages', () => {
    same(sma(closes, 20), expected.sma20);
    same(ema(closes, 20), expected.ema20);
    same(ema(closes, 50), expected.ema50);
  });
  it('RSI', () => same(rsi(closes, 14), expected.rsi14));
  it('MACD', () => {
    const m = macd(closes);
    same(m.macd, expected.macd.macd);
    same(m.signal, expected.macd.signal);
    same(m.histogram, expected.macd.histogram);
  });
  it('Bollinger Bands', () => {
    const b = bollinger(closes);
    same(b.upper, expected.bollinger.upper);
    same(b.middle, expected.bollinger.middle);
    same(b.lower, expected.bollinger.lower);
  });
  it('VWAP', () => same(vwap(bars), expected.vwap));
});

describe('edge cases', () => {
  it('returns all nulls without enough history', () => {
    expect(sma([1, 2], 3)).toEqual([null, null]);
    expect(ema([1, 2], 3)).toEqual([null, null]);
    expect(rsi([1, 2, 3], 14)).toEqual([null, null, null]);
    expect(macd([1, 2, 3]).signal).toEqual([null, null, null]);
  });
  it('a flat market has an RSI of 50 and a rising one 100', () => {
    expect(rsi([5, 5, 5, 5], 3)[3]).toBe(50);
    expect(rsi([1, 2, 3, 4], 3)[3]).toBe(100);
  });
  it('VWAP restarts each UTC day and skips bars without volume', () => {
    const bar = (t: number, price: number, volume: number | null): Bar => ({
      t,
      open: price,
      high: price,
      low: price,
      close: price,
      volume,
    });
    expect(vwap([bar(0, 10, 1), bar(60, 20, 1), bar(86400, 30, 2), bar(86460, 5, null)])).toEqual([
      10,
      15,
      30,
      null,
    ]);
  });
  it('refuses bad periods', () => {
    expect(() => sma([1], 0)).toThrow(RangeError);
    expect(() => ema([1], 2.5)).toThrow(RangeError);
    expect(() => macd([1], 26, 12)).toThrow(RangeError);
  });
  it('is fast enough to recompute on every live tick', () => {
    const closes = Array.from({ length: 2000 }, (_, i) => 100 + Math.sin(i / 10));
    const started = performance.now();
    for (let i = 0; i < 10; i++) {
      sma(closes, 20);
      ema(closes, 50);
      rsi(closes);
      macd(closes);
      bollinger(closes);
    }
    expect((performance.now() - started) / 10).toBeLessThan(20);
  });
});
