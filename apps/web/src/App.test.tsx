// SPDX-License-Identifier: AGPL-3.0-or-later
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { App } from './App';

describe('App', () => {
  it('shows the API version when the health check succeeds', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      Response.json({ status: 'ok', version: '0.1.0' }),
    );
    render(<App />);
    expect(await screen.findByText('API: ok')).toHaveAttribute('title', 'API version 0.1.0');
    expect(screen.getByRole('heading', { name: 'No data source connected' })).toBeInTheDocument();
  });

  it('reports an unreachable API', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));
    render(<App />);
    expect(await screen.findByText('API: unreachable')).toBeInTheDocument();
  });
});
