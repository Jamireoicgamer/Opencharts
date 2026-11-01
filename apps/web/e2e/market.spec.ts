// SPDX-License-Identifier: AGPL-3.0-or-later
import { expect, test, type Page } from '@playwright/test';
import { fakeApi, workspaceRoutes } from './fake-api';

const BTC = 'CRYPTO:BTC-USD';

/** Hourly bars ending now (made up for the test; the app never invents prices). */
function candles(count: number) {
  const now = Math.floor(Date.now() / 3_600_000) * 3_600_000;
  return Array.from({ length: count }, (_, i) => {
    const base = 70_000 + Math.sin(i / 5) * 800;
    return {
      t: new Date(now - (count - 1 - i) * 3_600_000).toISOString(),
      open: String(base),
      high: String(base + 300),
      low: String(base - 300),
      close: String(base + 100),
      volume: '10',
    };
  });
}

async function openOnBitcoin(page: Page) {
  const routes = workspaceRoutes();
  await fakeApi(page, {
    ...routes,
    'GET /preferences': {
      chart_type: 'candle',
      period: '1W',
      show_grid: true,
      show_ohlc: true,
      compact: false,
      risk_profile: 'balanced',
      last_instrument: BTC,
    },
    'GET /market/candles/*': {
      instrument_id: BTC,
      period: '1W',
      interval: '1h',
      candles: candles(168),
      sources: ['coinbase'],
      stale: false,
    },
  });
  const sent: unknown[] = [];
  await page.routeWebSocket('**/api/market/stream', (ws) => {
    ws.onMessage((message) => {
      const command = JSON.parse(String(message));
      sent.push(command);
      if (command.type !== 'watch') return;
      ws.send(JSON.stringify({ type: 'watching', ids: command.ids }));
      ws.send(
        JSON.stringify({
          type: 'quote',
          instrument_id: BTC,
          price: '70512.25',
          previous_close: '68640',
          change: '1872.25',
          change_pct: '2.73',
          currency: 'USD',
          at: new Date().toISOString(),
          source: 'coinbase',
          delay: 'realtime',
          delay_minutes: 0,
          market_state: 'open',
        }),
      );
    });
  });
  await page.goto('/');
  return sent;
}

test('a live chart with a labelled price', async ({ page }) => {
  const sent = await openOnBitcoin(page);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Bitcoin');
  await expect(page.getByText('$70,512.25')).toBeVisible();
  await expect(page.getByText(/Coinbase · real-time/)).toBeVisible();
  await expect(page.getByText('LIVE PRICES')).toBeVisible();
  await expect(page.getByText('History: Coinbase')).toBeVisible();
  // Lightweight Charts drew on its canvases, with TradingView's attribution.
  const chart = page.getByTestId('price-chart');
  await expect(chart.locator('canvas').first()).toBeVisible();
  await expect(chart.locator('a[href*="tradingview.com"]')).toHaveCount(1);
  expect(sent).toContainEqual({ type: 'watch', ids: [BTC] });
});

test.describe('on a phone', () => {
  test.use({ viewport: { width: 412, height: 915 }, isMobile: true, hasTouch: true });

  test('the price and chart fit the screen', async ({ page }) => {
    await openOnBitcoin(page);
    await expect(page.getByText('$70,512.25')).toBeVisible();
    const box = await page.getByTestId('price-chart').boundingBox();
    expect(box?.width).toBeGreaterThan(300);
    expect(box?.height).toBeGreaterThan(200);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBe(0);
  });
});
