// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback } from 'react';
import { api, type SessionInfo } from '../../api';
import { ErrorMessage } from '../../components/Form';
import { when } from '../../format';
import { useLoad, useSubmit } from '../../hooks';

function describeDevice(agent: string | null): string {
  if (!agent) return 'Unknown device';
  const browser = /Firefox|Edg|Chrome|Safari/.exec(agent)?.[0]?.replace('Edg', 'Edge') ?? 'Browser';
  const os =
    /Windows|Mac OS X|Android|iPhone|iPad|Linux|CrOS/
      .exec(agent)?.[0]
      ?.replace('Mac OS X', 'macOS') ?? '';
  return os ? `${browser} on ${os}` : browser;
}

export function Sessions() {
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
