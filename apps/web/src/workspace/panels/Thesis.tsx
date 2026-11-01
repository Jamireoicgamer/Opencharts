// SPDX-License-Identifier: AGPL-3.0-or-later
// The investment thesis: a journal of versions. Saving adds a version; old
// versions are never changed, so the person can see how their view moved.
import { useCallback, useState, type InputHTMLAttributes } from 'react';
import { api } from '../../api';
import { ErrorMessage } from '../../components/Form';
import { money, plain, when } from '../../format';
import { useLoad, useSubmit } from '../../hooks';
import { useWorkspace } from '../context';
import { NoInstrument, Panel } from '../Panel';
import {
  CONVICTION_LABELS,
  HORIZON_LABELS,
  instrumentPath,
  type Conviction,
  type Horizon,
  type Instrument,
  type Thesis,
  type ThesisInput,
  type ThesisVersion,
} from '../types';

const BLANK: ThesisInput = {
  summary: '',
  key_risk: '',
  bull_case: '',
  bear_case: '',
  fair_value: null,
  entry_price: null,
  conviction: 'not_assessed',
  horizon: 'not_set',
};

/** The editable copy of a version; amounts are kept as typed. */
type Draft = Omit<ThesisInput, 'fair_value' | 'entry_price'> & {
  fair_value: string;
  entry_price: string;
};

const toDraft = (v: ThesisInput): Draft => ({
  summary: v.summary,
  key_risk: v.key_risk,
  bull_case: v.bull_case,
  bear_case: v.bear_case,
  conviction: v.conviction,
  horizon: v.horizon,
  fair_value: v.fair_value === null ? '' : plain(v.fair_value),
  entry_price: v.entry_price === null ? '' : plain(v.entry_price),
});

export function ThesisPanel({ onClose, onSearch }: { onClose: () => void; onSearch: () => void }) {
  const { instrument } = useWorkspace();
  return (
    <Panel
      eyebrow="INVESTMENT JOURNAL"
      title="Thesis"
      subtitle={
        instrument ? `${instrument.name} · your reasoning, versioned` : 'Your reasoning, versioned'
      }
      onClose={onClose}
      wide
    >
      {instrument ? (
        <ThesisEditor key={instrument.id} instrument={instrument} />
      ) : (
        <NoInstrument onSearch={onSearch} />
      )}
    </Panel>
  );
}

function ThesisEditor({ instrument }: { instrument: Instrument }) {
  const path = `${instrumentPath(instrument.id)}/thesis`;
  const load = useCallback(() => api<Thesis>('GET', path), [path]);
  const { data, error } = useLoad(load);
  if (error) return <p className="form-error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  return <ThesisBody instrument={instrument} path={path} initial={data} />;
}

