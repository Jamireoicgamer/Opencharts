// SPDX-License-Identifier: AGPL-3.0-or-later
// The desktop app signs in without a password. Its shell opens the window at
// /#desktop=<token>, a random token made fresh on every launch and known
// only to the local API. The fragment never leaves the window, and the token
// is kept in sessionStorage, which belongs to this window alone and is gone
// when it closes.
import { api, type Me } from './api';

const KEY = 'openchart.desktop';

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** Move a token from the address bar into this window's storage. */
export function takeDesktopToken(): void {
  const match = /(?:^#|&)desktop=([0-9a-f]{64})(?:&|$)/.exec(window.location.hash);
  if (!match?.[1]) return;
  storage()?.setItem(KEY, match[1]);
  window.history.replaceState(
    window.history.state,
    '',
    window.location.pathname + window.location.search,
  );
}

export function desktopToken(): string | null {
  return storage()?.getItem(KEY) ?? null;
}

/** Sign in as the owner, or confirm "it's you" when already signed in. */
export function desktopSignIn(token: string): Promise<Me> {
  return api<Me>('POST', '/auth/desktop', { token });
}
