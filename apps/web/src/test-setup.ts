// SPDX-License-Identifier: AGPL-3.0-or-later
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';
import { charts, FakeSocket } from './test-market';

vi.mock('lightweight-charts', async () => (await import('./test-market')).chartModule);

beforeEach(() => {
  FakeSocket.instances = [];
  charts.length = 0;
  vi.stubGlobal('WebSocket', FakeSocket);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
