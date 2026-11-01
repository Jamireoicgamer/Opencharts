// SPDX-License-Identifier: AGPL-3.0-or-later
// Price chart on TradingView Lightweight Charts (Apache-2.0; attribution in
// NOTICE and as a link under the chart, see ChartArea). The library's own
// logo is off because it injects an inline <style>, which our CSP blocks.
// History comes from the API's cache; live quotes move the last bar.
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type SeriesType,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useEffect, useRef, useState } from 'react';
import type { Candle, History, Quote } from './types';

const INTERVAL_SECONDS = { '5m': 300, '1h': 3600, '1d': 86400 } as const;

interface Bar {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
}

const toTime = (iso: string) => Math.floor(Date.parse(iso) / 1000) as UTCTimestamp;

const toBar = (c: Candle): Bar => ({
  time: toTime(c.t),
  open: Number(c.open),
  high: Number(c.high),
  low: Number(c.low),
  close: Number(c.close),
});

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** Decimal places that suit the price's size (crypto under $1 needs more). */
export function precisionFor(price: number): number {
  if (price >= 1000) return 2;
  if (price >= 1) return 2;
  if (price >= 0.01) return 4;
  return 6;
}

/** The start of the bar a quote at `at` belongs to. */
export function barStart(at: number, interval: History['interval'], weekly: boolean): number {
  if (weekly) {
    const day = Math.floor(at / 86400) * 86400;
    const weekday = (new Date(day * 1000).getUTCDay() + 6) % 7; // Monday = 0
    return day - weekday * 86400;
  }
  const size = INTERVAL_SECONDS[interval];
  return Math.floor(at / size) * size;
}

/**
 * The last bar after a live quote: the same bar moved, a new bar, or null
 * when the quote does not belong on this chart.
 */
export function advance(
  bar: Bar,
  quote: Quote,
  interval: History['interval'],
  weekly: boolean,
): Bar | null {
  const price = Number(quote.price);
  const start = barStart(toTime(quote.at), interval, weekly) as UTCTimestamp;
  if (start === bar.time) {
    return { ...bar, high: Math.max(bar.high, price), low: Math.min(bar.low, price), close: price };
  }
  // A new bar begins only while the market is open, so an overnight date
  // change never invents a bar; weekly views just wait for history.
  if (start > bar.time && quote.market_state === 'open' && !weekly) {
    return { time: start, open: price, high: price, low: price, close: price };
  }
  return null;
}

export function PriceChart({
  history,
  quote,
  chartType,
  showGrid,
  showOhlc,
}: {
  history: History;
  quote: Quote | undefined;
  chartType: 'candle' | 'line';
  showGrid: boolean;
  showOhlc: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<SeriesType> | null>(null);
  const last = useRef<Bar | null>(null);
  const [hover, setHover] = useState<Bar | null>(null);
  const weekly = history.period === 'ALL';

  // Create the chart and series, and load history.
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const bars = history.candles.map(toBar);
    const intraday = history.interval !== '1d';
    const api = createChart(element, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: cssVar('--surface', '#101215') },
        textColor: cssVar('--muted', '#848991'),
        fontFamily: cssVar('--font-sans', 'sans-serif'),
        attributionLogo: false,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { visible: showGrid, color: cssVar('--line', '#25282d') },
      },
      rightPriceScale: { borderColor: cssVar('--line', '#25282d') },
      timeScale: {
        borderColor: cssVar('--line', '#25282d'),
        timeVisible: intraday,
        secondsVisible: false,
      },
      crosshair: { mode: CrosshairMode.Normal },
    });
    const up = cssVar('--green', '#39c7a1');
    const down = cssVar('--red', '#e87780');
    const precision = precisionFor(bars.at(-1)?.close ?? 1);
    const priceFormat = { type: 'price' as const, precision, minMove: 10 ** -precision };
    const s: ISeriesApi<SeriesType> =
      chartType === 'candle'
        ? api.addSeries(CandlestickSeries, {
            upColor: up,
            downColor: down,
            wickUpColor: up,
            wickDownColor: down,
            borderVisible: false,
            priceFormat,
          })
        : api.addSeries(LineSeries, { color: up, lineWidth: 2, priceFormat });
    s.setData(chartType === 'candle' ? bars : bars.map((b) => ({ time: b.time, value: b.close })));
    api.timeScale().fitContent();
    api.subscribeCrosshairMove((param) => {
      const bar = param.time === undefined ? undefined : bars.find((b) => b.time === param.time);
      setHover(bar ?? null);
    });
    chart.current = api;
    series.current = s;
    last.current = bars.at(-1) ?? null;
    return () => {
      api.remove();
      chart.current = null;
      series.current = null;
    };
    // Rebuild when the data or the look changes.
  }, [history, chartType, showGrid]);

  // Move the last bar with live quotes.
  useEffect(() => {
    const s = series.current;
    const bar = last.current;
    if (!s || !bar || !quote || quote.instrument_id !== history.instrument_id) return;
    const next = advance(bar, quote, history.interval, weekly);
    if (!next) return;
    last.current = next;
    s.update(chartType === 'candle' ? next : { time: next.time, value: next.close });
  }, [quote, history, chartType, weekly]);

  const lastBar = history.candles.at(-1);
  const latest = lastBar ? toBar(lastBar) : null;
  const live =
    latest && quote?.instrument_id === history.instrument_id
      ? (advance(latest, quote, history.interval, weekly) ?? latest)
      : latest;
  const shown = hover ?? live;
  const digits = precisionFor(latest?.close ?? 1);
  const fmt = (n: number) =>
    n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return (
    <div className="price-chart">
      {showOhlc && shown && (
        <div className="ohlc" aria-label="Open, high, low, close">
          <span>O {fmt(shown.open)}</span>
          <span>H {fmt(shown.high)}</span>
          <span>L {fmt(shown.low)}</span>
          <span>C {fmt(shown.close)}</span>
        </div>
      )}
      <div ref={container} className="chart-canvas" data-testid="price-chart" />
    </div>
  );
}
