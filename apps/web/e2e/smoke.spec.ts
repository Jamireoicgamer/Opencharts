// SPDX-License-Identifier: AGPL-3.0-or-later
import { expect, test } from '@playwright/test';
import { fakeApi, owner, workspaceRoutes } from './fake-api';

test('signed-in user sees the app shell and API health', async ({ page }) => {
  await fakeApi(page, workspaceRoutes());
  await page.goto('/');
  await expect(page).toHaveTitle('OpenChart AI');
  await expect(page.getByRole('heading', { name: 'Choose an instrument', level: 2 })).toBeVisible();
  await expect(page.getByRole('status')).toHaveText('API: ok');
  await expect(page.getByRole('link', { name: 'Ada' })).toBeVisible();
});

test('first run: setup, then manage devices from the account page', async ({ page }) => {
  let setupDone = false;
  await fakeApi(page, {
    ...workspaceRoutes(),
    'GET /setup/status': () => ({ json: { needs_setup: !setupDone } }),
    'GET /auth/me': () =>
      setupDone ? { json: owner } : { status: 401, json: { detail: 'Not signed in' } },
    'POST /setup': () => {
      setupDone = true;
      return { status: 201, json: owner };
    },
    'GET /auth/sessions': [
      {
        id: 's1',
        created_at: '2026-10-30T12:00:00Z',
        last_seen_at: '2026-10-30T12:00:00Z',
        expires_at: '2026-11-29T12:00:00Z',
        user_agent: 'Mozilla/5.0 (X11; Linux x86_64) Chrome/140',
        ip: '127.0.0.1',
        current: true,
      },
    ],
  });

  await page.goto('/');
  await expect(page).toHaveURL(/\/setup$/);
  await page.getByLabel('Setup token').fill('token-from-logs');
  await page.getByLabel('Your name').fill('Ada');
  await page.getByLabel('Email').fill('owner@example.com');
  await page.getByLabel('Password').fill('correct horse battery');
  await page.getByRole('button', { name: 'Create owner account' }).click();

  await expect(page.getByRole('heading', { name: 'Choose an instrument', level: 2 })).toBeVisible();
  await page.getByRole('link', { name: 'Ada' }).click();
  await expect(page.getByRole('heading', { name: 'Signed-in devices' })).toBeVisible();
  await expect(page.getByText('This device')).toBeVisible();
});
