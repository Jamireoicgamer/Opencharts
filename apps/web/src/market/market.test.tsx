// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReauthProvider } from '../components/Reauth';
import { defaultPreferences, mockApi } from '../test-api';
import { charts, FakeSocket } from '../test-market';
import { Workspace } from '../workspace/Workspace';
import { advance, barStart } from './Chart';
import { stamp } from './QuoteHeader';
import { MarketStream } from './stream';
import type { History, Quote, SourceInfo } from './types';
import { sourceLabel } from './types';
import { cash, marketValue, profit } from './valuation';

const BTC = {
  id: 'CRYPTO:BTC-USD',
  symbol: 'BTC-USD',
  name: 'Bitcoin',
  exchange: 'CRYPTO',
  currency: 'USD',
  asset_class: 'crypto',
} as const;
const BAE = {
  id: 'LSE:BA.',
  symbol: 'BA.',
  name: 'BAE Systems',
  exchange: 'LSE',
  currency: 'GBX',
  asset_class: 'equity',
} as const;

const quote = (over: Partial<Quote> = {}): Quote => ({
  instrument_id: BTC.id,
  price: '70500.5',
  previous_close: '68640',
  change: '1860.5',
  change_pct: '2.71',
  currency: 'USD',
  at: new Date().toISOString(),
  source: 'coinbase',
  delay: 'realtime',
  delay_minutes: 0,
  market_state: 'open',
  ...over,
});

const hour = (h: number) => new Date(Date.UTC(2026, 9, 31, h)).toISOString();
const history = (over: Partial<History> = {}): History => ({
  instrument_id: BTC.id,
  period: '1W',
  interval: '1h',
  sources: ['coinbase'],
  stale: false,
  candles: [10, 11, 12].map((h) => ({
    t: hour(h),
    open: '70000',
    high: '70600',
    low: '69900',
    close: '70400',
    volume: '12',
  })),
  ...over,
});

afterEach(() => vi.useRealTimers());

describe('the live connection', () => {
  it('watches over the socket and re-sends after reconnecting', async () => {
    vi.useFakeTimers();
    mockApi({});
    const stream = new MarketStream();
    const stop = stream.watch([BTC.id]);
    const first = FakeSocket.last;
    first.open();
    expect(first.sent).toEqual([{ type: 'watch', ids: [BTC.id] }]);
    first.receive({ type: 'quote', ...quote() });
    expect(stream.quotes.get(BTC.id)?.price).toBe('70500.5');

    first.drop();
    expect(stream.connection).toBe('connecting');
    await vi.advanceTimersByTimeAsync(1000);
    const second = FakeSocket.last;
    expect(second).not.toBe(first);
    second.open();
    expect(second.sent).toEqual([{ type: 'watch', ids: [BTC.id] }]);

    stop();
    expect(second.sent.at(-1)).toEqual({ type: 'unwatch', ids: [BTC.id] });
    stream.close();
  });

  it('counts watchers so one leaving does not stop the other', () => {
    mockApi({});
    const stream = new MarketStream();
    FakeSocket.last.open();
    const a = stream.watch([BTC.id]);
    const b = stream.watch([BTC.id]);
    a();
    expect(FakeSocket.last.sent).toEqual([{ type: 'watch', ids: [BTC.id] }]);
    b();
    expect(FakeSocket.last.sent.at(-1)).toEqual({ type: 'unwatch', ids: [BTC.id] });
    stream.close();
  });

  it('polls when the socket keeps failing, then goes live again', async () => {
    vi.useFakeTimers();
    const api = mockApi({
      [`GET /market/quotes?ids=${encodeURIComponent(BTC.id)}`]: [
        200,
        [{ instrument_id: BTC.id, quote: quote({ price: '1' }), reason: null }],
      ],
    });
    const stream = new MarketStream();
    stream.watch([BTC.id]);
    FakeSocket.last.drop();
    await vi.advanceTimersByTimeAsync(1000);
    FakeSocket.last.drop();
    expect(stream.connection).toBe('polling');
    await vi.waitFor(() => expect(stream.quotes.get(BTC.id)?.price).toBe('1'));
    expect(api.calls.some((c) => c.path.startsWith('/market/quotes'))).toBe(true);

    await vi.advanceTimersByTimeAsync(2000);
    FakeSocket.last.open();
    expect(stream.connection).toBe('live');
    stream.close();
  });
});

