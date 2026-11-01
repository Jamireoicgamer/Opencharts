// SPDX-License-Identifier: AGPL-3.0-or-later
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isDevelopmentLink } from './links.mjs';

test('keeps the library names PostgreSQL loads', () => {
  for (const name of [
    'native/lib/libicudata.68.dylib',
    'native/lib/libpq.5.dylib',
    'native/lib/libicudata.so.60',
    'native/lib/libpq.so.5',
  ]) {
    assert.equal(isDevelopmentLink(name), false, name);
  }
});

test('skips names only used for compiling', () => {
  for (const name of ['native/lib/libpq.so', 'native/lib/libpq.dylib', 'libicudata.dylib']) {
    assert.equal(isDevelopmentLink(name), true, name);
  }
});
