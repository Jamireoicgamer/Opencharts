// SPDX-License-Identifier: AGPL-3.0-or-later
import { Link, useSearchParams } from 'react-router';
import { api, type Me } from '../api';
import { AuthCard, ErrorMessage, Field, formValues, useSubmit } from '../components/Form';
import { useSession } from '../session';

export function RegisterPage() {
  const { signedIn } = useSession();
  const [params] = useSearchParams();
  const invite = params.get('invite');
  const { busy, error, run } = useSubmit(async (values: Record<string, string>) => {
    signedIn(await api<Me>('POST', '/auth/register', { ...values, invite_token: invite }));
  });

  if (!invite) {
    return (
      <AuthCard
        title="Invite needed"
        intro="Accounts on this server are created from invite links."
      >
        <Link className="button" to="/login">
          Back to sign in
        </Link>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Join OpenChart AI"
      intro="You were invited to this server. Create your account."
    >
      <form onSubmit={(e) => void run(formValues(e))}>
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
          hint="At least 12 characters."
        />
        <ErrorMessage message={error} />
        <button className="button primary" type="submit" disabled={busy}>
          {busy ? 'Creating…' : 'Create account'}
        </button>
      </form>
    </AuthCard>
  );
}
