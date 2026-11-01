// SPDX-License-Identifier: AGPL-3.0-or-later
// Where prices come from. Everyone sees which sources are on; owners and
// admins switch them, accept terms and set keys (after a recent sign-in).
import { useCallback, useState } from 'react';
import { api } from '../../api';
import { ErrorMessage } from '../../components/Form';
import { useReauth } from '../../components/Reauth';
import { useLoad, useSubmit } from '../../hooks';
import type { Provider, SourceInfo } from '../../market/types';
import { Icon } from '../Icon';

const YAHOO_TERMS = 'https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html';

export function DataSources() {
  const load = useCallback(() => api<SourceInfo[]>('GET', '/data-sources'), []);
  const { data: sources, error, setData } = useLoad(load);
  const withReauth = useReauth();
  const change = useSubmit(async (provider: Provider, body: Record<string, unknown>) => {
    const updated = await withReauth(() =>
      api<SourceInfo[]>('PUT', `/admin/data-sources/${provider}`, body),
    );
    setData(() => updated);
  });

  if (error) return <p className="form-error">{error}</p>;
  if (!sources) return <p className="muted">Loading…</p>;
  const canManage = sources.some((s) => s.enabled !== null);

  return (
    <div className="data-sources">
      <p className="helper">
        {canManage
          ? 'Sources are tried from the top; if one fails, the next one that covers the instrument takes over. Changes apply at once for everyone on this server.'
          : 'The owner of this server chooses where prices come from.'}
      </p>
      <ul className="rows">
        {sources.map((s, index) => (
          <li key={s.provider} className="row source">
            <div className="source-main">
              <div className="source-head">
                <strong>{s.label}</strong>
                <span className="pill" data-on={s.active || undefined}>
                  {s.active ? 'In use' : 'Off'}
                </span>
              </div>
              <small>{s.coverage}</small>
              {canManage && s.enabled && !s.active && (
                <small className="source-blocked">
                  {s.needs_terms && !s.terms_accepted
                    ? 'Accept the terms below to use it.'
                    : s.needs_key && !s.key_hint
                      ? 'Add an API key below to use it.'
                      : 'Not available.'}
                </small>
              )}
              {canManage && s.needs_terms && (
                <label className="switch terms">
                  <input
                    type="checkbox"
                    checked={Boolean(s.terms_accepted)}
                    disabled={change.busy}
                    onChange={(e) =>
                      void change.run(s.provider, { accept_terms: e.target.checked })
                    }
                  />
                  <span>
                    Yahoo Finance data is for personal, non-commercial use, and this unofficial feed
                    can stop working without notice. I accept{' '}
                    <a href={YAHOO_TERMS} target="_blank" rel="noreferrer">
                      Yahoo&rsquo;s terms
                    </a>{' '}
                    for this server.
                  </span>
                </label>
              )}
              {canManage && s.needs_key && (
                <KeyForm source={s} busy={change.busy} onSave={change.run} />
              )}
            </div>
            {canManage && (
              <div className="source-actions">
                <label className="switch">
                  <input
                    type="checkbox"
                    aria-label={`Use ${s.label}`}
                    checked={Boolean(s.enabled)}
                    disabled={change.busy}
                    onChange={(e) => void change.run(s.provider, { enabled: e.target.checked })}
                  />
                </label>
                <button
                  type="button"
                  className="icon-button small"
                  aria-label={`Try ${s.label} earlier`}
                  disabled={index === 0 || change.busy}
                  onClick={() =>
                    void change.run(s.provider, {
                      priority: Math.max(1, (sources[index - 1]?.priority ?? 2) - 1),
                    })
                  }
                >
                  <Icon name="up" />
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
      <ErrorMessage message={change.error} />
    </div>
  );
}

function KeyForm({
  source,
  busy,
  onSave,
}: {
  source: SourceInfo;
  busy: boolean;
  onSave: (provider: Provider, body: Record<string, unknown>) => Promise<void>;
}) {
  const [key, setKey] = useState('');
  return (
    <form
      className="key-form"
      onSubmit={(e) => {
        e.preventDefault();
        void onSave(source.provider, { api_key: key }).then(() => setKey(''));
      }}
    >
      <label className="field">
        <span>
          {source.label} API key{' '}
          {source.key_hint && <span className="muted">(saved, ends {source.key_hint})</span>}
        </span>
        <input
          type="password"
          autoComplete="off"
          minLength={8}
          maxLength={200}
          value={key}
          placeholder={source.key_hint ? 'Replace the saved key' : 'Paste your key'}
          onChange={(e) => setKey(e.target.value)}
        />
      </label>
      <div className="row-inline tight">
        <button className="button" type="submit" disabled={busy || key.trim().length < 8}>
          Save key
        </button>
        {source.key_hint && (
          <button
            type="button"
            className="button ghost"
            disabled={busy}
            onClick={() => void onSave(source.provider, { remove_key: true })}
          >
            Remove key
          </button>
        )}
      </div>
    </form>
  );
}
