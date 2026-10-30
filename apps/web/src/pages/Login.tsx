// SPDX-License-Identifier: AGPL-3.0-or-later
import { api, type Me } from '../api';
import { AuthCard, ErrorMessage, Field, formValues } from '../components/Form';
import { useSubmit } from '../hooks';
import { useSession } from '../session';

export function LoginPage() {
  const { signedIn } = useSession();
  const { busy, error, run } = useSubmit(async (values: Record<string, string>) => {
    signedIn(await api<Me>('POST', '/auth/login', values));
  });

  return (
    <AuthCard title="Sign in">
      <form onSubmit={(e) => void run(formValues(e))}>
        <Field label="Email" name="email" type="email" required autoComplete="username" />
        <Field
          label="Password"
          name="password"
          type="password"
          required
          autoComplete="current-password"
        />
        <ErrorMessage message={error} />
        <button className="button primary" type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
      <p className="auth-footnote">New here? Ask the owner of this server for an invite link.</p>
    </AuthCard>
  );
}
