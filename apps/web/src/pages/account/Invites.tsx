// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useState } from 'react';
import { api, type CreatedInvite, type Invite, type Me } from '../../api';
import { ErrorMessage, Field, formValues } from '../../components/Form';
import { when } from '../../format';
import { useLoad, useSubmit } from '../../hooks';

export function Invites({ user }: { user: Me }) {
  const load = useCallback(() => api<Invite[]>('GET', '/invites'), []);
  const { data, error, reload } = useLoad(load);
  const [created, setCreated] = useState<string | null>(null);
  const create = useSubmit(async (values: Record<string, string>) => {
    const invite = await api<CreatedInvite>('POST', '/invites', {
      email: values.email || null,
      role: values.role ?? 'member',
    });
    // The token goes in the fragment (#), which browsers never send to a
    // server, so it cannot end up in proxy or web-server access logs.
    setCreated(`${window.location.origin}/register#invite=${encodeURIComponent(invite.token)}`);
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