describe('labels and arithmetic', () => {
  it('always says where a price came from and how fresh it is', () => {
    expect(sourceLabel(quote())).toBe('Coinbase · real-time');
    expect(sourceLabel(quote({ source: 'yahoo', delay: 'delayed', delay_minutes: null }))).toBe(
      'Yahoo Finance · delayed',
    );
    expect(sourceLabel(quote({ source: 'yahoo', delay: 'delayed', delay_minutes: 15 }))).toBe(
      'Yahoo Finance · delayed 15 min',
    );
    const yesterday = new Date(Date.now() - 86_400_000 * 2).toISOString();
    expect(stamp(yesterday)).toMatch(/\d/);
  });

  it('values pence holdings in pounds and keeps currencies apart', () => {
    expect(marketValue('120', '1986.5', 'GBX')).toBeCloseTo(2383.8);
    expect(profit('120', '1900', '1986.5', 'GBX')).toBeCloseTo(103.8);
    expect(profit('2', null, '100', 'USD')).toBeNull();
    expect(cash(2383.8, 'GBP')).toMatch(/2,383\.80/);
  });

  it('moves the last bar and only starts new ones while the market is open', () => {
    const bar = {
      time: barStart(Date.parse(hour(12)) / 1000, '1h', false),
      open: 1,
      high: 2,
      low: 0.5,
      close: 1,
    };
    const same = advance(bar as never, quote({ price: '3', at: hour(12) }), '1h', false);
    expect(same).toMatchObject({ high: 3, close: 3, open: 1 });
    const next = advance(bar as never, quote({ price: '4', at: hour(13) }), '1h', false);
    expect(next).toMatchObject({ open: 4, close: 4 });
    const closed = advance(
      bar as never,
      quote({ price: '4', at: hour(13), market_state: 'closed' }),
      '1h',
      false,
    );
    expect(closed).toBeNull();
  });
});

function signedInRoutes(extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({
    'GET /preferences': [200, { ...defaultPreferences, last_instrument: BTC.id, period: '1W' }],
    'GET /watchlist': [200, [{ ...BTC, added_at: hour(1) }]],
    'PUT /preferences': (body) => [200, { ...defaultPreferences, ...(body as object) }],
    'GET /market/candles/CRYPTO%3ABTC-USD': [200, history()],
    ...extra,
  });
}

function renderWorkspace(path = '/', role: 'owner' | 'member' = 'owner') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ReauthProvider>
        <Workspace role={role} />
      </ReauthProvider>
    </MemoryRouter>,
  );
}

