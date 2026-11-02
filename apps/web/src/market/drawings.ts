// SPDX-License-Identifier: AGPL-3.0-or-later
// Chart drawings: the saved shapes, and the geometry that places them.
// Points are kept in time and price, so drawings stay put however the
// chart is scrolled or zoomed, and across chart periods.

export type DrawingKind = 'trend' | 'hline' | 'rect' | 'fib' | 'note';
export type DrawingColor = 'accent' | 'amber' | 'blue' | 'pink' | 'green' | 'red' | 'muted';

export interface DrawingPoint {
  /** Unix seconds. */
  t: number;
  price: number;
}

export interface DrawingInput {
  kind: DrawingKind;
  points: DrawingPoint[];
  color: DrawingColor;
  text: string;
}

export interface Drawing extends DrawingInput {
  id: string;
  instrument_id: string;
  created_at: string;
  updated_at: string;
}

export const DRAWING_TOOLS: { kind: DrawingKind; name: string; points: 1 | 2; hint: string }[] = [
  { kind: 'trend', name: 'Trend line', points: 2, hint: 'Click the start, then the end.' },
  { kind: 'hline', name: 'Horizontal level', points: 1, hint: 'Click the price level.' },
  { kind: 'rect', name: 'Rectangle', points: 2, hint: 'Click one corner, then the opposite one.' },
  {
    kind: 'fib',
    name: 'Fibonacci retracement',
    points: 2,
    hint: 'Click the swing start, then its end.',
  },
  { kind: 'note', name: 'Note', points: 1, hint: 'Click where the note goes.' },
];

export const DRAWING_COLORS: DrawingColor[] = [
  'accent',
  'amber',
  'blue',
  'pink',
  'green',
  'red',
  'muted',
];

/** Retracement levels, from the swing's end (0%) back to its start (100%). */
export const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];

export function fibPrices(start: number, end: number): { level: number; price: number }[] {
  return FIB_LEVELS.map((level) => ({ level, price: end - (end - start) * level }));
}

/**
 * Bar times to fractional bar positions ("logical" indexes) and back.
 * Times between bars are interpolated; times past either end are
 * extrapolated with the nearest bar spacing, so drawings can reach into
 * the future or before the loaded history.
 */
export class TimeAxis {
  constructor(private readonly times: readonly number[]) {}

  get size(): number {
    return this.times.length;
  }

  private step(at: 'start' | 'end'): number {
    const t = this.times;
    if (t.length < 2) return 86400;
    return at === 'start'
      ? (t[1] as number) - (t[0] as number)
      : (t.at(-1) as number) - (t.at(-2) as number);
  }

  toLogical(time: number): number | null {
    const t = this.times;
    if (t.length === 0) return null;
    const first = t[0] as number;
    const last = t.at(-1) as number;
    if (time <= first) return (time - first) / this.step('start');
    if (time >= last) return t.length - 1 + (time - last) / this.step('end');
    let lo = 0;
    let hi = t.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if ((t[mid] as number) <= time) lo = mid;
      else hi = mid;
    }
    const a = t[lo] as number;
    const b = t[hi] as number;
    return lo + (time - a) / (b - a);
  }

  toTime(logical: number): number | null {
    const t = this.times;
    if (t.length === 0) return null;
    const first = t[0] as number;
    const last = t.at(-1) as number;
    if (logical <= 0) return Math.round(first + logical * this.step('start'));
    if (logical >= t.length - 1)
      return Math.round(last + (logical - (t.length - 1)) * this.step('end'));
    const i = Math.floor(logical);
    const a = t[i] as number;
    const b = t[i + 1] as number;
    return Math.round(a + (logical - i) * (b - a));
  }
}

export interface Pixel {
  x: number;
  y: number;
}

function distanceToSegment(p: Pixel, a: Pixel, b: Pixel): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = dx * dx + dy * dy;
  const k =
    length === 0 ? 0 : Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / length));
  return Math.hypot(p.x - (a.x + k * dx), p.y - (a.y + k * dy));
}

/**
 * How far (in pixels) the pointer is from a drawing, given its points
 * already converted to pixels; `priceToY` places Fibonacci levels.
 */
export function distanceTo(
  kind: DrawingKind,
  points: Pixel[],
  pointer: Pixel,
  priceToY: (price: number) => number | null,
  prices: number[],
): number {
  const [a, b] = points;
  if (!a) return Infinity;
  switch (kind) {
    case 'hline':
      return Math.abs(pointer.y - a.y);
    case 'note':
      return Math.hypot(pointer.x - a.x, pointer.y - a.y);
    case 'trend':
      return b ? distanceToSegment(pointer, a, b) : Infinity;
    case 'rect': {
      if (!b) return Infinity;
      const left = Math.min(a.x, b.x);
      const right = Math.max(a.x, b.x);
      const top = Math.min(a.y, b.y);
      const bottom = Math.max(a.y, b.y);
      const inside =
        pointer.x >= left && pointer.x <= right && pointer.y >= top && pointer.y <= bottom;
      return inside
        ? 0
        : Math.hypot(
            Math.max(left - pointer.x, 0, pointer.x - right),
            Math.max(top - pointer.y, 0, pointer.y - bottom),
          );
    }
    case 'fib': {
      if (!b) return Infinity;
      const left = Math.min(a.x, b.x);
      if (pointer.x < left - 4) return Infinity;
      const [start = 0, end = 0] = prices;
      let best = Infinity;
      for (const { price } of fibPrices(start, end)) {
        const y = priceToY(price);
        if (y != null) best = Math.min(best, Math.abs(pointer.y - y));
      }
      return best;
    }
  }
}
