// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { NavLink, Navigate, Route, Routes } from 'react-router';
import {
  api,
  type AuditEvent,
  type CreatedInvite,
  type Invite,
  type Me,
  type SecretInfo,
  type SessionInfo,
} from '../api';
import { ErrorMessage, Field, formValues, useSubmit } from '../components/Form';

const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const when = (iso: string) => dateTime.format(new Date(iso));

/** Loads data from the API; `reload()` fetches it again. */
function useLoad<T>(load: () => Promise<T>) {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({
    data: null,
    error: null,
  });
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    load().then(
      (data) => {
        if (active) setState({ data, error: null });
      },
      () => {
        if (active) setState((prev) => ({ ...prev, error: 'Could not load this list.' }));
      },
    );
    return () => {
      active = false;
    };
  }, [load, version]);
  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { ...state, reload };
}

function describeDevice(agent: string | null): string {
  if (!agent) return 'Unknown device';
  const browser = /Firefox|Edg|Chrome|Safari/.exec(agent)?.[0]?.replace('Edg', 'Edge') ?? 'Browser';
  const os =
    /Windows|Mac OS X|Android|iPhone|iPad|Linux|CrOS/
      .exec(agent)?.[0]
      ?.replace('Mac OS X', 'macOS') ?? '';
  return os ? `${browser} on ${os}` : browser;
}

