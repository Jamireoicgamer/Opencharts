// SPDX-License-Identifier: AGPL-3.0-or-later
// The preview server's CSP must stay identical to production's, or browser
// tests stop catching CSP breakage.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, it } from 'vitest';

it('the preview server uses the production Content-Security-Policy', () => {
  const nginx = readFileSync(resolve(__dirname, '../../../deploy/nginx.conf'), 'utf8');
  const vite = readFileSync(resolve(__dirname, '../vite.config.ts'), 'utf8');
  const production = /Content-Security-Policy "([^"]+)"/.exec(nginx)?.[1];
  const preview = /PRODUCTION_CSP =\s*"([^"]+)"/.exec(vite)?.[1];
  expect(production).toBeTruthy();
  expect(preview).toBe(production);
});
