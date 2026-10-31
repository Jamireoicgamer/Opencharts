// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react';
import { useLocation } from 'react-router';
import { api, needsSecondFactor, type Me, type MfaRequired, type SecondFactor } from '../api';
import { AuthCard, ErrorMessage, Field, formValues } from '../components/Form';
import { GoogleButton, googleErrorFromHash, useGoogleAvailable } from '../components/Google';
import { useSubmit } from '../hooks';
import { useSession } from '../session';
import { passkeysSupported, signWithPasskey } from '../webauthn';

export function LoginPage() {
  const { signedIn } = useSession();
  const { hash } = useLocation();
  const google = useGoogleAvailable();
  const [methods, setMethods] = useState<SecondFactor[] | null>(null);

  // Back from Google with two-factor still to do.
  useEffect(() => {
    if (hash !== '#mfa') return;
    let active = true;
    api<MfaRequired>('GET', '/auth/mfa').then(
      (pending) => {
        if (active) setMethods(pending.methods);
      },
      () => undefined,
    );
    return () => {
      active = false;
    };
  }, [hash]);

  const password = useSubmit(async (values: Record<string, string>) => {
    const result = await api<Me | MfaRequired>('POST', '/auth/login', values);
    if (needsSecondFactor(result)) setMethods(result.methods);
    else signedIn(result);
  });
  const passkey = useSubmit(async () => {
    signedIn(await signWithPasskey<Me>('/auth/passkey/options', '/auth/passkey'));
  });

  if (methods) {
    return <SecondFactorStep methods={methods} onRestart={() => setMethods(null)} />;
  }

  return (
    <AuthCard title="Sign in">
      <ErrorMessage message={googleErrorFromHash(hash)} />
      <form onSubmit={(e) => void password.run(formValues(e))}>
        <Field label="Email" name="email" type="email" required autoComplete="username webauthn" />
        <Field
          label="Password"
          name="password"
          type="password"
          required
          autoComplete="current-password"
        />
        <ErrorMessage message={password.error} />
        <button className="button primary" type="submit" disabled={password.busy}>
          {password.busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
      <div className="auth-alternatives">
        {passkeysSupported() && (
          <button
            type="button"
            className="button"
            disabled={passkey.busy}
            onClick={() => void passkey.run()}
          >
            Sign in with a passkey
          </button>
        )}
        {google && <GoogleButton purpose="login" />}
      </div>
      <ErrorMessage message={passkey.error} />
      <p className="auth-footnote">New here? Ask the owner of this server for an invite link.</p>
    </AuthCard>
  );
}

function SecondFactorStep({
  methods,
  onRestart,
}: {
  methods: SecondFactor[];
  onRestart: () => void;
}) {
  const { signedIn } = useSession();
  const [useRecovery, setUseRecovery] = useState(!methods.includes('totp'));
  const code = useSubmit(async (values: Record<string, string>) => {
    const path = useRecovery ? '/auth/mfa/recovery' : '/auth/mfa/totp';
    signedIn(await api<Me>('POST', path, { code: values.code }));
  });
  const passkey = useSubmit(async () => {
    signedIn(await signWithPasskey<Me>('/auth/mfa/passkey/options', '/auth/mfa/passkey'));
  });

  return (
    <AuthCard
      title="Two-factor check"
      intro={
        useRecovery
          ? 'Enter one of your recovery codes. Each code works once.'
          : 'Enter the 6-digit code from your authenticator app.'
      }
    >
      {(methods.includes('totp') || methods.includes('recovery')) && (
        <form onSubmit={(e) => void code.run(formValues(e))} key={String(useRecovery)}>
          <Field
            label={useRecovery ? 'Recovery code' : 'Code'}
            name="code"
            required
            autoFocus
            autoComplete="one-time-code"
            inputMode={useRecovery ? 'text' : 'numeric'}
            spellCheck={false}
          />
          <ErrorMessage message={code.error} />
          <button className="button primary" type="submit" disabled={code.busy}>
            Verify
          </button>
        </form>
      )}
      <div className="auth-alternatives">
        {methods.includes('passkey') && passkeysSupported() && (
          <button
            type="button"
            className="button"
            disabled={passkey.busy}
            onClick={() => void passkey.run()}
          >
            Use a passkey
          </button>
        )}
        {methods.includes('recovery') && methods.includes('totp') && (
          <button
            type="button"
            className="button ghost"
            onClick={() => setUseRecovery(!useRecovery)}
          >
            {useRecovery ? 'Use the authenticator app' : 'Use a recovery code'}
          </button>
        )}
        <button type="button" className="button ghost" onClick={onRestart}>
          Start over
        </button>
      </div>
      <ErrorMessage message={passkey.error} />
    </AuthCard>
  );
}
