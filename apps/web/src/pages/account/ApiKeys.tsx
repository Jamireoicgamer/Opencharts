// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, type FormEvent } from 'react';
import { api, type SecretInfo } from '../../api';
import { ErrorMessage, Field, formValues } from '../../components/Form';
import { when } from '../../format';
import { useLoad, useSubmit } from '../../hooks';

export function ApiKeys() {
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
          placeholder="e.g. finnhub"
          hint="Lower-case letters, digits, dots, dashes."
        />
        <Field
          label="Provider (optional)"
          name="provider"
          maxLength={64}
          placeholder="e.g. Finnhub"
        />
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
