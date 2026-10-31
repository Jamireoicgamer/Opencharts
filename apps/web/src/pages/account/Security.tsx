// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useState } from 'react';
import { useLocation } from 'react-router';
import { api, type Me, type RecoveryCodes, type SecurityStatus, type TotpSetup } from '../../api';
import { ErrorMessage, Field, formValues } from '../../components/Form';
import { googleErrorFromHash, startGoogle } from '../../components/Google';
import { useReauth } from '../../components/Reauth';
import { when } from '../../format';
import { useLoad, useSubmit } from '../../hooks';
import { useSession } from '../../session';
import { createPasskey, passkeysSupported } from '../../webauthn';

export function Security({ user }: { user: Me }) {
  const load = useCallback(() => api<SecurityStatus>('GET', '/account/security'), []);
  const { data, error, reload } = useLoad(load);
  const { refresh } = useSession();
  const [codes, setCodes] = useState<string[] | null>(null);
  const { hash } = useLocation();

  // After a change that may satisfy (or lift) the owner's two-factor rule.
  const changed = (newCodes?: string[] | null) => {
    if (newCodes) setCodes(newCodes);
    reload();
    void refresh();
  };

  return (
    <section aria-labelledby="security-title">
      <div className="section-head">
        <h2 id="security-title">Sign-in and security</h2>
      </div>
      {user.mfa_setup_required && (
        <p className="notice" role="alert">
          The owner of this server requires two-factor sign-in. Set up an authenticator app or a
          passkey to continue.
        </p>
      )}
      {hash.includes('google=linked') && (
        <p className="notice" role="status">
          Google account linked.
        </p>
      )}
      <ErrorMessage message={error ?? googleErrorFromHash(hash)} />
      {codes && <RecoveryCodesPanel codes={codes} onDone={() => setCodes(null)} />}
      {data && (
        <>
          <Passkeys status={data} onChange={changed} />
          <Authenticator status={data} email={user.email} onChange={changed} />
          <Recovery status={data} onChange={changed} />
          <PasswordSection status={data} onChange={changed} />
          {data.google_available && <GoogleSection status={data} onChange={changed} />}
          {user.role === 'owner' && <RequireMfa status={data} onChange={changed} />}
        </>
      )}
    </section>
  );
}

type OnChange = (codes?: string[] | null) => void;

function Passkeys({ status, onChange }: { status: SecurityStatus; onChange: OnChange }) {
  const withReauth = useReauth();
  const add = useSubmit(async (values: Record<string, string>) => {
    const added = await withReauth(() =>
      createPasskey<RecoveryCodes>(values.name?.trim() || 'Passkey'),
    );
    onChange(added.recovery_codes);
  });
  const remove = useSubmit(async (id: string) => {
    await withReauth(() => api('DELETE', `/account/security/passkeys/${id}`));
    onChange();
  });

  return (
    <div className="security-block">
      <h3>Passkeys</h3>
      <p className="muted">
        Sign in with your fingerprint, face, screen lock or a security key, with no password to
        type. A passkey also counts as a second factor.
      </p>
      <ul className="rows">
        {status.passkeys.length === 0 && <li className="row muted">No passkeys yet.</li>}
        {status.passkeys.map((p) => (
          <li key={p.id} className="row">
            <div>
              <strong>{p.name}</strong>
              {p.backed_up && <span className="pill">synced</span>}
              <small>
                added {when(p.created_at)}
                {p.last_used_at ? ` · last used ${when(p.last_used_at)}` : ''}
              </small>
            </div>
            <button type="button" className="button ghost" onClick={() => void remove.run(p.id)}>
              Remove
            </button>
          </li>
        ))}
      </ul>
      <ErrorMessage message={remove.error} />
      {passkeysSupported() ? (
        <form className="inline-form" onSubmit={(e) => void add.run(formValues(e))}>
          <Field label="Name" name="name" maxLength={64} placeholder="e.g. Phone, Work laptop" />
          <ErrorMessage message={add.error} />
          <button className="button primary" type="submit" disabled={add.busy}>
            Add a passkey
          </button>
        </form>
      ) : (
        <p className="muted">This browser does not support passkeys.</p>
      )}
    </div>
  );
}

function Authenticator({
  status,
  email,
  onChange,
}: {
  status: SecurityStatus;
  email: string;
  onChange: OnChange;
}) {
  const withReauth = useReauth();
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const begin = useSubmit(async () => {
    setSetup(await withReauth(() => api<TotpSetup>('POST', '/account/security/totp/setup')));
  });
  const confirm = useSubmit(async (values: Record<string, string>) => {
    const result = await api<RecoveryCodes>('POST', '/account/security/totp/confirm', {
      code: values.code,
    });
    setSetup(null);
    onChange(result.recovery_codes);
  });
  const remove = useSubmit(async () => {
    await withReauth(() => api('DELETE', '/account/security/totp'));
    onChange();
  });

  return (
    <div className="security-block">
      <h3>Authenticator app</h3>
      {status.totp ? (
        <div className="row-inline">
          <span className="pill on">On</span>
          <button type="button" className="button ghost" onClick={() => void remove.run()}>
            Remove
          </button>
        </div>
      ) : setup ? (
        <div className="totp-setup">
          <p className="muted">
            Scan this with an authenticator app (such as Aegis, 2FAS, Google Authenticator or
            1Password), then enter the code it shows.
          </p>
          <img
            className="qr"
            src={setup.qr_svg}
            alt={`QR code to add ${email} to an authenticator app`}
          />
          <details>
            <summary>Can't scan? Enter this key instead</summary>
            <code className="copyable">{setup.secret}</code>
          </details>
          <form className="inline-form" onSubmit={(e) => void confirm.run(formValues(e))}>
            <Field
              label="Code from the app"
              name="code"
              required
              inputMode="numeric"
              autoComplete="one-time-code"
            />
            <ErrorMessage message={confirm.error} />
            <button className="button primary" type="submit" disabled={confirm.busy}>
              Turn on
            </button>
          </form>
        </div>
      ) : (
        <>
          <p className="muted">
            Six-digit codes from an app on your phone, as a second step after your password.
          </p>
          <button
            type="button"
            className="button"
            disabled={begin.busy}
            onClick={() => void begin.run()}
          >
            Set up
          </button>
        </>
      )}
      <ErrorMessage message={begin.error ?? remove.error} />
    </div>
  );
}

