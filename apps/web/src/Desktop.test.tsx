// SPDX-License-Identifier: AGPL-3.0-or-later
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';
import { App } from './App';
import { SessionProvider } from './session';
import { health, mockApi, owner } from './test-api';

const TOKEN = 'ab'.repeat(32);

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SessionProvider>
        <App />
      </SessionProvider>
    </MemoryRouter>,
  );
}

function openWindow() {
  window.history.pushState(null, '', `/#desktop=${TOKEN}`);
}

afterEach(() => {
  window.sessionStorage.clear();
  window.history.pushState(null, '', '/');
});

const desktop = (needsSetup: boolean) => ({
  'GET /setup/status': [200, { needs_setup: needsSetup, desktop: true }] as [number, unknown],
  'GET /health': health,
});

describe('desktop app', () => {
  it('opens straight to the workspace on first launch, with no form', async () => {
    const api = mockApi({ ...desktop(true), 'POST /auth/desktop': [200, owner] });
    openWindow();
    renderAt('/');
    expect(
      await screen.findByRole('heading', { name: 'Choose an instrument', level: 2 }),
    ).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === '/auth/desktop')?.body).toEqual({ token: TOKEN });
    // The token leaves the address bar at once.
    expect(window.location.hash).toBe('');
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument();
  });

  it('signs in again on later launches', async () => {
    const api = mockApi({
      ...desktop(false),
      'GET /auth/me': [401, { detail: 'Not signed in' }],
      'POST /auth/desktop': [200, owner],
    });
    openWindow();
    renderAt('/');
    await screen.findByRole('heading', { name: 'Choose an instrument', level: 2 });
    expect(api.calls.filter((c) => c.path === '/auth/desktop')).toHaveLength(1);
  });

  it('keeps a signed-in session without asking again', async () => {
    const api = mockApi({ ...desktop(false), 'GET /auth/me': [200, owner] });
    openWindow();
    renderAt('/');
    await screen.findByRole('heading', { name: 'Choose an instrument', level: 2 });
    expect(api.calls.some((c) => c.path === '/auth/desktop')).toBe(false);
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument();
  });

  it('ignores a token on a server that is not the desktop app', async () => {
    const api = mockApi({
      'GET /setup/status': [200, { needs_setup: false }],
      'GET /auth/me': [401, { detail: 'Not signed in' }],
      'GET /auth/providers': [200, { google: false }],
      'GET /health': health,
    });
    openWindow();
    renderAt('/');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === '/auth/desktop')).toBe(false);
  });

  it('shows sign-in if the token is refused', async () => {
    mockApi({
      ...desktop(false),
      'GET /auth/me': [401, { detail: 'Not signed in' }],
      'GET /auth/providers': [200, { google: false }],
      'POST /auth/desktop': [403, { detail: 'This sign-in link is not valid' }],
    });
    openWindow();
    renderAt('/');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it("confirms it's you without a password", async () => {
    let confirmed = false;
    mockApi({
      ...desktop(false),
      'GET /auth/me': [200, owner],
      'GET /auth/providers': [200, { google: false }],
      'GET /account/security': [
        200,
        { has_password: false, totp: false, passkeys: [], recovery_codes_left: 0, google: null },
      ],
      'POST /account/security/totp/setup': () =>
        confirmed
          ? [
              200,
              {
                secret: 'JBSWY3DPEHPK3PXP',
                uri: 'otpauth://totp/x',
                qr_svg: 'data:image/svg+xml;base64,PHN2Zy8+',
              },
            ]
          : [403, { detail: 'reauth_required' }],
      'POST /auth/desktop': () => {
        confirmed = true;
        return [200, owner];
      },
    });
    openWindow();
    renderAt('/account/security');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Set up' }));
    expect(await screen.findByRole('img', { name: /QR code/ })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
