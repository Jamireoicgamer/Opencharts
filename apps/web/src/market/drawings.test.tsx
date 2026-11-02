// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { ReauthProvider } from '../components/Reauth';
import { defaultPreferences, mockApi } from '../test-api';
import { charts } from '../test-market';
import { Workspace } from '../workspace/Workspace';
import { distanceTo, fibPrices, TimeAxis, type Drawing } from './drawings';

describe('drawing geometry', () => {
  const axis = new TimeAxis([100, 200, 300, 500]);

  it('maps times to bar positions and back, beyond either end too', () => {
    expect(axis.toLogical(100)).toBe(0);
    expect(axis.toLogical(150)).toBe(0.5);
    expect(axis.toLogical(400)).toBe(2.5); // the gap 300→500 is one bar
    expect(axis.toLogical(900)).toBe(5); // past the end, at the last spacing (200)
    expect(axis.toLogical(0)).toBe(-1);
    for (const t of [0, 100, 150, 400, 500, 900]) {
      expect(axis.toTime(axis.toLogical(t) ?? NaN)).toBe(t);
    }
    expect(new TimeAxis([]).toLogical(5)).toBeNull();
  });

  it('places Fibonacci levels from the swing end back to its start', () => {
    const levels = fibPrices(100, 200).map((l) => [l.level, Number(l.price.toFixed(1))]);
    expect(levels).toEqual([
      [0, 200],
      [0.236, 176.4],
      [0.382, 161.8],
      [0.5, 150],
      [0.618, 138.2],
      [0.786, 121.4],
      [1, 100],
    ]);
  });

  it('measures how close the pointer is to each kind of shape', () => {
    const a = { x: 0, y: 0 };
    const b = { x: 100, y: 100 };
    const none = () => null;
    expect(distanceTo('trend', [a, b], { x: 50, y: 50 }, none, [])).toBe(0);
    expect(distanceTo('trend', [a, b], { x: 200, y: 200 }, none, [])).toBeCloseTo(141.42, 1);
    expect(distanceTo('hline', [a], { x: 999, y: 4 }, none, [])).toBe(4);
    expect(distanceTo('rect', [a, b], { x: 50, y: 50 }, none, [])).toBe(0);
    expect(distanceTo('rect', [a, b], { x: 110, y: 50 }, none, [])).toBe(10);
    expect(distanceTo('note', [a], { x: 3, y: 4 }, none, [])).toBe(5);
    // Fibonacci: the nearest level line to the right of the swing start.
    const y = (price: number) => 1000 - price;
    expect(distanceTo('fib', [a, b], { x: 300, y: 1000 - 150 - 2 }, y, [100, 200])).toBe(2);
    expect(distanceTo('fib', [a, b], { x: -50, y: 850 }, y, [100, 200])).toBe(Infinity);
  });
});

const BTC = {
  id: 'CRYPTO:BTC-USD',
  symbol: 'BTC-USD',
  name: 'Bitcoin',
  exchange: 'CRYPTO',
  currency: 'USD',
  asset_class: 'crypto',
} as const;
const hour = (h: number) => Date.UTC(2026, 9, 31, h) / 1000;
const candles = [10, 11, 12].map((h) => ({
  t: new Date(hour(h) * 1000).toISOString(),
  open: '70000',
  high: '70600',
  low: '69900',
  close: '70400',
  volume: '12',
}));
const DRAWINGS = '/instruments/CRYPTO%3ABTC-USD/drawings';

function pointer(type: string, element: Element, x: number, y: number) {
  // jsdom has no PointerEvent; a MouseEvent with the same fields will do.
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y });
  Object.assign(event, { pointerId: 1, pointerType: 'mouse' });
  act(() => {
    element.dispatchEvent(event);
  });
}

function setup(saved: Drawing[] = []) {
  let drawings = [...saved];
  let next = 1;
  const api = mockApi({
    'GET /preferences': [200, { ...defaultPreferences, last_instrument: BTC.id, period: '1W' }],
    'GET /watchlist': [200, [{ ...BTC, added_at: new Date().toISOString() }]],
    'GET /market/candles/CRYPTO%3ABTC-USD': [
      200,
      {
        instrument_id: BTC.id,
        period: '1W',
        interval: '1h',
        candles,
        sources: ['coinbase'],
        stale: false,
      },
    ],
    [`GET ${DRAWINGS}`]: () => [200, drawings],
    [`POST ${DRAWINGS}`]: (body) => {
      const created = {
        ...(body as object),
        id: `d${next++}`,
        instrument_id: BTC.id,
        created_at: '',
        updated_at: '',
      } as Drawing;
      drawings = [...drawings, created];
      return [201, created];
    },
    [`DELETE ${DRAWINGS}/d1`]: () => {
      drawings = drawings.filter((d) => d.id !== 'd1');
      return [204];
    },
  });
  render(
    <MemoryRouter>
      <ReauthProvider>
        <Workspace role="owner" />
      </ReauthProvider>
    </MemoryRouter>,
  );
  return api;
}

describe('drawing on the chart', () => {
  it('places a trend line with two clicks, then selects and deletes it', async () => {
    const api = setup();
    await waitFor(() => expect(charts).toHaveLength(1));
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Draw' }));
    await user.click(screen.getByRole('button', { name: 'Trend line' }));
    expect(screen.getByRole('status')).toHaveTextContent('Click the start, then the end.');
    // The chart doesn't pan while drawing.
    expect(charts[0]?.applied.at(-1)).toEqual({ handleScroll: false, handleScale: false });

    const canvas = screen.getByTestId('price-chart');
    // Mock scales: x = 10 px per bar, y = 1000 - price / 100.
    pointer('pointerdown', canvas, 0, 300);
    pointer('pointermove', canvas, 15, 295);
    pointer('pointerdown', canvas, 20, 290);
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === 'POST')?.body).toEqual({
        kind: 'trend',
        points: [
          { t: hour(10), price: 70000 },
          { t: hour(12), price: 71000 },
        ],
        color: 'accent',
        text: '',
      }),
    );
    // The new line is selected, with its own small toolbar.
    const selected = within(await screen.findByRole('group', { name: 'Selected trend line' }));
    await user.click(selected.getByRole('radio', { name: 'blue' }));
    expect(api.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ color: 'blue' });

    await user.keyboard('{Delete}');
    await waitFor(() => expect(api.calls.some((c) => c.method === 'DELETE')).toBe(true));
    expect(screen.queryByRole('group', { name: 'Selected trend line' })).not.toBeInTheDocument();
  });

  it('selects a saved drawing by clicking it, and Escape lets go', async () => {
    setup([
      {
        id: 'd1',
        instrument_id: BTC.id,
        kind: 'hline',
        points: [{ t: hour(11), price: 69000 }],
        color: 'amber',
        text: 'support',
        created_at: '',
        updated_at: '',
      },
    ]);
    await waitFor(() => expect(charts).toHaveLength(1));
    const canvas = screen.getByTestId('price-chart');
    // The level is at y = 1000 - 690 = 310; a click 3 px away selects it.
    await waitFor(() => {
      pointer('pointerdown', canvas, 400, 313);
      pointer('pointerup', canvas, 400, 313);
      expect(screen.getByRole('group', { name: 'Selected horizontal level' })).toBeInTheDocument();
    });
    expect(screen.getByLabelText('Label')).toHaveValue('support');
    await userEvent.keyboard('{Escape}');
    expect(
      screen.queryByRole('group', { name: 'Selected horizontal level' }),
    ).not.toBeInTheDocument();
  });
});
