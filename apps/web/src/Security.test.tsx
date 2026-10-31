// SPDX-License-Identifier: AGPL-3.0-or-later
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { App } from './App';
import { SessionProvider } from './session';
import { health, member, mockApi, owner } from './test-api';

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SessionProvider>
        <App />
      </SessionProvider>
    </MemoryRouter>,
  );
}

const signedOut = {
  'GET /setup/status': [200, { needs_setup: false }] as [number, unknown],
  'GET /auth/me': [401, { detail: 'Not signed in' }] as [number, unknown],
  'GET /auth/providers': [200, { google: false }] as [number, unknown],
  'GET /health': health,
};

const status = {
  has_password: true,
  totp: false,
  passkeys: [],
  google_email: null,
  recovery_codes_left: 0,
  require_mfa: false,
  google_available: false,
};

describe('two-step sign-in', () => {
  it('asks for the authenticator code after the password', async () => {
    const api = mockApi({
      ...signedOut,
      'POST /auth/login': [200, { mfa_required: true, methods: ['totp', 'recovery'] }],
      'POST /auth/mfa/totp': (body) =>
        (body as { code: string }).code === '123456'
          ? [200, owner]
          : [401, { detail: 'That code is not right. Try again.' }],
    });
    renderAt('/login');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Email'), 'owner@example.com');
    await user.type(screen.getByLabelText('Password'), 'pw');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('heading', { name: 'Two-factor check' })).toBeInTheDocument();
    await user.type(screen.getByLabelText('Code'), '000000');
    await user.click(screen.getByRole('button', { name: 'Verify' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('That code is not right');

    await user.clear(screen.getByLabelText('Code'));
    await user.type(screen.getByLabelText('Code'), '123456');
    await user.click(screen.getByRole('button', { name: 'Verify' }));
    expect(
      await screen.findByRole('heading', { name: 'No data source connected' }),
    ).toBeInTheDocument();
    expect(api.calls.filter((c) => c.path === '/auth/mfa/totp')).toHaveLength(2);
  });

  it('can switch to a recovery code', async () => {
    mockApi({
      ...signedOut,
      'POST /auth/login': [200, { mfa_required: true, methods: ['totp', 'recovery'] }],
      'POST /auth/mfa/recovery': [200, owner],
    });
    renderAt('/login');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Email'), 'owner@example.com');
    await user.type(screen.getByLabelText('Password'), 'pw');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    await user.click(await screen.findByRole('button', { name: 'Use a recovery code' }));
    await user.type(screen.getByLabelText('Recovery code'), 'abcde-fghjk');
    await user.click(screen.getByRole('button', { name: 'Verify' }));
    expect(
      await screen.findByRole('heading', { name: 'No data source connected' }),
    ).toBeInTheDocument();
  });

  it('explains a Google account that is not linked', async () => {
    mockApi(signedOut);
    renderAt('/login#error=not_linked');
    expect(await screen.findByRole('alert')).toHaveTextContent("isn't linked to an account here");
  });
});

describe('security settings', () => {
  it('confirms identity when needed, then sets up the authenticator app', async () => {
    let reauthed = false;
    let enabled = false;
    mockApi({
      'GET /setup/status': [200, { needs_setup: false }],
      'GET /auth/me': [200, owner],
      'GET /health': health,
      'GET /auth/providers': [200, { google: false }],
      'GET /account/security': () => [200, { ...status, totp: enabled }],
      'POST /account/security/totp/setup': () =>
        reauthed
          ? [
              200,
              {
                secret: 'JBSWY3DPEHPK3PXP',
                uri: 'otpauth://totp/x',
                qr_svg: 'data:image/svg+xml;base64,PHN2Zy8+',
              },
            ]
          : [403, { detail: 'reauth_required' }],
      'POST /auth/reauth': () => {
        reauthed = true;
        return [204];
      },
      'POST /account/security/totp/confirm': () => {
        enabled = true;
        return [200, { recovery_codes: Array.from({ length: 10 }, (_, i) => `code${i}-xxxxx`) }];
      },
    });
    renderAt('/account/security');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Set up' }));

    // The API wanted a recent sign-in: confirm, and the setup continues.
    expect(await screen.findByRole('dialog', { name: "Confirm it's you" })).toBeInTheDocument();
    await user.type(screen.getByLabelText('Password'), 'correct horse battery');
    await user.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(await screen.findByRole('img', { name: /QR code/ })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('Code from the app'), '123456');
    await user.click(screen.getByRole('button', { name: 'Turn on' }));
    expect(await screen.findByText('Save these recovery codes now.')).toBeInTheDocument();
    expect(screen.getAllByText(/^code\d-xxxxx$/)).toHaveLength(10);
    await user.click(screen.getByRole('button', { name: "I've saved them" }));
    expect(screen.queryByText(/^code0-xxxxx$/)).not.toBeInTheDocument();
    expect(await screen.findByText('On')).toBeInTheDocument();
  });

  it('sends users who must set up two-factor to the security page', async () => {
    mockApi({
      'GET /setup/status': [200, { needs_setup: false }],
      'GET /auth/me': [200, { ...member, mfa_setup_required: true }],
      'GET /health': health,
      'GET /auth/providers': [200, { google: false }],
      'GET /account/security': [200, { ...status, require_mfa: true }],
    });
    renderAt('/account/keys');
    expect(await screen.findByText(/requires two-factor sign-in/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Sign-in and security' })).toBeInTheDocument();
  });
});
