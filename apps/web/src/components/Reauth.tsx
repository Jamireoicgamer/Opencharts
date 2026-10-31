// SPDX-License-Identifier: AGPL-3.0-or-later
// Sensitive changes need a recent sign-in. When the API answers
// "reauth_required", this asks the person to confirm who they are, then
// retries the change.
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import { api, ApiError, REAUTH_REQUIRED } from '../api';
import { Cancelled, useSubmit } from '../hooks';
import { passkeysSupported, signWithPasskey } from '../webauthn';
import { ErrorMessage, Field, formValues } from './Form';
import { GoogleButton, useGoogleAvailable } from './Google';

type WithReauth = <T>(action: () => Promise<T>) => Promise<T>;

const ReauthContext = createContext<WithReauth | null>(null);

interface Pending {
  resolve: () => void;
  reject: (error: Error) => void;
}

export function ReauthProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null);

  const withReauth = useCallback<WithReauth>(async (action) => {
    try {
      return await action();
    } catch (error) {
      if (!(error instanceof ApiError && error.message === REAUTH_REQUIRED)) throw error;
      await new Promise<void>((resolve, reject) => setPending({ resolve, reject }));
      return action();
    }
  }, []);

  return (
    <ReauthContext.Provider value={withReauth}>
      {children}
      {pending && (
        <ReauthDialog
          onDone={() => {
            setPending(null);
            pending.resolve();
          }}
          onCancel={() => {
            setPending(null);
            pending.reject(new Cancelled());
          }}
        />
      )}
    </ReauthContext.Provider>
  );
}

export function useReauth(): WithReauth {
  const value = useContext(ReauthContext);
  if (!value) throw new Error('useReauth must be used inside <ReauthProvider>');
  return value;
}

function ReauthDialog({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const google = useGoogleAvailable();
  const password = useSubmit(async (values: Record<string, string>) => {
    await api('POST', '/auth/reauth', values);
    onDone();
  });
  const passkey = useSubmit(async () => {
    await signWithPasskey('/auth/reauth/passkey/options', '/auth/reauth/passkey');
    onDone();
  });

  return (
    <div className="dialog-backdrop">
      <section
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="reauth-title"
        onKeyDown={(e) => {
          if (e.key === 'Escape') onCancel();
        }}
      >
        <h2 id="reauth-title">Confirm it's you</h2>
        <p className="muted">This change needs a recent sign-in.</p>
        <form onSubmit={(e) => void password.run(formValues(e))}>
          <Field
            label="Password"
            name="password"
            type="password"
            required
            autoFocus
            autoComplete="current-password"
          />
          <ErrorMessage message={password.error} />
          <button className="button primary" type="submit" disabled={password.busy}>
            Confirm
          </button>
        </form>
        <div className="dialog-alternatives">
          {passkeysSupported() && (
            <button
              type="button"
              className="button"
              disabled={passkey.busy}
              onClick={() => void passkey.run()}
            >
              Use a passkey
            </button>
          )}
          {google && <GoogleButton purpose="reauth" label="Use Google" />}
          <button type="button" className="button ghost" onClick={onCancel}>
            Cancel
          </button>
        </div>
        <ErrorMessage message={passkey.error} />
      </section>
    </div>
  );
}
