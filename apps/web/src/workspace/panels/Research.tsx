// SPDX-License-Identifier: AGPL-3.0-or-later
// Research for one instrument: a checklist and free-form notes. Notes save
// themselves a moment after the person stops typing.
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { ErrorMessage } from '../../components/Form';
import { useLoad, useSubmit } from '../../hooks';
import { useWorkspace } from '../context';
import { Icon } from '../Icon';
import { NoInstrument, Panel } from '../Panel';
import { instrumentPath, type Instrument, type Research } from '../types';

export const AUTOSAVE_MS = 800;

export function ResearchPanel({
  onClose,
  onSearch,
}: {
  onClose: () => void;
  onSearch: () => void;
}) {
  const { instrument } = useWorkspace();
  return (
    <Panel
      eyebrow="RESEARCH / 02"
      title="Research"
      subtitle={instrument ? instrument.name : 'An organised place for the evidence.'}
      onClose={onClose}
    >
      {instrument ? (
        <ResearchBody key={instrument.id} instrument={instrument} />
      ) : (
        <NoInstrument onSearch={onSearch} />
      )}
    </Panel>
  );
}

function ResearchBody({ instrument }: { instrument: Instrument }) {
  const base = `${instrumentPath(instrument.id)}/research`;
  const load = useCallback(() => api<Research>('GET', base), [base]);
  const { data: research, error, setData } = useLoad(load);

  const task = useSubmit(async (work: () => Promise<Research>) => {
    const updated = await work();
    setData(() => updated);
  });

  if (error) return <p className="form-error">{error}</p>;
  if (!research) return <p className="muted">Loading…</p>;

  return (
    <>
      <h3 className="list-heading">Checklist</h3>
      {research.tasks.length === 0 && <p className="muted">No tasks. Add your own below.</p>}
      <ul className="checklist">
        {research.tasks.map((t) => (
          <li key={t.id}>
            <label>
              <input
                type="checkbox"
                checked={t.done}
                disabled={task.busy}
                onChange={() =>
                  void task.run(() =>
                    api<Research>('PATCH', `/research/tasks/${t.id}`, { done: !t.done }),
                  )
                }
              />
              <span data-done={t.done || undefined}>{t.label}</span>
            </label>
            <button
              type="button"
              className="icon-button small"
              aria-label={`Delete task: ${t.label}`}
              disabled={task.busy}
              onClick={() =>
                void task.run(() => api<Research>('DELETE', `/research/tasks/${t.id}`))
              }
            >
              <Icon name="trash" />
            </button>
          </li>
        ))}
      </ul>
      <form
        className="add-task"
        onSubmit={(e) => {
          e.preventDefault();
          const form = e.currentTarget;
          const label = String(new FormData(form).get('label') ?? '').trim();
          if (!label) return;
          void task.run(async () => {
            const result = await api<Research>('POST', `${base}/tasks`, { label });
            form.reset();
            return result;
          });
        }}
      >
        <input
          name="label"
          aria-label="New task"
          placeholder="Add a task…"
          maxLength={200}
          required
        />
        <button className="button" type="submit" disabled={task.busy}>
          Add
        </button>
      </form>
      <ErrorMessage message={task.error} />

      <Notes key={base} path={`${base}/notes`} initial={research.notes} />
    </>
  );
}

type SaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'failed';

const SAVE_LABELS: Record<SaveState, string> = {
  idle: 'Saved on the server',
  pending: 'Editing…',
  saving: 'Saving…',
  saved: 'Saved',
  failed: 'Could not save. Your text is still here; keep typing to retry.',
};

function Notes({ path, initial }: { path: string; initial: string }) {
  const [text, setText] = useState(initial);
  const [state, setState] = useState<SaveState>('idle');
  const unsaved = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const flush = useCallback(async () => {
    clearTimeout(timer.current);
    const body = unsaved.current;
    if (body === null) return;
    unsaved.current = null;
    setState('saving');
    try {
      await api('PUT', path, { body });
      // Typing may have continued while this saved.
      setState(unsaved.current === null ? 'saved' : 'pending');
    } catch {
      unsaved.current ??= body;
      setState('failed');
    }
  }, [path]);

  // Save what is left when the panel closes or the instrument changes.
  useEffect(() => () => void flush(), [flush]);

  return (
    <div className="notes">
      <label className="field">
        <span>Notes</span>
        <textarea
          rows={10}
          maxLength={50000}
          value={text}
          placeholder="Evidence, sources, questions to answer…"
          onChange={(e) => {
            setText(e.target.value);
            unsaved.current = e.target.value;
            setState('pending');
            clearTimeout(timer.current);
            timer.current = setTimeout(() => void flush(), AUTOSAVE_MS);
          }}
          onBlur={() => void flush()}
        />
      </label>
      <p className="save-caption" role="status" data-state={state}>
        {SAVE_LABELS[state]}
      </p>
    </div>
  );
}
