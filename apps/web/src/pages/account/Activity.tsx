// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback } from 'react';
import { api, type AuditEvent } from '../../api';
import { ErrorMessage } from '../../components/Form';
import { when } from '../../format';
import { useLoad } from '../../hooks';

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
  'auth.mfa_failed': 'Wrong two-factor code',
  'auth.reauth': 'Identity confirmed',
  'auth.reauth_failed': 'Failed identity confirmation',
  'auth.password_changed': 'Password changed',
  'mfa.totp_enabled': 'Authenticator app turned on',
  'mfa.totp_disabled': 'Authenticator app removed',
  'mfa.recovery_codes_issued': 'New recovery codes issued',
  'mfa.recovery_code_used': 'Recovery code used',
  'passkey.added': 'Passkey added',
  'passkey.removed': 'Passkey removed',
  'oauth.linked': 'Google account linked',
  'oauth.unlinked': 'Google account unlinked',
  'oauth.failed': 'Google sign-in failed',
  'settings.require_mfa_changed': 'Two-factor requirement changed',
};

export function Activity() {
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
