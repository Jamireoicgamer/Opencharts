// SPDX-License-Identifier: AGPL-3.0-or-later
import { expect, test } from '@playwright/test';

test('loads the app shell and reports API health', async ({ page }) => {
  await page.route('/api/health', (route) =>
    route.fulfill({ json: { status: 'ok', version: '0.1.0' } }),
  );
  await page.goto('/');
  await expect(page).toHaveTitle('OpenChart AI');
  await expect(page.getByRole('heading', { name: 'No data source connected' })).toBeVisible();
  await expect(page.getByRole('status')).toHaveText('API: ok');
});
