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

const violations: string[] = [];
let prefs: Record<string, unknown> = {};
// Kept across a reload, like the server's data.
let routes = workspaceRoutes();

async function openOnBitcoin(page: Page, fresh = true) {
  violations.length = 0;
  if (fresh) {
    routes = workspaceRoutes();
    prefs = {
      chart_type: 'candle',
      period: '1W',
      show_grid: true,
      show_ohlc: true,
      compact: false,
      risk_profile: 'balanced',
      last_instrument: BTC,
      indicators: [],
    };
  }
  page.on('console', (m) => {
    if (m.type() === 'error' && m.text().includes('Content Security Policy'))
      violations.push(m.text());
  });
  await fakeApi(page, {
    ...routes,
    'GET /preferences': () => ({ json: prefs }),
    'PUT /preferences': (body) => {
      prefs = { ...prefs, ...(body as object) };
      return { json: prefs };
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
  // Lightweight Charts drew on its canvases; TradingView is credited.
  const chart = page.getByTestId('price-chart');
  await expect(chart.locator('canvas').first()).toBeVisible();
  // The preview server sends the production CSP; nothing may break it.
  expect(violations).toEqual([]);
  await expect(page.getByRole('link', { name: 'TradingView' })).toHaveAttribute(
    'href',
    'https://www.tradingview.com/',
  );

  expect(sent).toContainEqual({ type: 'watch', ids: [BTC] });
});

test('indicators are added from the toolbar and survive a reload', async ({ page }) => {
  await openOnBitcoin(page);
  await expect(page.getByText('$70,512.25')).toBeVisible();
  const chart = page.getByTestId('price-chart');
  const panesBefore = await chart.locator('canvas').count();

  await page.getByRole('button', { name: 'Indicators' }).click();
  const menu = page.getByRole('group', { name: 'Indicators' });
  await menu.getByRole('button', { name: 'Add' }).click(); // EMA 20 is the default
  await menu.getByLabel('Indicator').selectOption('rsi');
  await menu.getByRole('button', { name: 'Add' }).click();
  await expect(menu.getByText('RSI 14', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');

  await expect(page.getByText(/^EMA 20 \d/)).toBeVisible();
  await expect(page.getByText(/^RSI 14 \d/)).toBeVisible();
  // RSI draws in a new pane, which brings its own canvases.
  await expect.poll(() => chart.locator('canvas').count()).toBeGreaterThan(panesBefore);
  await page.screenshot({ path: 'test-results/indicators.png' });

  await page.reload();
  await openOnBitcoin(page, false);
  await expect(page.getByText(/^RSI 14 \d/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Indicators' })).toContainText('2');
  expect(violations).toEqual([]);
});

test('drawings are placed on the chart, saved, and come back after a reload', async ({ page }) => {
  await openOnBitcoin(page);
  await expect(page.getByText('$70,512.25')).toBeVisible();
  const chart = page.getByTestId('price-chart');
  const box = await chart.boundingBox();
  if (!box) throw new Error('no chart');

  await page.getByRole('button', { name: 'Draw' }).click();
  await page.getByRole('button', { name: 'Trend line' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Trend line:' })).toBeVisible();
  const saved = page.waitForResponse(
    (r) => r.request().method() === 'POST' && r.url().includes('/drawings'),
  );
  await page.mouse.click(box.x + box.width * 0.3, box.y + box.height * 0.6);
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.45);
  await page.mouse.click(box.x + box.width * 0.6, box.y + box.height * 0.3);
  const body = (await saved).request().postDataJSON() as { kind: string; points: unknown[] };
  expect(body.kind).toBe('trend');
  expect(body.points).toHaveLength(2);
  await expect(page.getByRole('group', { name: 'Selected trend line' })).toBeVisible();

  await page.getByRole('button', { name: 'Horizontal level' }).click();
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.7);
  const label = page.getByLabel('Label');
  await label.fill('support');
  await label.press('Enter');
  await page.keyboard.press('Escape');
  await page.screenshot({ path: 'test-results/drawings.png' });

  const reloaded = page.waitForResponse(
    (r) => r.request().method() === 'GET' && r.url().includes('/drawings'),
  );
  await page.reload();
  await openOnBitcoin(page, false);
  expect(((await (await reloaded).json()) as unknown[]).length).toBe(2);
  await expect(page.getByText('$70,512.25')).toBeVisible();
  // Click on the saved level to select it again: it came back from the server.
  // The chart loads lazily; click until it's there to be clicked.
  await expect(async () => {
    await page.mouse.click(box.x + box.width * 0.2, box.y + box.height * 0.7);
    await expect(page.getByRole('group', { name: 'Selected horizontal level' })).toBeVisible({
      timeout: 500,
    });
  }).toPass({ timeout: 5000 });
  await expect(page.getByLabel('Label')).toHaveValue('support');
  await page.keyboard.press('Delete');
  await expect(page.getByRole('group', { name: 'Selected horizontal level' })).toBeHidden();
  expect(violations).toEqual([]);
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
