// SPDX-License-Identifier: AGPL-3.0-or-later
// A manual journal of holdings, grouped by account. Market values need live
// prices (M3), so they show "—" until then rather than a made-up number.
import { useCallback, useState } from 'react';
import { api } from '../../api';
import { ErrorMessage, formValues } from '../../components/Form';
import { amount, money, plain } from '../../format';
import { useLoad, useSubmit } from '../../hooks';
import { useWorkspace } from '../context';
import { Icon } from '../Icon';
import { Panel } from '../Panel';
import { ACCOUNT_LABELS, type Account, type Position, type RiskProfile } from '../types';
import { MoneyField } from './Thesis';

const ACCOUNTS = Object.keys(ACCOUNT_LABELS) as Account[];
const RISK_LABELS: Record<RiskProfile, string> = {
  conservative: 'Conservative',
  balanced: 'Balanced',
  aggressive: 'Aggressive',
};

/** Form values for a position; empty optional fields become null. */
function positionBody(values: Record<string, string>) {
  return {
    quantity: values.quantity?.trim(),
    average_price: values.average_price?.trim() || null,
    account: values.account,
    note: values.note?.trim() ?? '',
  };
}

export function PortfolioPanel({ onClose }: { onClose: () => void }) {
  const { instrument, prefs, updatePrefs } = useWorkspace();
  const load = useCallback(() => api<Position[]>('GET', '/positions'), []);
  const { data: positions, error, setData: setPositions } = useLoad(load);
  const [editing, setEditing] = useState<string | null>(null);

  const add = useSubmit(async (form: HTMLFormElement, values: Record<string, string>) => {
    if (!instrument) return;
    const made = await api<Position>('POST', '/positions', {
      instrument_id: instrument.id,
      ...positionBody(values),
    });
    setPositions((list) => [...(list ?? []), made]);
    form.reset();
  });
  const change = useSubmit(async (id: string, values: Record<string, string>) => {
    const updated = await api<Position>('PATCH', `/positions/${id}`, positionBody(values));
    setPositions((list) => list?.map((p) => (p.id === id ? updated : p)) ?? null);
    setEditing(null);
  });
  const remove = useSubmit(async (id: string) => {
    await api('DELETE', `/positions/${id}`);
    setPositions((list) => list?.filter((p) => p.id !== id) ?? null);
  });

  return (
    <Panel
      eyebrow="PORTFOLIO / 03"
      title="Holdings & risk"
      subtitle="Your exposure, without the noise."
      onClose={onClose}
    >
      <div className="metric-pair">
        <div className="metric">
          <span>POSITIONS</span>
          <strong>{positions?.length ?? '…'}</strong>
        </div>
        <label className="metric">
          <span>RISK PROFILE</span>
          <select
            value={prefs.risk_profile}
            onChange={(e) => void updatePrefs({ risk_profile: e.target.value as RiskProfile })}
          >
            {(Object.keys(RISK_LABELS) as RiskProfile[]).map((r) => (
              <option key={r} value={r}>
                {RISK_LABELS[r]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="helper">
        Market value and profit appear once a live data source is connected. Nothing here is
        estimated.
      </p>

      {error && <p className="form-error">{error}</p>}
      {positions?.length === 0 && <p className="muted">No holdings recorded yet.</p>}
      {ACCOUNTS.map((account) => {
        const group = positions?.filter((p) => p.account === account) ?? [];
        if (group.length === 0) return null;
        return (
          <section key={account} className="holding-group" aria-label={ACCOUNT_LABELS[account]}>
            <h3 className="list-heading">{ACCOUNT_LABELS[account]}</h3>
            <ul className="rows">
              {group.map((p) =>
                editing === p.id ? (
                  <li key={p.id} className="row">
                    <form
                      className="edit-position"
                      onSubmit={(e) => void change.run(p.id, formValues(e))}
                    >
                      <PositionFields position={p} />
                      <div className="row-inline">
                        <button className="button primary" type="submit" disabled={change.busy}>
                          Save
                        </button>
                        <button
                          type="button"
                          className="button ghost"
                          onClick={() => setEditing(null)}
                        >
                          Cancel
                        </button>
                      </div>
                      <ErrorMessage message={change.error} />
                    </form>
                  </li>
                ) : (
                  <li key={p.id} className="row holding">
                    <div>
                      <strong>{p.instrument.symbol}</strong>{' '}
                      <span className="muted">{p.instrument.name}</span>
                      <small>
                        {amount(p.quantity)} units
                        {p.average_price && ` at ${money(p.average_price, p.instrument.currency)}`}
                        {' · value —'}
                        {p.note && ` · ${p.note}`}
                      </small>
                    </div>
                    <div className="row-inline tight">
                      <button
                        type="button"
                        className="button ghost"
                        onClick={() => setEditing(p.id)}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="icon-button small"
                        aria-label={`Delete ${p.instrument.symbol} holding`}
                        disabled={remove.busy}
                        onClick={() => void remove.run(p.id)}
                      >
                        <Icon name="trash" />
                      </button>
                    </div>
                  </li>
                ),
              )}
            </ul>
          </section>
        );
      })}
      <ErrorMessage message={remove.error} />

      <h3 className="list-heading">Record a holding</h3>
      {instrument ? (
        <form
          className="inline-form"
          aria-label={`Record a holding of ${instrument.symbol}`}
          onSubmit={(e) => {
            const form = e.currentTarget;
            void add.run(form, formValues(e));
          }}
        >
          <p className="muted">
            {instrument.symbol} · {instrument.name}
          </p>
          <PositionFields currency={instrument.currency} />
          <ErrorMessage message={add.error} />
          <button className="button primary" type="submit" disabled={add.busy}>
            Add holding
          </button>
        </form>
      ) : (
        <p className="muted">Choose an instrument to record a holding of it.</p>
      )}
    </Panel>
  );
}

function PositionFields({ position, currency }: { position?: Position; currency?: string }) {
  const unit = currency ?? position?.instrument.currency ?? '';
  return (
    <>
      <div className="grid-fields">
        <label className="field">
          <span>Quantity</span>
          <input
            name="quantity"
            inputMode="decimal"
            pattern="[0-9]*[.]?[0-9]*"
            required
            defaultValue={position ? plain(position.quantity) : undefined}
          />
        </label>
        <MoneyField
          label={`Average price (${unit})`}
          name="average_price"
          defaultValue={position?.average_price ? plain(position.average_price) : undefined}
        />
      </div>
      <div className="grid-fields">
        <label className="field">
          <span>Account</span>
          <select name="account" defaultValue={position?.account ?? 'isa'}>
            {ACCOUNTS.map((a) => (
              <option key={a} value={a}>
                {ACCOUNT_LABELS[a]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Note</span>
          <input name="note" maxLength={500} defaultValue={position?.note} placeholder="Optional" />
        </label>
      </div>
    </>
  );
}