function ThesisBody({
  instrument,
  path,
  initial,
}: {
  instrument: Instrument;
  path: string;
  initial: Thesis;
}) {
  const [data, setData] = useState(initial);
  // The editor starts from the latest version.
  const [draft, setDraft] = useState<Draft>(() => toDraft(initial.current ?? BLANK));
  const [tab, setTab] = useState<'editor' | 'history'>('editor');
  const [saved, setSaved] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const save = useSubmit(async () => {
    const body: ThesisInput = {
      ...draft,
      fair_value: draft.fair_value.trim() || null,
      entry_price: draft.entry_price.trim() || null,
    };
    const version = await api<ThesisVersion>('POST', path, body);
    setData((d) => ({ current: version, history: [version, ...d.history] }));
    setSaved('Saved as a new version.');
  });
  const remove = useSubmit(async () => {
    await api('DELETE', path);
    setConfirmDelete(false);
    setDraft(toDraft(BLANK));
    setData({ current: null, history: [] });
  });

  const set =
    <K extends keyof Draft>(key: K) =>
    (e: { target: { value: string } }) => {
      setSaved(null);
      setDraft((d) => ({ ...d, [key]: e.target.value }));
    };

  return (
    <>
      <div className="subtabs" role="tablist" aria-label="Thesis">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'editor'}
          onClick={() => setTab('editor')}
        >
          Editor
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'history'}
          onClick={() => setTab('history')}
        >
          History <span className="count">{data.history.length}</span>
        </button>
      </div>

      {tab === 'editor' ? (
        <form
          className="thesis-form"
          onSubmit={(e) => {
            e.preventDefault();
            void save.run();
          }}
        >
          <p className="helper">
            Make your assumptions testable. Conviction and valuation are separate.
          </p>
          <TextArea
            label="The investment case"
            rows={4}
            value={draft.summary}
            onChange={set('summary')}
            placeholder="Why does this belong in your portfolio?"
            max={10000}
          />
          <div className="grid-fields">
            <Select
              label="Conviction"
              value={draft.conviction}
              onChange={set('conviction')}
              options={CONVICTION_LABELS as Record<Conviction, string>}
            />
            <Select
              label="Horizon"
              value={draft.horizon}
              onChange={set('horizon')}
              options={HORIZON_LABELS as Record<Horizon, string>}
            />
          </div>
          <div className="grid-fields">
            <MoneyField
              label={`Fair value (${instrument.currency})`}
              value={draft.fair_value}
              onChange={set('fair_value')}
            />
            <MoneyField
              label={`Preferred entry (${instrument.currency})`}
              value={draft.entry_price}
              onChange={set('entry_price')}
            />
          </div>
          <div className="grid-fields">
            <TextArea
              label="What supports your view?"
              rows={3}
              value={draft.bull_case}
              onChange={set('bull_case')}
              placeholder="Catalysts and evidence"
              max={5000}
            />
            <TextArea
              label="The strongest counterargument"
              rows={3}
              value={draft.bear_case}
              onChange={set('bear_case')}
              placeholder="Risks and other explanations"
              max={5000}
            />
          </div>
          <TextArea
            label="What would make you reconsider?"
            rows={3}
            value={draft.key_risk}
            onChange={set('key_risk')}
            placeholder="Conditions that would invalidate the thesis"
            max={5000}
          />
          <ErrorMessage message={save.error} />
          <div className="form-actions">
            <span className="save-caption" role="status">
              {saved ??
                (data.current ? `Last saved ${when(data.current.created_at)}` : 'Not saved yet')}
            </span>
            <button className="button primary" type="submit" disabled={save.busy}>
              Save version
            </button>
          </div>
        </form>
      ) : (
        <div>
          {data.history.length === 0 ? (
            <p className="muted">No versions yet. Each save adds one.</p>
          ) : (
            <ol className="versions">
              {data.history.map((v) => (
                <li key={v.id} className="version">
                  <div className="version-head">
                    <strong>{when(v.created_at)}</strong>
                    <span className="pill">{CONVICTION_LABELS[v.conviction]}</span>
                    {v.horizon !== 'not_set' && (
                      <span className="pill">{HORIZON_LABELS[v.horizon]}</span>
                    )}
                  </div>
                  {v.summary && <p className="version-text">{v.summary}</p>}
                  {(v.fair_value || v.entry_price) && (
                    <p className="version-meta muted">
                      {v.fair_value && `Fair value ${money(v.fair_value, instrument.currency)}`}
                      {v.fair_value && v.entry_price && ' · '}
                      {v.entry_price && `Entry ${money(v.entry_price, instrument.currency)}`}
                    </p>
                  )}
                  <button
                    type="button"
                    className="button ghost"
                    onClick={() => {
                      setDraft(toDraft(v));
                      setSaved('Loaded into the editor. Save to make it the current version.');
                      setTab('editor');
                    }}
                  >
                    Load into editor
                  </button>
                </li>
              ))}
            </ol>
          )}
          {data.history.length > 0 && (
            <div className="danger-zone">
              {confirmDelete ? (
                <>
                  <p>Delete every version of this thesis? This cannot be undone.</p>
                  <div className="row-inline">
                    <button
                      type="button"
                      className="button danger"
                      disabled={remove.busy}
                      onClick={() => void remove.run()}
                    >
                      Delete all versions
                    </button>
                    <button
                      type="button"
                      className="button ghost"
                      onClick={() => setConfirmDelete(false)}
                    >
                      Keep them
                    </button>
                  </div>
                </>
              ) : (
                <button
                  type="button"
                  className="button ghost"
                  onClick={() => setConfirmDelete(true)}
                >
                  Delete thesis history…
                </button>
              )}
              <ErrorMessage message={remove.error} />
            </div>
          )}
        </div>
      )}
    </>
  );
}

function TextArea({
  label,
  max,
  ...props
}: {
  label: string;
  max: number;
  rows: number;
  value: string;
  placeholder: string;
  onChange: (e: { target: { value: string } }) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <textarea maxLength={max} {...props} />
    </label>
  );
}

function Select<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: Record<T, string>;
  onChange: (e: { target: { value: string } }) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={onChange}>
        {(Object.entries(options) as [T, string][]).map(([key, text]) => (
          <option key={key} value={key}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

export function MoneyField({
  label,
  ...input
}: { label: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        inputMode="decimal"
        autoComplete="off"
        pattern="[0-9]*[.]?[0-9]*"
        title="A positive number, such as 21.50"
        placeholder={input.required ? undefined : 'Optional'}
        {...input}
      />
    </label>
  );
}
