// SPDX-License-Identifier: AGPL-3.0-or-later
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
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

const signedIn = (user: typeof owner | typeof member) => ({
  'GET /setup/status': [200, { needs_setup: false }] as [number, unknown],
  'GET /auth/me': [200, user] as [number, unknown],
  'GET /health': health,
});

describe('routing and sign-in', () => {
  it('sends a fresh server to owner setup', async () => {
    mockApi({ 'GET /setup/status': [200, { needs_setup: true }] });
    renderAt('/');
    expect(
      await screen.findByRole('heading', { name: 'Create the owner account' }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Setup token')).toBeInTheDocument();
  });

  it('creates the owner and lands on the home screen', async () => {
    const api = mockApi({
      'GET /setup/status': [200, { needs_setup: true }],
      'POST /setup': [201, owner],
      'GET /health': health,
    });
    renderAt('/setup');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Setup token'), 'tok');
    await user.type(screen.getByLabelText('Your name'), 'Ada');
    await user.type(screen.getByLabelText('Email'), 'owner@example.com');
    await user.type(screen.getByLabelText('Password'), 'correct horse battery');
    await user.click(screen.getByRole('button', { name: 'Create owner account' }));
    expect(
      await screen.findByRole('heading', { name: 'Choose an instrument', level: 2 }),
    ).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === '/setup')?.body).toEqual({
      setup_token: 'tok',
      display_name: 'Ada',
      email: 'owner@example.com',
      password: 'correct horse battery',
    });
  });

  it('takes the desktop app’s setup token from the URL and removes it', async () => {
    const api = mockApi({
      'GET /setup/status': [200, { needs_setup: true }],
      'POST /setup': [201, owner],
      'GET /health': health,
    });
    window.history.pushState(null, '', '/setup#token=desktop-token-123');
    renderAt('/setup');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Your name'), 'Ada');
    expect(screen.queryByLabelText('Setup token')).not.toBeInTheDocument();
    expect(window.location.hash).toBe('');
    await user.type(screen.getByLabelText('Email'), 'owner@example.com');
    await user.type(screen.getByLabelText('Password'), 'correct horse battery');
    await user.click(screen.getByRole('button', { name: 'Create owner account' }));
    await screen.findByRole('heading', { name: 'Choose an instrument', level: 2 });
    expect(api.calls.find((c) => c.path === '/setup')?.body).toMatchObject({
      setup_token: 'desktop-token-123',
    });
    window.history.pushState(null, '', '/');
  });

  it('redirects signed-out visitors to sign in, then back', async () => {
    mockApi({
      'GET /setup/status': [200, { needs_setup: false }],
      'GET /auth/me': [401, { detail: 'Not signed in' }],
      'POST /auth/login': [200, owner],
      'GET /health': health,
      'GET /auth/sessions': [200, []],
    });
    renderAt('/account/sessions');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Email'), 'owner@example.com');
    await user.type(screen.getByLabelText('Password'), 'pw');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'Signed-in devices' })).toBeInTheDocument();
  });

  it('shows the server error when sign-in fails', async () => {
    mockApi({
      'GET /setup/status': [200, { needs_setup: false }],
      'GET /auth/me': [401, { detail: 'Not signed in' }],
      'POST /auth/login': [401, { detail: 'Invalid email or password' }],
    });
    renderAt('/login');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Email'), 'owner@example.com');
    await user.type(screen.getByLabelText('Password'), 'wrong');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password');
  });

  it('explains that registration needs an invite link', async () => {
    mockApi({
      'GET /setup/status': [200, { needs_setup: false }],
      'GET /auth/me': [401, { detail: 'Not signed in' }],
    });
    renderAt('/register');
    expect(await screen.findByRole('heading', { name: 'Invite needed' })).toBeInTheDocument();
  });
});