function Recovery({ status, onChange }: { status: SecurityStatus; onChange: OnChange }) {
  const withReauth = useReauth();
  const regenerate = useSubmit(async () => {
    const result = await withReauth(() =>
      api<RecoveryCodes>('POST', '/account/security/recovery-codes'),
    );
    onChange(result.recovery_codes);
  });
  if (!status.totp && status.passkeys.length === 0) return null;
  return (
    <div className="security-block">
      <h3>Recovery codes</h3>
      <p className="muted">
        {status.recovery_codes_left} unused. Each works once if you lose your phone or passkey.
      </p>
      <button
        type="button"
        className="button"
        disabled={regenerate.busy}
        onClick={() => void regenerate.run()}
      >
        Get new codes
      </button>
      <ErrorMessage message={regenerate.error} />
    </div>
  );
}

function RecoveryCodesPanel({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const text = codes.join('\n');
  const download = () => {
    const url = URL.createObjectURL(new Blob([`OpenChart AI recovery codes\n\n${text}\n`]));
    const link = Object.assign(document.createElement('a'), {
      href: url,
      download: 'openchart-recovery-codes.txt',
    });
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="notice" role="status">
      <p>
        <strong>Save these recovery codes now.</strong> They are shown only once. Each code signs
        you in once if you lose your second factor.
      </p>
      <ol className="codes">
        {codes.map((c) => (
          <li key={c}>
            <code>{c}</code>
          </li>
        ))}
      </ol>
      <div className="row-inline">
        <button
          type="button"
          className="button"
          onClick={() => void navigator.clipboard?.writeText(text)}
        >
          Copy
        </button>
        <button type="button" className="button" onClick={download}>
          Download
        </button>
        <button type="button" className="button primary" onClick={onDone}>
          I've saved them
        </button>
      </div>
    </div>
  );
}

function PasswordSection({ status, onChange }: { status: SecurityStatus; onChange: OnChange }) {
  const withReauth = useReauth();
  const [saved, setSaved] = useState(false);
  const save = useSubmit(async (form: HTMLFormElement, values: Record<string, string>) => {
    await withReauth(() => api('POST', '/account/security/password', values));
    form.reset();
    setSaved(true);
    onChange();
  });
  return (
    <div className="security-block">
      <h3>Password</h3>
      <form
        className="inline-form"
        onSubmit={(e) => {
          const form = e.currentTarget;
          void save.run(form, formValues(e));
        }}
      >
        <Field
          label={status.has_password ? 'New password' : 'Set a password'}
          name="new_password"
          type="password"
          required
          minLength={12}
          maxLength={256}
          autoComplete="new-password"
          hint="Other devices are signed out when you change it."
        />
        <ErrorMessage message={save.error} />
        {saved && (
          <p className="muted" role="status">
            Password saved.
          </p>
        )}
        <button className="button primary" type="submit" disabled={save.busy}>
          {status.has_password ? 'Change password' : 'Set password'}
        </button>
      </form>
    </div>
  );
}

function GoogleSection({ status, onChange }: { status: SecurityStatus; onChange: OnChange }) {
  const withReauth = useReauth();
  const link = useSubmit(() => withReauth(() => startGoogle('link')));
  const unlink = useSubmit(async () => {
    await withReauth(() => api('DELETE', '/account/security/google'));
    onChange();
  });
  return (
    <div className="security-block">
      <h3>Google</h3>
      {status.google_email ? (
        <div className="row-inline">
          <span>Linked to {status.google_email}</span>
          <button type="button" className="button ghost" onClick={() => void unlink.run()}>
            Unlink
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="button"
          disabled={link.busy}
          onClick={() => void link.run()}
        >
          Link a Google account
        </button>
      )}
      <ErrorMessage message={link.error ?? unlink.error} />
    </div>
  );
}

function RequireMfa({ status, onChange }: { status: SecurityStatus; onChange: OnChange }) {
  const withReauth = useReauth();
  const toggle = useSubmit(async () => {
    await withReauth(() => api('PUT', '/admin/settings', { require_mfa: !status.require_mfa }));
    onChange();
  });
  return (
    <div className="security-block">
      <h3>Everyone on this server</h3>
      <label className="switch">
        <input
          type="checkbox"
          checked={status.require_mfa}
          disabled={toggle.busy}
          onChange={() => void toggle.run()}
        />
        Require two-factor sign-in for all accounts
      </label>
      <ErrorMessage message={toggle.error} />
    </div>
  );
}
