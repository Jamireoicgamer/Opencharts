// SPDX-License-Identifier: AGPL-3.0-or-later
// Test helper: a fake OpenChart API behind a mocked fetch.
import { vi } from 'vitest';

type Handler = (body: unknown) => [status: number, json?: unknown];

export interface FakeApi {
  calls: { method: string; path: string; body: unknown }[];
}

export const defaultPreferences = {
  chart_type: 'candle',
  period: '1M',
  show_grid: true,
  show_ohlc: false,
  compact: false,
  risk_profile: 'balanced',
  last_instrument: null,
  indicators: [],
} as const;

/** What a new account's workspace returns, so signed-in screens can load. */
const workspaceDefaults: Record<string, Handler | [number, unknown?]> = {
  'GET /preferences': [200, defaultPreferences],
  'GET /watchlist': [200, []],
};

/**
 * Routes are keyed like 'GET /auth/me'. Unknown routes answer 404. An empty
 * workspace is served unless the test gives its own routes for it.
 */
export function mockApi(given: Record<string, Handler | [number, unknown?]>): FakeApi {
  const routes = { ...workspaceDefaults, ...given };
  const fake: FakeApi = { calls: [] };
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = new URL(String(input), 'http://localhost');
    const method = init?.method ?? 'GET';
    const path = url.pathname.replace(/^\/api/, '') + url.search;
    const body: unknown = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
    fake.calls.push({ method, path, body });
    const route =
      routes[`${method} ${path}`] ??
      routes[`${method} ${url.pathname.replace(/^\/api/, '')}`] ??
      // Charts load their drawings; none unless a test says otherwise.
      (method === 'GET' && /^\/instruments\/[^/]+\/drawings$/.test(path)
        ? ([200, []] as [number, unknown])
        : undefined);
    const [status, json] =
      typeof route === 'function' ? route(body) : (route ?? [404, { detail: 'Not found' }]);
    return new Response(json === undefined ? null : JSON.stringify(json), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  });
  return fake;
}

export const owner = {
  id: 'u1',
  email: 'owner@example.com',
  display_name: 'Ada',
  role: 'owner',
} as const;
export const member = { ...owner, id: 'u2', display_name: 'Bob', role: 'member' } as const;
export const health: [number, unknown] = [200, { status: 'ok', version: '0.1.0' }];
