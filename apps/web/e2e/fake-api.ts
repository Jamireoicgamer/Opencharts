// SPDX-License-Identifier: AGPL-3.0-or-later
// A fake OpenChart API for browser tests. Requests to /api/** are answered
// here; the workspace part keeps state, so reloading the page shows what was
// saved, as the real server would.
import type { Page, Route } from '@playwright/test';

type Fulfill = Parameters<Route['fulfill']>[0];
type Handler = (body: unknown, url: URL) => Fulfill;
/** A JSON body to return, or a function that builds the response. */
type Answer = Handler | object;

export const owner = { id: 'u1', email: 'owner@example.com', display_name: 'Ada', role: 'owner' };

const CATALOGUE = [
  ['LSE:BA.', 'BA.', 'BAE Systems', 'LSE', 'GBX', 'equity'],
  ['LSE:RR.', 'RR.', 'Rolls-Royce Holdings', 'LSE', 'GBX', 'equity'],
  ['NASDAQ:NVDA', 'NVDA', 'NVIDIA', 'NASDAQ', 'USD', 'equity'],
  ['CRYPTO:BTC-USD', 'BTC-USD', 'Bitcoin', 'CRYPTO', 'USD', 'crypto'],
].map(([id, symbol, name, exchange, currency, asset_class]) => ({
  id,
  symbol,
  name,
  exchange,
  currency,
  asset_class,
}));

const at = () => new Date().toISOString();
const dec = (v: unknown) => (v == null || v === '' ? null : `${Number(v).toFixed(10)}`);

/** Routes for a signed-in owner with an empty workspace that remembers changes. */
export function workspaceRoutes(): Record<string, Answer> {
  let prefs: Record<string, unknown> = {
    chart_type: 'candle',
    period: '1M',
    show_grid: true,
    show_ohlc: false,
    compact: false,
    risk_profile: 'balanced',
    last_instrument: null,
    indicators: [],
  };
  let watchlist: string[] = [];
  const theses: Record<string, Record<string, unknown>[]> = {};
  let drawings: Record<string, unknown>[] = [];
  let nextDrawing = 1;
  const drawingId = (url: URL) => url.pathname.split('/')[5] ?? '';
  const find = (id: string) => CATALOGUE.find((i) => i.id === id);
  const watch = () => watchlist.map((id) => ({ ...find(id), added_at: at() }));
  const idFrom = (url: URL) => decodeURIComponent(url.pathname.split('/')[3] ?? '');

  return {
    'GET /health': { status: 'ok', version: '0.1.0' },
    'GET /setup/status': { needs_setup: false },
    'GET /auth/me': owner,
    'GET /preferences': () => ({ json: prefs }),
    'PUT /preferences': (body) => {
      prefs = { ...prefs, ...(body as object) };
      return { json: prefs };
    },
    'GET /watchlist': () => ({ json: watch() }),
    'POST /watchlist': (body) => {
      const id = (body as { instrument_id: string }).instrument_id;
      if (!watchlist.includes(id)) watchlist = [...watchlist, id];
      return { status: 201, json: watch() };
    },
    'GET /instruments': (_body, url) => {
      const q = (url.searchParams.get('q') ?? '').toLowerCase();
      return {
        json: CATALOGUE.filter((i) => `${i.symbol} ${i.name}`.toLowerCase().includes(q)),
      };
    },
    'GET /instruments/*': (_body, url) => ({ json: find(idFrom(url)) }),
    'GET /instruments/*/drawings': (_body, url) => ({
      json: drawings.filter((d) => d.instrument_id === idFrom(url)),
    }),
    'POST /instruments/*/drawings': (body, url) => {
      const created = {
        ...(body as object),
        id: `d${nextDrawing++}`,
        instrument_id: idFrom(url),
        created_at: at(),
        updated_at: at(),
      };
      drawings = [...drawings, created];
      return { status: 201, json: created };
    },
    'PATCH /instruments/*/drawings/*': (body, url) => {
      drawings = drawings.map((d) =>
        d.id === drawingId(url) ? { ...d, ...(body as object), updated_at: at() } : d,
      );
      return { json: drawings.find((d) => d.id === drawingId(url)) };
    },
    'DELETE /instruments/*/drawings/*': (_body, url) => {
      drawings = drawings.filter((d) => d.id !== drawingId(url));
      return { status: 204 };
    },
    'GET /instruments/*/thesis': (_body, url) => {
      const history = theses[idFrom(url)] ?? [];
      return { json: { current: history[0] ?? null, history } };
    },
    'POST /instruments/*/thesis': (body, url) => {
      const input = body as Record<string, unknown>;
      const version = {
        ...input,
        fair_value: dec(input.fair_value),
        entry_price: dec(input.entry_price),
        id: crypto.randomUUID(),
        created_at: at(),
      };
      const id = idFrom(url);
      theses[id] = [version, ...(theses[id] ?? [])];
      return { status: 201, json: version };
    },
  };
}

/** Answer /api/** from `routes`. Keys look like 'GET /watchlist'; `*` matches one segment. */
export async function fakeApi(page: Page, routes: Record<string, Answer>) {
  const patterns = Object.entries(routes).map(([key, answer]) => {
    const [method, path] = key.split(' ') as [string, string];
    const regex = new RegExp(`^${path.replace(/[.]/g, '\\.').replace(/\*/g, '[^/]+')}$`);
    return { method, regex, answer };
  });
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, '');
    const match = patterns.find((p) => p.method === request.method() && p.regex.test(path));
    if (!match) return route.fulfill({ status: 404, json: { detail: 'Not found' } });
    if (typeof match.answer === 'function') {
      const body: unknown = request.postData() ? request.postDataJSON() : undefined;
      return route.fulfill((match.answer as Handler)(body, url));
    }
    return route.fulfill({ json: match.answer });
  });
}
