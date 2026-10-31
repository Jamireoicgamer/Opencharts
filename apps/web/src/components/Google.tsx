// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react';
import { api } from '../api';
import { useSubmit } from '../hooks';
import { ErrorMessage } from './Form';

type Purpose = 'login' | 'link' | 'register' | 'reauth';

/** Whether this server offers Google sign-in. */
export function useGoogleAvailable(): boolean {
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    let active = true;
    api<{ google: boolean }>('GET', '/auth/providers').then(
      (p) => {
        if (active) setAvailable(p.google);
      },
      () => undefined,
    );
    return () => {
      active = false;
    };
  }, []);
  return available;
}

/** Leaves for Google; the server sends the browser back when done. */
export async function startGoogle(purpose: Purpose, inviteToken?: string): Promise<void> {
  const { url } = await api<{ url: string }>('POST', '/auth/google/start', {
    purpose,
    ...(inviteToken ? { invite_token: inviteToken } : {}),
  });
  window.location.assign(url);
}

export function GoogleButton({
  purpose,
  inviteToken,
  label = 'Continue with Google',
}: {
  purpose: Purpose;
  inviteToken?: string;
  label?: string;
}) {
  const { busy, error, run } = useSubmit(() => startGoogle(purpose, inviteToken));
  return (
    <>
      <button type="button" className="button" disabled={busy} onClick={() => void run()}>
        {label}
      </button>
      <ErrorMessage message={error} />
    </>
  );
}

const MESSAGES: Record<string, string> = {
  not_linked:
    "That Google account isn't linked to an account here. Sign in another way, then link it under Account → Security.",
  expired: 'The Google sign-in expired or was started in another browser. Try again.',
  cancelled: 'Google sign-in was cancelled.',
  google: 'Google sign-in did not work. Try again.',
  invite_invalid: 'This invite link is invalid or has expired.',
  already_registered: 'That Google account or email already has an account here. Sign in instead.',
  google_in_use: 'That Google account is linked to someone else here.',
  already_linked: 'A Google account is already linked.',
  wrong_account: 'That is not the Google account linked to you.',
  session: 'Your session changed during the Google sign-in. Try again.',
};

/** Reads `#error=…` left by the Google callback, if any. */
export function googleErrorFromHash(hash: string): string | null {
  const code = new URLSearchParams(hash.replace(/^#/, '')).get('error');
  return code ? (MESSAGES[code] ?? 'Google sign-in did not work. Try again.') : null;
}
