// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback } from 'react';
import { api } from '../../api';
import { ErrorMessage, formValues } from '../../components/Form';
import { money, when } from '../../format';
import { useLoad, useSubmit } from '../../hooks';
import { useWorkspace } from '../context';
import { Icon } from '../Icon';
import { Panel } from '../Panel';
import type { Alert } from '../types';
import { MoneyField } from './Thesis';

export function AlertsPanel({ onClose }: { onClose: () => void }) {
  const { instrument } = useWorkspace();
  const load = useCallback(() => api<Alert[]>('GET', '/alerts'), []);
  const { data: alerts, error, setData: setAlerts } = useLoad(load);

  const add = useSubmit(async (form: HTMLFormElement, values: Record<string, string>) => {
    if (!instrument) return;
    const made = await api<Alert>('POST', '/alerts', {
      instrument_id: instrument.id,
      direction: values.direction,
      price: values.price?.trim(),
      note: values.note?.trim() ?? '',
    });
    setAlerts((list) => [made, ...(list ?? [])]);
    form.reset();
  });
  const change = useSubmit(async (alert: Alert) => {
    const updated = await api<Alert>('PATCH', `/alerts/${alert.id}`, { active: !alert.active });
    setAlerts((list) => list?.map((a) => (a.id === alert.id ? updated : a)) ?? null);
  });
  const remove = useSubmit(async (id: string) => {
    await api('DELETE', `/alerts/${id}`);
    setAlerts((list) => list?.filter((a) => a.id !== id) ?? null);
  });

  return (
    <Panel
      eyebrow="WATCH / 04"
      title="Price alerts"
      subtitle="Your levels, your rules."
      onClose={onClose}
    >
      <p className="helper">
        Alerts are saved now and checked once a live data source is connected (milestone M3).
      </p>
      {instrument ? (
        <form
          className="inline-form"
          aria-label={`New alert for ${instrument.symbol}`}
          onSubmit={(e) => {
            const form = e.currentTarget;
            void add.run(form, formValues(e));
          }}
        >
          <p className="muted">
            {instrument.symbol} · {instrument.name}
          </p>
          <div className="grid-fields">
            <label className="field">
              <span>When the price goes</span>
              <select name="direction" defaultValue="above">
                <option value="above">Above</option>
                <option value="below">Below</option>
              </select>
            </label>
            <MoneyField label={`Price (${instrument.currency})`} name="price" required />
          </div>
          <label className="field">
            <span>Note</span>
            <input name="note" maxLength={500} placeholder="Optional" />
          </label>
          <ErrorMessage message={add.error} />
          <button className="button primary" type="submit" disabled={add.busy}>
            Add alert
          </button>
        </form>
      ) : (
        <p className="muted">Choose an instrument to set an alert on it.</p>
      )}

      <h3 className="list-heading">Your alerts</h3>
      {error && <p className="form-error">{error}</p>}
      {alerts?.length === 0 && <p className="muted">No alerts yet.</p>}
      {alerts && alerts.length > 0 && (
        <ul className="rows">
          {alerts.map((a) => (
            <li key={a.id} className="row" data-paused={!a.active || undefined}>
              <div>
                <strong>{a.instrument.symbol}</strong> {a.direction}{' '}
                {money(a.price, a.instrument.currency)}
                {!a.active && <span className="pill">Paused</span>}
                <small>
                  {a.triggered_at
                    ? `Triggered ${when(a.triggered_at)}`
                    : `Set ${when(a.created_at)}`}
                  {a.note && ` · ${a.note}`}
                </small>
              </div>
              <div className="row-inline tight">
                <button
                  type="button"
                  className="button ghost"
                  disabled={change.busy}
                  onClick={() => void change.run(a)}
                >
                  {a.active ? 'Pause' : 'Resume'}
                </button>
                <button
                  type="button"
                  className="icon-button small"
                  aria-label={`Delete alert: ${a.instrument.symbol} ${a.direction} ${a.price}`}
                  disabled={remove.busy}
                  onClick={() => void remove.run(a.id)}
                >
                  <Icon name="trash" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <ErrorMessage message={change.error ?? remove.error} />
    </Panel>
  );
}
