// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { api, type Me } from '../api';
import { AuthCard, ErrorMessage, Field, formValues } from '../components/Form';
import { useSubmit } from '../hooks';
import { useSession } from '../session';

/**
 * The desktop app opens /setup#token=… so its owner never has to find a
 * log. The token is read once and removed from the address bar and history.
 */
function takeTokenFromUrl(): string | null {
  const token = new URLSearchParams(window.location.hash.slice(1)).get('token');
  if (token) {
    window.history.replaceState(window.history.state, '', window.location.pathname);
  }
  return token;
}

export function SetupPage() {
  const { signedIn } = useSession();
  const [given] = useState(takeTokenFromUrl);
  const { busy, error, run } = useSubmit(async (values: Record<string, string>) => {
    const user = await api<Me>('POST', '/setup', values);
    signedIn(user);
  });

  return (
    <AuthCard
      title="Create the owner account"
      intro={
        given ? (
          'Choose the name, email and password you’ll sign in with on this computer.'
        ) : (
          <>
            This server has no accounts yet. Enter the setup token printed in the server logs (
            <code>docker compose logs api</code>) to become its owner.
          </>
        )
      }
    >
      <form onSubmit={(e) => void run(formValues(e))}>
        {given ? (
          <input type="hidden" name="setup_token" value={given} />
        ) : (
          <Field
            label="Setup token"
            name="setup_token"
            required
            autoComplete="off"
            spellCheck={false}
          />
        )}
        <Field label="Your name" name="display_name" required maxLength={100} autoComplete="name" />
        <Field label="Email" name="email" type="email" required autoComplete="email" />
        <Field
          label="Password"
          name="password"
          type="password"
          required
          minLength={12}
          maxLength={256}
          autoComplete="new-password"
          hint="At least 12 characters. A passphrase works well."
        />
        <ErrorMessage message={error} />
        <button className="button primary" type="submit" disabled={busy}>
          {busy ? 'Creating…' : 'Create owner account'}
        </button>
      </form>
    </AuthCard>
  );
}