describe('the chart and quote', () => {
  it('draws history, then moves with live quotes, labelled with its source', async () => {
    signedInRoutes();
    renderWorkspace();
    await waitFor(() => expect(charts).toHaveLength(1));
    const [chart] = charts;
    if (!chart) throw new Error('no chart');
    const [series] = chart.series;
    if (!series) throw new Error('no series');
    expect(chart.options).toMatchObject({ layout: { attributionLogo: true } });
    expect(series.kind).toBe('Candlestick');
    expect(series.data).toHaveLength(3);
    expect(screen.getByText('History: Coinbase')).toBeInTheDocument();

    act(() => {
      FakeSocket.last.open();
      FakeSocket.last.receive({ type: 'quote', ...quote({ at: hour(12), price: '70700' }) });
    });
    expect(await screen.findByText('$70,700')).toBeInTheDocument();
    expect(screen.getByText('+2.71%')).toHaveAttribute('data-direction', 'up');
    expect(screen.getByText(/Coinbase · real-time/)).toBeInTheDocument();
    expect(series.updates.at(-1)).toMatchObject({ close: 70700, high: 70700 });
    expect(screen.getByText('LIVE PRICES')).toBeInTheDocument();
  });

  it('explains when no source covers an instrument', async () => {
    mockApi({
      'GET /preferences': [200, { ...defaultPreferences, last_instrument: BAE.id }],
      'GET /watchlist': [200, [{ ...BAE, added_at: hour(1) }]],
      'GET /market/candles/LSE%3ABA.': [404, { detail: 'no_source' }],
    });
    renderWorkspace();
    expect(
      await screen.findByRole('heading', { name: 'No data source covers this instrument' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Settings → Data sources' })).toBeInTheDocument();
  });

  it('tells members to ask the owner, and retries after a failure', async () => {
    let calls = 0;
    signedInRoutes({
      'GET /market/candles/CRYPTO%3ABTC-USD': () => (++calls === 1 ? [503] : [200, history()]),
    });
    renderWorkspace('/', 'member');
    await userEvent.click(await screen.findByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(charts).toHaveLength(1));
  });
});

describe('prices in the panels', () => {
  it('shows watchlist prices and holding values', async () => {
    signedInRoutes({
      'GET /watchlist': [
        200,
        [
          { ...BTC, added_at: hour(1) },
          { ...BAE, added_at: hour(1) },
        ],
      ],
      'GET /positions': [
        200,
        [
          {
            id: 'p1',
            instrument: BAE,
            quantity: '120.0000000000',
            average_price: '1900.0000000000',
            account: 'isa',
            note: '',
            created_at: hour(1),
            updated_at: hour(1),
          },
        ],
      ],
    });
    renderWorkspace('/?panel=watchlist');
    await waitFor(() => expect(FakeSocket.instances.length).toBeGreaterThan(0));
    act(() => {
      FakeSocket.last.open();
      FakeSocket.last.receive({ type: 'quote', ...quote() });
      FakeSocket.last.receive({
        type: 'status',
        instrument_id: BAE.id,
        state: 'no_source',
        source: null,
      });
    });
    const list = within(await screen.findByRole('complementary', { name: 'Watchlist' }));
    expect(await list.findByText('$70,500.5')).toBeInTheDocument();
    expect(list.getByText('no source')).toBeInTheDocument();

    await userEvent.click(
      within(screen.getByRole('navigation', { name: 'Workspace' })).getByRole('button', {
        name: 'Portfolio',
      }),
    );
    const portfolio = within(await screen.findByRole('complementary', { name: 'Holdings & risk' }));
    await portfolio.findByText(/120 units/);
    expect(portfolio.getByText(/value —/)).toBeInTheDocument();
    act(() =>
      FakeSocket.last.receive({
        type: 'quote',
        ...quote({ instrument_id: BAE.id, price: '1986.5', currency: 'GBX', source: 'yahoo' }),
      }),
    );
    expect(await portfolio.findByText(/value £2,383\.80/)).toBeInTheDocument();
    expect(portfolio.getByText(/\+£103\.80\)/)).toBeInTheDocument();
    expect(portfolio.getByRole('region', { name: 'Market value by currency' })).toHaveTextContent(
      'VALUE · GBP',
    );
  });

  it('shows a toast when an alert fires', async () => {
    signedInRoutes();
    renderWorkspace();
    await waitFor(() => expect(FakeSocket.instances.length).toBeGreaterThan(0));
    act(() => {
      FakeSocket.last.open();
      FakeSocket.last.receive({
        type: 'alert',
        alert_id: 'a1',
        instrument_id: BTC.id,
        direction: 'above',
        level: '70000.0000000000',
        price: '70500.5',
        currency: 'USD',
        note: 'take profit?',
        at: hour(12),
      });
    });
    const toast = await screen.findByText(/BTC-USD rose above \$70,000 · now \$70,500\.5/);
    expect(toast.closest('[role="alert"]')).toHaveTextContent('take profit?');
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss alert' }));
    expect(screen.queryByText(/rose above/)).not.toBeInTheDocument();
  });
});

const source = (over: Partial<SourceInfo>): SourceInfo => ({
  provider: 'coinbase',
  label: 'Coinbase',
  coverage: 'Crypto',
  active: true,
  enabled: true,
  priority: 10,
  needs_terms: false,
  terms_accepted: null,
  needs_key: false,
  key_hint: null,
  ...over,
});

describe('data sources', () => {
  it('lets the owner accept Yahoo terms and save a key', async () => {
    const yahoo = source({
      provider: 'yahoo',
      label: 'Yahoo Finance',
      active: false,
      enabled: true,
      priority: 30,
      needs_terms: true,
      terms_accepted: false,
    });
    const twelve = source({
      provider: 'twelvedata',
      label: 'Twelve Data',
      active: false,
      enabled: false,
      priority: 40,
      needs_key: true,
    });
    const api = signedInRoutes({
      'GET /data-sources': [200, [source({}), yahoo, twelve]],
      'PUT /admin/data-sources/yahoo': [
        200,
        [source({}), { ...yahoo, terms_accepted: true, active: true }, twelve],
      ],
      'PUT /admin/data-sources/twelvedata': [
        200,
        [
          source({}),
          { ...yahoo, terms_accepted: true, active: true },
          { ...twelve, key_hint: '…3456' },
        ],
      ],
    });
    renderWorkspace('/?panel=settings');
    const settings = within(await screen.findByRole('complementary', { name: 'Settings' }));
    expect(await settings.findByText('Accept the terms below to use it.')).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(settings.getByRole('checkbox', { name: /I accept/ }));
    await waitFor(() => expect(settings.getAllByText('In use')).toHaveLength(2));

    await user.type(settings.getByLabelText(/Twelve Data API key/), 'td-secret-123456');
    await user.click(settings.getByRole('button', { name: 'Save key' }));
    expect(await settings.findByText(/saved, ends …3456/)).toBeInTheDocument();
    expect(settings.getByLabelText(/Twelve Data API key/)).toHaveValue('');
    const puts = api.calls.filter((c) => c.method === 'PUT' && c.path.startsWith('/admin'));
    expect(puts.map((c) => c.body)).toEqual([
      { accept_terms: true },
      { api_key: 'td-secret-123456' },
    ]);
  });

  it('shows members what is in use, without controls', async () => {
    signedInRoutes({
      'GET /data-sources': [
        200,
        [
          source({ enabled: null, priority: null }),
          source({
            provider: 'yahoo',
            label: 'Yahoo Finance',
            active: false,
            enabled: null,
            priority: null,
          }),
        ],
      ],
    });
    renderWorkspace('/?panel=settings', 'member');
    const settings = within(await screen.findByRole('complementary', { name: 'Settings' }));
    expect(await settings.findByText(/owner of this server chooses/)).toBeInTheDocument();
    expect(settings.queryByRole('checkbox', { name: /Use / })).not.toBeInTheDocument();
  });
});
