// SPDX-License-Identifier: AGPL-3.0-or-later
// Price chart on TradingView Lightweight Charts (Apache-2.0; attribution in
// NOTICE and as a link under the chart, see ChartArea). The library's own
// logo is off because it injects an inline <style>, which our CSP blocks.
// History comes from the API's cache; live quotes move the last bar.
// Indicators come from @opencharts/indicators and are recomputed on each
// live update (well under a millisecond for a chart's worth of bars).
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type SeriesType,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { Indicator } from '../workspace/types';
import { DrawingEditor } from './DrawingEditor';
import { DrawingLayer } from './DrawingLayer';
import { TimeAxis, type Drawing } from './drawings';
import {
  indicatorLines,
  panesFor,
  toBars,
  type Bar as IndicatorBar,
  type IndicatorLine,
  type PaneKind,
} from './indicators';
import type { Candle, History, Quote } from './types';
import type { DrawingsApi } from './useDrawings';

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

/** The indicator bars with the live bar applied (its volume stays as it was). */
function withLiveBar(bars: IndicatorBar[], live: Bar): IndicatorBar[] {
  const last = bars.at(-1);
  const next = { t: live.time, open: live.open, high: live.high, low: live.low, close: live.close };
  if (last && last.t === live.time) return [...bars.slice(0, -1), { ...next, volume: last.volume }];
  return [...bars, { ...next, volume: null }];
}

type Point = { time: UTCTimestamp; value: number; color?: string };

function points(line: IndicatorLine, bars: readonly IndicatorBar[], color: (v: string) => string) {
  const out: Point[] = [];
  line.values.forEach((value, i) => {
    const bar = bars[i];
    if (value == null || !bar) return;
    const c = line.colors?.[i];
    out.push({ time: bar.t as UTCTimestamp, value, ...(c ? { color: color(c) } : {}) });
  });
  return out;
}

export interface Readout {
  label: string;
  value: number;
}