describe('account', () => {
  it('only shows the Invites tab to owners and admins', async () => {
    mockApi({ ...signedIn(member), 'GET /auth/sessions': [200, []] });
    renderAt('/account');
    const tabs = await screen.findByRole('navigation', { name: 'Account sections' });
    expect(within(tabs).queryByText('Invites')).not.toBeInTheDocument();
    expect(within(tabs).getByText('API keys')).toBeInTheDocument();
  });

  it('saves an API key without keeping or showing its value', async () => {
    let saved = false;
    const api = mockApi({
      ...signedIn(owner),
      'GET /secrets': () => [
        200,
        saved
          ? [
              {
                name: 'finnhub',
                provider: 'Finnhub',
                hint: '…cdef',
                created_at: '2026-10-30T12:00:00Z',
                updated_at: '2026-10-30T12:00:00Z',
              },
            ]
          : [],
      ],
      'PUT /secrets/finnhub': () => {
        saved = true;
        return [204];
      },
    });
    renderAt('/account/keys');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Name'), 'finnhub');
    await user.type(screen.getByLabelText('Provider (optional)'), 'Finnhub');
    await user.type(screen.getByLabelText('Key'), 'sk-live-0123456789abcdef');
    await user.click(screen.getByRole('button', { name: 'Save key' }));

    expect(await screen.findByText(/ends …cdef/)).toBeInTheDocument();
    expect(screen.getByLabelText('Key')).toHaveValue('');
    expect(document.body.textContent).not.toContain('sk-live-0123456789abcdef');
    expect(api.calls.find((c) => c.method === 'PUT')?.body).toEqual({
      value: 'sk-live-0123456789abcdef',
      provider: 'Finnhub',
    });
  });

  it('signs out other devices', async () => {
    let sessions = [
      {
        id: 's1',
        created_at: '2026-10-30T12:00:00Z',
        last_seen_at: '2026-10-30T12:00:00Z',
        expires_at: '2026-11-29T12:00:00Z',
        user_agent: 'Mozilla/5.0 (X11; Linux x86_64) Chrome/140',
        ip: '10.0.0.2',
        current: true,
      },
      {
        id: 's2',
        created_at: '2026-10-29T12:00:00Z',
        last_seen_at: '2026-10-29T12:00:00Z',
        expires_at: '2026-11-28T12:00:00Z',
        user_agent: 'Mozilla/5.0 (iPhone) Safari/604',
        ip: '10.0.0.3',
        current: false,
      },
    ];
    mockApi({
      ...signedIn(owner),
      'GET /auth/sessions': () => [200, sessions],
      'POST /auth/sessions/revoke-others': () => {
        sessions = sessions.filter((s) => s.current);
        return [200, { revoked: 1 }];
      },
    });
    renderAt('/account/sessions');
    expect(await screen.findByText('Chrome on Linux')).toBeInTheDocument();
    expect(screen.getByText('Safari on iPhone')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Sign out other devices' }));
    await screen.findByText('Chrome on Linux');
    expect(screen.queryByText('Safari on iPhone')).not.toBeInTheDocument();
  });
});

describe('security audit fixes', () => {
  it('reads the invite token from the URL fragment and sends it in the request body', async () => {
    const api = mockApi({
      'GET /setup/status': [200, { needs_setup: false }],
      'GET /auth/me': [401, { detail: 'Not signed in' }],
      'POST /auth/register': [201, member],
      'GET /health': health,
    });
    renderAt('/register#invite=tok-123');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Your name'), 'Bob');
    await user.type(screen.getByLabelText('Email'), 'bob@example.com');
    await user.type(screen.getByLabelText('Password'), 'another long password');
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    await screen.findByRole('heading', { name: 'Choose an instrument', level: 2 });
    expect(api.calls.find((c) => c.path === '/auth/register')?.body).toMatchObject({
      invite_token: 'tok-123',
    });
  });

  it('creates invite links with the token in the fragment, not the query', async () => {
    mockApi({
      ...signedIn(owner),
      'GET /invites': [200, []],
      'POST /invites': [
        201,
        {
          id: 'i1',
          email: null,
          role: 'member',
          created_at: '2026-10-30T12:00:00Z',
          expires_at: '2026-11-02T12:00:00Z',
          used_at: null,
          token: 'secret-invite-token',
        },
      ],
    });
    renderAt('/account/invites');
    await userEvent
      .setup()
      .click(await screen.findByRole('button', { name: 'Create invite link' }));
    const link = await screen.findByText(/register#invite=secret-invite-token$/);
    expect(link.textContent).not.toContain('?invite=');
  });

  it('returns to sign-in when the session ends elsewhere', async () => {
    mockApi({
      ...signedIn(owner),
      'GET /auth/sessions': [401, { detail: 'Session expired or signed out' }],
    });
    renderAt('/account/sessions');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('shows a readable error when the proxy answers with a non-JSON page', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const path = new URL(String(input), 'http://localhost').pathname;
      if (path === '/api/setup/status') return Response.json({ needs_setup: false });
      if (path === '/api/auth/me')
        return Response.json({ detail: 'Not signed in' }, { status: 401 });
      return new Response('<html>429 Too Many Requests</html>', { status: 429 });
    });
    renderAt('/login');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Email'), 'owner@example.com');
    await user.type(screen.getByLabelText('Password'), 'pw');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Too many attempts. Try again later.',
    );
  });
});
