// SPDX-License-Identifier: AGPL-3.0-or-later
// Draws the user's shapes on the price pane, through Lightweight Charts'
// series-primitive API, so they scroll and zoom with the chart and need no
// extra canvas or inline styles (our CSP forbids those).
import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  Logical,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from 'lightweight-charts';
import { fibPrices, TimeAxis, type DrawingInput, type Pixel } from './drawings';

type Target = Parameters<IPrimitivePaneRenderer['draw']>[0];

export interface Shape extends DrawingInput {
  id: string;
}

export interface LayerState {
  shapes: Shape[];
  selected: string | null;
  /** A drawing being placed, its last point following the pointer. */
  draft: Shape | null;
}

export class DrawingLayer implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType> | null = null;
  private requestUpdate: (() => void) | null = null;
  private state: LayerState = { shapes: [], selected: null, draft: null };
  axis: TimeAxis = new TimeAxis([]);

  constructor(
    private readonly color: (name: string) => string,
    private readonly font: string,
    private readonly formatPrice: (price: number) => string,
  ) {}

  attached(param: SeriesAttachedParameter<Time>): void {
    this.chart = param.chart as IChartApi;
    this.series = param.series as ISeriesApi<SeriesType>;
    this.requestUpdate = param.requestUpdate;
  }

  detached(): void {
    this.chart = null;
    this.series = null;
    this.requestUpdate = null;
  }

  update(next: Partial<LayerState>): void {
    this.state = { ...this.state, ...next };
    this.requestUpdate?.();
  }

  get current(): LayerState {
    return this.state;
  }

  /** A time and price as a pixel on the price pane. */
  toPixel(t: number, price: number): Pixel | null {
    if (!this.chart || !this.series) return null;
    const logical = this.axis.toLogical(t);
    if (logical == null) return null;
    const x = this.chart.timeScale().logicalToCoordinate(logical as Logical);
    const y = this.series.priceToCoordinate(price);
    return x == null || y == null ? null : { x, y };
  }

  /** A pixel as a time (snapped to the nearest bar) and price. */
  fromPixel(p: Pixel): { t: number; price: number } | null {
    if (!this.chart || !this.series) return null;
    const logical = this.chart.timeScale().coordinateToLogical(p.x);
    const price = this.series.coordinateToPrice(p.y);
    if (logical == null || price == null) return null;
    const t = this.axis.toTime(Math.round(logical));
    return t == null ? null : { t, price };
  }

  priceToY(price: number): number | null {
    return this.series?.priceToCoordinate(price) ?? null;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [{ zOrder: () => 'top', renderer: () => this.renderer() }];
  }

  private renderer(): IPrimitivePaneRenderer {
    const shapes = this.state.draft ? [...this.state.shapes, this.state.draft] : this.state.shapes;
    return {
      draw: (target: Target) => {
        target.useMediaCoordinateSpace(({ context, mediaSize }) => {
          context.save();
          context.font = `11px ${this.font}`;
          context.lineWidth = 1.5;
          for (const shape of shapes) {
            this.drawShape(context, mediaSize.width, shape, shape.id === this.state.selected);
          }
          context.restore();
        });
      },
    };
  }

  private drawShape(
    ctx: CanvasRenderingContext2D,
    width: number,
    shape: Shape,
    selected: boolean,
  ): void {
    const pixels = shape.points.map((p) => this.toPixel(p.t, p.price));
    if (pixels.some((p) => p == null)) return;
    const [a, b] = pixels as Pixel[];
    if (!a) return;
    const stroke = this.color(`--${shape.color}`);
    ctx.strokeStyle = stroke;
    ctx.fillStyle = stroke;
    ctx.setLineDash([]);
    switch (shape.kind) {
      case 'trend':
        if (!b) return;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
        break;
      case 'hline': {
        ctx.beginPath();
        ctx.moveTo(0, a.y);
        ctx.lineTo(width, a.y);
        ctx.stroke();
        const label = `${shape.text ? `${shape.text} · ` : ''}${this.formatPrice(shape.points[0]?.price ?? 0)}`;
        ctx.fillText(label, 8, a.y - 5);
        break;
      }
      case 'rect': {
        if (!b) return;
        const x = Math.min(a.x, b.x);
        const y = Math.min(a.y, b.y);
        const w = Math.abs(b.x - a.x);
        const h = Math.abs(b.y - a.y);
        ctx.globalAlpha = 0.12;
        ctx.fillRect(x, y, w, h);
        ctx.globalAlpha = 1;
        ctx.strokeRect(x, y, w, h);
        if (shape.text) ctx.fillText(shape.text, x + 4, y - 5);
        break;
      }
      case 'fib': {
        if (!b) return;
        const start = shape.points[0]?.price ?? 0;
        const end = shape.points[1]?.price ?? 0;
        const left = Math.min(a.x, b.x);
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
        ctx.setLineDash([]);
        for (const { level, price } of fibPrices(start, end)) {
          const y = this.priceToY(price);
          if (y == null) continue;
          ctx.globalAlpha = level === 0 || level === 1 ? 1 : 0.7;
          ctx.beginPath();
          ctx.moveTo(left, y);
          ctx.lineTo(width, y);
          ctx.stroke();
          ctx.fillText(`${(level * 100).toFixed(1)}%  ${this.formatPrice(price)}`, left + 4, y - 4);
        }
        ctx.globalAlpha = 1;
        break;
      }
      case 'note': {
        ctx.beginPath();
        ctx.arc(a.x, a.y, 3.5, 0, Math.PI * 2);
        ctx.fill();
        const text = shape.text || 'Note';
        const padding = 6;
        const w = ctx.measureText(text).width + padding * 2;
        ctx.globalAlpha = 0.9;
        ctx.fillStyle = this.color('--raised');
        ctx.fillRect(a.x + 8, a.y - 22, w, 20);
        ctx.globalAlpha = 1;
        ctx.strokeRect(a.x + 8, a.y - 22, w, 20);
        ctx.fillStyle = this.color('--text');
        ctx.fillText(text, a.x + 8 + padding, a.y - 8);
        break;
      }
    }
    if (selected) {
      ctx.fillStyle = this.color('--text');
      for (const p of pixels as Pixel[]) ctx.fillRect(p.x - 4, p.y - 4, 8, 8);
    }
  }
}
