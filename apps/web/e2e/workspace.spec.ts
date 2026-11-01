// SPDX-License-Identifier: AGPL-3.0-or-later
import { devices, expect, test } from '@playwright/test';
import { fakeApi, workspaceRoutes } from './fake-api';

test('search, watch, write a thesis, and find it all after a reload', async ({ page }) => {
  await fakeApi(page, workspaceRoutes());
  await page.goto('/');
  await expect(page.getByRole('button', { name: /Choose an instrument/ })).toBeVisible();

  await page.keyboard.press('ControlOrMeta+k');
  await page.getByRole('combobox', { name: 'Search instruments' }).fill('rolls');
  await page.getByRole('option', { name: /Rolls-Royce/ }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Rolls-Royce Holdings');
  await page.getByRole('button', { name: 'Add to watchlist' }).click();
  await expect(page.getByRole('button', { name: 'Remove from watchlist' })).toBeVisible();

  const rail = page.getByRole('navigation', { name: 'Workspace' });
  await rail.getByRole('button', { name: 'Thesis' }).click();
  await expect(page).toHaveURL(/\?panel=thesis$/);
  const thesis = page.getByRole('complementary', { name: 'Thesis' });
  await thesis.getByLabel('The investment case').fill('Civil aerospace recovery');
  await thesis.getByLabel('Fair value (GBX)').fill('650');
  await thesis.getByRole('button', { name: 'Save version' }).click();
  await expect(thesis.getByText('Saved as a new version.')).toBeVisible();

  await page.reload();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Rolls-Royce Holdings');
  await expect(thesis.getByLabel('The investment case')).toHaveValue('Civil aerospace recovery');
  await expect(thesis.getByLabel('Fair value (GBX)')).toHaveValue('650');

  await page.getByRole('button', { name: 'Close Thesis' }).click();
  await expect(page).toHaveURL(/\/$/);
  await rail.getByRole('button', { name: 'Watchlist' }).click();
  await expect(
    page.getByRole('complementary', { name: 'Watchlist' }).getByText('Rolls-Royce Holdings'),
  ).toBeVisible();
});

test.describe('on a phone', () => {
  const { viewport, deviceScaleFactor, isMobile, hasTouch, userAgent } = devices['Pixel 7'];
  test.use({ viewport, deviceScaleFactor, isMobile, hasTouch, userAgent });

  test('the rail sits at the bottom and panels fill the screen', async ({ page }) => {
    await fakeApi(page, workspaceRoutes());
    await page.goto('/');
    const rail = page.getByRole('navigation', { name: 'Workspace' });
    await expect(rail).toBeVisible();
    const viewport = page.viewportSize();
    const box = await rail.boundingBox();
    expect(viewport && box && box.y + box.height).toBeCloseTo(viewport?.height ?? 0, -1);

    await rail.getByRole('button', { name: 'Settings' }).click();
    const settings = page.getByRole('complementary', { name: 'Settings' });
    await expect(settings).toBeVisible();
    const sheet = await settings.boundingBox();
    expect(sheet?.width).toBeCloseTo(viewport?.width ?? 0, 0);

    // Nothing is wider than the screen.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBe(0);
  });
});

test.describe('installed app', () => {
  test('links a manifest with icons', async ({ page, request }) => {
    await fakeApi(page, workspaceRoutes());
    await page.goto('/');
    const href = await page.locator('link[rel="manifest"]').getAttribute('href');
    const manifest = await (await request.get(href ?? '')).json();
    expect(manifest.display).toBe('standalone');
    for (const icon of manifest.icons as { src: string }[]) {
      expect((await request.get(icon.src)).ok()).toBe(true);
    }
  });

  test('opens the app shell offline, but never caches the API', async ({ page, context }) => {
    await fakeApi(page, workspaceRoutes());
    await page.goto('/');
    await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined));
    // Load once under the service worker so the shell and assets are cached.
    await page.reload();
    await expect(
      page.getByRole('heading', { name: 'Choose an instrument', level: 2 }),
    ).toBeVisible();

    const cached = await page.evaluate(async () => {
      const urls: string[] = [];
      for (const name of await caches.keys()) {
        const cache = await caches.open(name);
        urls.push(...(await cache.keys()).map((r) => new URL(r.url).pathname));
      }
      return urls;
    });
    expect(cached).toContain('/');
    expect(cached.some((u) => u.startsWith('/assets/'))).toBe(true);
    expect(cached.some((u) => u.startsWith('/api/'))).toBe(false);

    await context.setOffline(true);
    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await page.reload();
    await expect(page).toHaveTitle('OpenChart AI');
    await expect(page.getByText('Cannot reach the OpenChart server.')).toBeVisible();
  });
});
