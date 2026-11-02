// SPDX-License-Identifier: AGPL-3.0-or-later
// Turns the chosen indicators into lines for the chart, using the shared,
// deterministic @opencharts/indicators package.
import * as calc from '@opencharts/indicators';
import type { Bar, Series } from '@opencharts/indicators';
import type { Indicator, IndicatorKind } from '../workspace/types';
import type { Candle } from './types';

export type { Bar };

/** Where a line is drawn: over the price, or in its own pane below. */
export type PaneKind = 'price' | 'volume' | 'rsi' | 'macd';

export interface IndicatorLine {
  id: string;
  /** Shown in the readout, e.g. "EMA 20" or "MACD signal". */
  label: string;
  pane: PaneKind;
  kind: 'line' | 'dashed' | 'histogram';
  /** A CSS custom property name, resolved by the chart. */
  color: string;
  values: Series;
  /** Per-bar colours for histograms (volume, MACD histogram). */
  colors?: string[];
}

export const INDICATOR_KINDS: { kind: IndicatorKind; name: string; period: number | null }[] = [
  { kind: 'sma', name: 'Simple moving average', period: 20 },
  { kind: 'ema', name: 'Exponential moving average', period: 20 },
  { kind: 'bollinger', name: 'Bollinger Bands', period: 20 },
  { kind: 'vwap', name: 'VWAP', period: null },
  { kind: 'volume', name: 'Volume', period: null },
  { kind: 'rsi', name: 'RSI', period: 14 },
  { kind: 'macd', name: 'MACD', period: null },
];

export const MAX_INDICATORS = 10;

export function indicatorLabel(i: Indicator): string {
  switch (i.kind) {
    case 'sma':
      return `SMA ${i.period}`;
    case 'ema':
      return `EMA ${i.period}`;
    case 'bollinger':
      return `Bollinger ${i.period}, 2`;
    case 'rsi':
      return `RSI ${i.period}`;
    case 'macd':
      return 'MACD 12, 26, 9';
    case 'vwap':
      return 'VWAP';
    case 'volume':
      return 'Volume';
  }
}

export function toBars(candles: readonly Candle[]): Bar[] {
  return candles.map((c) => ({
    t: Math.floor(Date.parse(c.t) / 1000),
    open: Number(c.open),
    high: Number(c.high),
    low: Number(c.low),
    close: Number(c.close),
    volume: c.volume == null ? null : Number(c.volume),
  }));
}

// Price-pane lines cycle through these; candles use green and red.
const OVERLAY_COLORS = ['--accent', '--amber', '--blue', '--pink'];

/** The lines to draw for these indicators, in a stable order. */
export function indicatorLines(
  indicators: readonly Indicator[],
  bars: readonly Bar[],
): IndicatorLine[] {
  const closes = bars.map((b) => b.close);
  const lines: IndicatorLine[] = [];
  let overlay = 0;
  const nextColor = () => OVERLAY_COLORS[overlay++ % OVERLAY_COLORS.length] as string;
  for (const i of indicators) {
    const id = `${i.kind}-${i.period ?? ''}`;
    const label = indicatorLabel(i);
    const n = i.period ?? 0;
    switch (i.kind) {
      case 'sma':
      case 'ema': {
        const values = i.kind === 'sma' ? calc.sma(closes, n) : calc.ema(closes, n);
        lines.push({ id, label, pane: 'price', kind: 'line', color: nextColor(), values });
        break;
      }
      case 'bollinger': {
        const b = calc.bollinger(closes, n, 2);
        const color = nextColor();
        lines.push(
          {
            id: `${id}-u`,
            label: `${label} upper`,
            pane: 'price',
            kind: 'dashed',
            color,
            values: b.upper,
          },
          {
            id: `${id}-m`,
            label: `${label} middle`,
            pane: 'price',
            kind: 'line',
            color,
            values: b.middle,
          },
          {
            id: `${id}-l`,
            label: `${label} lower`,
            pane: 'price',
            kind: 'dashed',
            color,
            values: b.lower,
          },
        );
        break;
      }
      case 'vwap':
        lines.push({
          id,
          label,
          pane: 'price',
          kind: 'line',
          color: nextColor(),
          values: calc.vwap(bars),
        });
        break;
      case 'volume':
        lines.push({
          id,
          label,
          pane: 'volume',
          kind: 'histogram',
          color: '--muted',
          values: bars.map((b) => b.volume),
          colors: bars.map((b) => (b.close >= b.open ? '--green' : '--red')),
        });
        break;
      case 'rsi':
        lines.push({
          id,
          label,
          pane: 'rsi',
          kind: 'line',
          color: '--accent',
          values: calc.rsi(closes, n),
        });
        break;
      case 'macd': {
        const m = calc.macd(closes);
        lines.push(
          {
            id: `${id}-h`,
            label: 'MACD histogram',
            pane: 'macd',
            kind: 'histogram',
            color: '--muted',
            values: m.histogram,
            colors: m.histogram.map((v) => ((v ?? 0) >= 0 ? '--green' : '--red')),
          },
          {
            id: `${id}-m`,
            label: 'MACD',
            pane: 'macd',
            kind: 'line',
            color: '--blue',
            values: m.macd,
          },
          {
            id: `${id}-s`,
            label: 'MACD signal',
            pane: 'macd',
            kind: 'line',
            color: '--amber',
            values: m.signal,
          },
        );
        break;
      }
    }
  }
  return lines;
}

/** Which extra panes are needed, in display order. */
export function panesFor(lines: readonly IndicatorLine[]): PaneKind[] {
  const order: PaneKind[] = ['rsi', 'macd'];
  return order.filter((p) => lines.some((l) => l.pane === p));
}