function Sessions() {
  const load = useCallback(() => api<SessionInfo[]>('GET', '/auth/sessions'), []);
  const { data, error, reload } = useLoad(load);
  const revoke = useSubmit(async (id: string) => {
    await api('DELETE', `/auth/sessions/${id}`);
    reload();
  });
  const revokeOthers = useSubmit(async () => {
    await api('POST', '/auth/sessions/revoke-others');
    reload();
  });

  return (
    <section aria-labelledby="sessions-title">
      <div className="section-head">
        <h2 id="sessions-title">Signed-in devices</h2>
        <button
          type="button"
          className="button"
          disabled={revokeOthers.busy || (data?.length ?? 0) < 2}
          onClick={() => void revokeOthers.run()}
        >
          Sign out other devices
        </button>
      </div>
      <ErrorMessage message={error ?? revoke.error ?? revokeOthers.error} />
      <ul className="rows">
        {data?.map((s) => (
          <li key={s.id} className="row">
            <div>
              <strong>{describeDevice(s.user_agent)}</strong>
              {s.current && <span className="pill">This device</span>}
              <small>
                {s.ip ?? 'unknown IP'} · last active {when(s.last_seen_at)} · signed in{' '}
                {when(s.created_at)}
              </small>
            </div>
            {!s.current && (
              <button type="button" className="button ghost" onClick={() => void revoke.run(s.id)}>
                Sign out
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ApiKeys() {
  const load = useCallback(() => api<SecretInfo[]>('GET', '/secrets'), []);
  const { data, error, reload } = useLoad(load);
  const save = useSubmit(async (form: HTMLFormElement, values: Record<string, string>) => {
    const { name = '', value = '', provider = '' } = values;
    await api('PUT', `/secrets/${encodeURIComponent(name)}`, { value, provider: provider || null });
    form.reset(); // never keep the secret around in the page
    reload();
  });
  const remove = useSubmit(async (name: string) => {
    await api('DELETE', `/secrets/${encodeURIComponent(name)}`);
    reload();
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    const form = event.currentTarget;
    void save.run(form, formValues(event));
  }

  return (
    <section aria-labelledby="keys-title">
      <div className="section-head">
        <h2 id="keys-title">API keys</h2>
      </div>
      <p className="muted">
        Keys are encrypted on the server and can never be shown again, only replaced or deleted.
      </p>
      <ErrorMessage message={error ?? remove.error} />
      <ul className="rows">
        {data?.length === 0 && <li className="row muted">No keys saved yet.</li>}
        {data?.map((s) => (
          <li key={s.name} className="row">
            <div>
              <strong>{s.name}</strong>
              {s.provider && <span className="pill">{s.provider}</span>}
              <small>
                {s.hint ? `ends ${s.hint}` : 'hidden'} · updated {when(s.updated_at)}
              </small>
            </div>
            <button type="button" className="button ghost" onClick={() => void remove.run(s.name)}>
              Delete
            </button>
          </li>
        ))}
      </ul>
      <form className="inline-form" onSubmit={onSubmit} autoComplete="off">
        <Field
          label="Name"
          name="name"
          required
          pattern="[a-z0-9][a-z0-9_.\-]{0,63}"
          placeholder="finnhub"
          hint="Lower-case letters, digits, dots, dashes."
        />
        <Field label="Provider (optional)" name="provider" maxLength={64} placeholder="Finnhub" />
        <Field
          label="Key"
          name="value"
          type="password"
          required
          maxLength={4096}
          autoComplete="off"
        />
        <ErrorMessage message={save.error} />
        <button className="button primary" type="submit" disabled={save.busy}>
          Save key
        </button>
      </form>
    </section>
  );
}

function Invites({ user }: { user: Me }) {
  const load = useCallback(() => api<Invite[]>('GET', '/invites'), []);
  const { data, error, reload } = useLoad(load);
  const [created, setCreated] = useState<string | null>(null);
  const create = useSubmit(async (values: Record<string, string>) => {
    const invite = await api<CreatedInvite>('POST', '/invites', {
      email: values.email || null,
      role: values.role ?? 'member',
    });
    setCreated(`${window.location.origin}/register?invite=${encodeURIComponent(invite.token)}`);
    reload();
  });
  const revoke = useSubmit(async (id: string) => {
    await api('DELETE', `/invites/${id}`);
    reload();
  });

  return (
    <section aria-labelledby="invites-title">
      <div className="section-head">
        <h2 id="invites-title">Invites</h2>
      </div>
      <form className="inline-form" onSubmit={(e) => void create.run(formValues(e))}>
        <Field
          label="Email (optional)"
          name="email"
          type="email"
          hint="Locks the invite to this address."
        />
        {user.role === 'owner' && (
          <div className="field">
            <label htmlFor="invite-role">Role</label>
            <select id="invite-role" name="role" defaultValue="member">
              <option value="member">Member</option>
              <option value="admin">Admin (can invite others)</option>
            </select>
          </div>
        )}
        <ErrorMessage message={create.error} />
        <button className="button primary" type="submit" disabled={create.busy}>
          Create invite link
        </button>
      </form>
      {created && (
        <div className="notice" role="status">
          <p>Send this link to the person you are inviting. It is shown only once.</p>
          <code className="copyable">{created}</code>
          <button
            type="button"
            className="button"
            onClick={() => void navigator.clipboard?.writeText(created)}
          >
            Copy link
          </button>
        </div>
      )}
      <ErrorMessage message={error ?? revoke.error} />
      <ul className="rows">
        {data?.map((i) => (
          <li key={i.id} className="row">
            <div>
              <strong>{i.email ?? 'Anyone with the link'}</strong>
              <span className="pill">{i.role}</span>
              <small>
                {i.used_at
                  ? `used ${when(i.used_at)}`
                  : new Date(i.expires_at) < new Date()
                    ? 'expired'
                    : `expires ${when(i.expires_at)}`}
              </small>
            </div>
            {!i.used_at && (
              <button type="button" className="button ghost" onClick={() => void revoke.run(i.id)}>
                Revoke
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

const ACTION_LABELS: Record<string, string> = {
  'setup.owner_created': 'Owner account created',
  'setup.token_rejected': 'Wrong setup token entered',
  'auth.login': 'Signed in',
  'auth.login_failed': 'Failed sign-in attempt',
  'auth.login_rate_limited': 'Sign-in blocked (too many attempts)',
  'auth.logout': 'Signed out',
  'auth.registered': 'Account created from invite',
  'auth.session_revoked': 'Signed out a device',
  'auth.sessions_revoked_others': 'Signed out other devices',
  'invite.created': 'Invite created',
  'invite.revoked': 'Invite revoked',
  'secret.saved': 'API key saved',
  'secret.deleted': 'API key deleted',
};

function Activity() {
  const load = useCallback(() => api<AuditEvent[]>('GET', '/audit?limit=100'), []);
  const { data, error } = useLoad(load);
  return (
    <section aria-labelledby="activity-title">
      <div className="section-head">
        <h2 id="activity-title">Security activity</h2>
      </div>
      <ErrorMessage message={error} />
      <ul className="rows">
        {data?.map((e) => (
          <li key={e.id} className="row">
            <div>
              <strong
                data-failed={
                  e.action.includes('fail') || e.action.includes('rejected') || undefined
                }
              >
                {ACTION_LABELS[e.action] ?? e.action}
              </strong>
              {e.target && <span className="pill">{e.target}</span>}
              <small>
                {when(e.created_at)} · {e.ip ?? 'unknown IP'}
              </small>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function AccountPage({ user }: { user: Me }) {
  const canInvite = user.role === 'owner' || user.role === 'admin';
  return (
    <main className="account">
      <header className="account-head">
        <h1>{user.display_name}</h1>
        <p className="muted">
          {user.email} · {user.role}
        </p>
      </header>
      <nav className="tabs" aria-label="Account sections">
        <NavLink to="/account/sessions">Devices</NavLink>
        <NavLink to="/account/keys">API keys</NavLink>
        {canInvite && <NavLink to="/account/invites">Invites</NavLink>}
        <NavLink to="/account/activity">Activity</NavLink>
      </nav>
      <Routes>
        <Route index element={<Navigate to="sessions" replace />} />
        <Route path="sessions" element={<Sessions />} />
        <Route path="keys" element={<ApiKeys />} />
        {canInvite && <Route path="invites" element={<Invites user={user} />} />}
        <Route path="activity" element={<Activity />} />
        <Route path="*" element={<Navigate to="sessions" replace />} />
      </Routes>
    </main>
  );
}