export function PriceChart({
  history,
  quote,
  chartType,
  showGrid,
  showOhlc,
  indicators = [],
  drawings,
}: {
  history: History;
  quote: Quote | undefined;
  chartType: 'candle' | 'line';
  showGrid: boolean;
  showOhlc: boolean;
  indicators?: Indicator[];
  /** The user's drawings for this instrument; without it, none are shown. */
  drawings?: DrawingsApi;
}) {
  const container = useRef<HTMLDivElement>(null);
  const chartApi = useRef<IChartApi | null>(null);
  const layer = useRef<DrawingLayer | null>(null);
  const latestDrawings = useRef<Drawing[]>([]);
  const series = useRef<ISeriesApi<SeriesType> | null>(null);
  const extra = useRef<Map<string, ISeriesApi<SeriesType>>>(new Map());
  const last = useRef<Bar | null>(null);
  const [hover, setHover] = useState<{ bar: Bar; index: number } | null>(null);
  const weekly = history.period === 'ALL';
  // Rebuild only when the chosen indicators really change.
  const indicatorKey = JSON.stringify(indicators);
  const chosen = useMemo(() => JSON.parse(indicatorKey) as Indicator[], [indicatorKey]);
  const baseBars = useMemo(() => toBars(history.candles), [history]);

  // A rebuilt chart starts with whatever drawings are current.
  useEffect(() => {
    latestDrawings.current = drawings?.drawings ?? [];
  });

  // Create the chart and series, and load history.
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const bars = history.candles.map(toBar);
    const intraday = history.interval !== '1d';
    const color = (name: string) => cssVar(name, '#848991');
    const api: IChartApi = createChart(element, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: cssVar('--surface', '#101215') },
        textColor: cssVar('--muted', '#848991'),
        fontFamily: cssVar('--font-sans', 'sans-serif'),
        attributionLogo: false,
        panes: { separatorColor: cssVar('--line', '#25282d') },
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

    // Indicators: overlays on the price, oscillators in panes below.
    const lines = indicatorLines(chosen, baseBars);
    const paneIndex: Record<PaneKind, number> = { price: 0, volume: 0, rsi: 0, macd: 0 };
    panesFor(lines).forEach((pane, i) => (paneIndex[pane] = i + 1));
    const added = new Map<string, ISeriesApi<SeriesType>>();
    for (const line of lines) {
      const common = {
        priceLineVisible: false,
        lastValueVisible: line.pane !== 'price' && line.pane !== 'volume',
        title: '',
      };
      const target =
        line.kind === 'histogram'
          ? api.addSeries(
              HistogramSeries,
              {
                ...common,
                color: color(line.color),
                ...(line.pane === 'volume'
                  ? { priceScaleId: 'volume', priceFormat: { type: 'volume' as const } }
                  : {}),
              },
              paneIndex[line.pane],
            )
          : api.addSeries(
              LineSeries,
              {
                ...common,
                color: color(line.color),
                lineWidth: line.pane === 'price' ? 1 : 2,
                lineStyle: line.kind === 'dashed' ? LineStyle.Dashed : LineStyle.Solid,
                crosshairMarkerVisible: false,
                ...(line.pane === 'price' ? { priceFormat } : {}),
              },
              paneIndex[line.pane],
            );
      if (line.pane === 'volume') {
        target.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      }
      if (line.pane === 'rsi') {
        for (const level of [70, 30]) {
          target.createPriceLine({
            price: level,
            color: cssVar('--line', '#25282d'),
            lineStyle: LineStyle.Dashed,
            lineWidth: 1,
            axisLabelVisible: false,
          });
        }
      }
      target.setData(points(line, baseBars, color));
      added.set(line.id, target);
    }
    // The price keeps most of the height; each indicator pane gets a strip.
    const panes = api.panes();
    panes.forEach((pane, i) => pane.setStretchFactor(i === 0 ? 3 : 1));

    // Drawings sit on the price, in time and price coordinates.
    const fontFamily = cssVar('--font-sans', 'sans-serif');
    const drawingLayer = new DrawingLayer(
      (name) => cssVar(name, '#b4abff'),
      fontFamily,
      (price) =>
        price.toLocaleString(undefined, {
          minimumFractionDigits: precision,
          maximumFractionDigits: precision,
        }),
    );
    drawingLayer.axis = new TimeAxis(bars.map((b) => b.time));
    s.attachPrimitive(drawingLayer);
    drawingLayer.update({ shapes: latestDrawings.current });
    layer.current = drawingLayer;
    chartApi.current = api;

    api.timeScale().fitContent();
    const indexOf = new Map(bars.map((b, i) => [b.time as number, i]));
    api.subscribeCrosshairMove((param) => {
      const index = param.time === undefined ? undefined : indexOf.get(param.time as number);
      const bar = index === undefined ? undefined : bars[index];
      setHover(bar && index !== undefined ? { bar, index } : null);
    });
    series.current = s;
    extra.current = added;
    last.current = bars.at(-1) ?? null;
    return () => {
      api.remove();
      series.current = null;
      extra.current = new Map();
      chartApi.current = null;
      layer.current = null;
    };
    // Rebuild when the data, the look or the indicators change.
  }, [history, chartType, showGrid, chosen, baseBars]);

  // Move the last bar, and the indicators, with live quotes.
  useEffect(() => {
    const s = series.current;
    const bar = last.current;
    if (!s || !bar || !quote || quote.instrument_id !== history.instrument_id) return;
    const next = advance(bar, quote, history.interval, weekly);
    if (!next) return;
    if (next.time !== bar.time && layer.current) {
      // A new bar: drawings measure time against the bars on the chart.
      layer.current.axis = new TimeAxis([...baseBars.map((b) => b.t), next.time]);
    }
    last.current = next;
    s.update(chartType === 'candle' ? next : { time: next.time, value: next.close });
    if (extra.current.size === 0) return;
    const bars = withLiveBar(baseBars, next);
    const color = (name: string) => cssVar(name, '#848991');
    for (const line of indicatorLines(chosen, bars)) {
      const target = extra.current.get(line.id);
      const value = line.values.at(-1);
      // Volume isn't in quotes; leave its bar as it was.
      if (!target || value == null || line.pane === 'volume') continue;
      const c = line.colors?.at(-1);
      target.update({ time: next.time, value, ...(c ? { color: color(c) } : {}) });
    }
  }, [quote, history, chartType, weekly, chosen, baseBars]);

  const lastBar = history.candles.at(-1);
  const latest = lastBar ? toBar(lastBar) : null;
  const live =
    latest && quote?.instrument_id === history.instrument_id
      ? (advance(latest, quote, history.interval, weekly) ?? latest)
      : latest;
  const shown = hover?.bar ?? live;
  const digits = precisionFor(latest?.close ?? 1);
  const fmt = (n: number, places = digits) =>
    n.toLocaleString(undefined, { minimumFractionDigits: places, maximumFractionDigits: places });
  // Hovering shows that bar's values; otherwise the latest, live ones.
  const readoutBars = hover || !live ? baseBars : withLiveBar(baseBars, live);
  const readoutIndex = hover?.index ?? readoutBars.length - 1;
  const readouts =
    chosen.length === 0
      ? []
      : indicatorLines(chosen, readoutBars)
          .filter(
            (l) => l.pane !== 'volume' && !l.label.endsWith('upper') && !l.label.endsWith('lower'),
          )
          .flatMap((l): Readout[] => {
            const value = l.values[readoutIndex];
            return value == null ? [] : [{ label: l.label.replace(' middle', ''), value }];
          });
  return (
    <div className="price-chart">
      {(showOhlc || readouts.length > 0) && (
        <div className="ohlc" aria-label="Chart values">
          {showOhlc && shown && (
            <>
              <span>O {fmt(shown.open)}</span>
              <span>H {fmt(shown.high)}</span>
              <span>L {fmt(shown.low)}</span>
              <span>C {fmt(shown.close)}</span>
            </>
          )}
          {readouts.map((r) => (
            <span key={r.label} className="indicator-value">
              {r.label} {fmt(r.value, /^(RSI|MACD)/.test(r.label) ? 2 : digits)}
            </span>
          ))}
        </div>
      )}
      <div ref={container} className="chart-canvas" data-testid="price-chart" />
      {drawings && (
        <DrawingEditor container={container} chart={chartApi} layer={layer} store={drawings} />
      )}
    </div>
  );
}
