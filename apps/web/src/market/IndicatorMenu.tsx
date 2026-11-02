// SPDX-License-Identifier: AGPL-3.0-or-later
// Chooses the chart's indicators. They're saved in preferences, so they
// follow the user to every device.
import { useEffect, useId, useRef, useState } from 'react';
import { Icon } from '../workspace/Icon';
import type { Indicator, IndicatorKind } from '../workspace/types';
import { INDICATOR_KINDS, MAX_INDICATORS, indicatorLabel } from './indicators';

export function IndicatorMenu({
  indicators,
  onChange,
}: {
  indicators: Indicator[];
  onChange: (next: Indicator[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<IndicatorKind>('ema');
  const [period, setPeriod] = useState('20');
  const menu = useRef<HTMLDivElement>(null);
  const id = useId();
  const spec = INDICATOR_KINDS.find((k) => k.kind === kind);
  const needsPeriod = spec?.period != null;
  const periodValue = Number(period);
  const periodOk =
    !needsPeriod || (Number.isInteger(periodValue) && periodValue >= 2 && periodValue <= 400);
  const candidate: Indicator = { kind, period: needsPeriod ? periodValue : null };
  const duplicate = indicators.some(
    (i) => i.kind === candidate.kind && i.period === candidate.period,
  );
  const full = indicators.length >= MAX_INDICATORS;

  // Close on Escape or a click outside.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    const onClick = (e: MouseEvent) => {
      if (menu.current && !menu.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onClick);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onClick);
    };
  }, [open]);

  return (
    <div className="indicator-menu" ref={menu}>
      <button
        type="button"
        className="toolbar-button"
        aria-expanded={open}
        aria-controls={id}
        aria-label="Indicators"
        title="Indicators"
        onClick={() => setOpen((o) => !o)}
      >
        <Icon name="indicators" />
        {indicators.length > 0 && <span className="count">{indicators.length}</span>}
      </button>
      {open && (
        <div className="indicator-popover" id={id} role="group" aria-label="Indicators">
          {indicators.length === 0 ? (
            <p className="muted">No indicators on the chart.</p>
          ) : (
            <ul className="indicator-list">
              {indicators.map((i, index) => (
                <li key={`${i.kind}-${i.period}`}>
                  <span>{indicatorLabel(i)}</span>
                  <button
                    type="button"
                    className="icon-button small"
                    aria-label={`Remove ${indicatorLabel(i)}`}
                    onClick={() => onChange(indicators.filter((_, j) => j !== index))}
                  >
                    <Icon name="close" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <form
            className="indicator-add"
            onSubmit={(e) => {
              e.preventDefault();
              if (periodOk && !duplicate && !full) onChange([...indicators, candidate]);
            }}
          >
            <label className="field compact">
              <span>Indicator</span>
              <select
                value={kind}
                onChange={(e) => {
                  const next = e.target.value as IndicatorKind;
                  setKind(next);
                  const p = INDICATOR_KINDS.find((k) => k.kind === next)?.period;
                  if (p != null) setPeriod(String(p));
                }}
              >
                {INDICATOR_KINDS.map((k) => (
                  <option key={k.kind} value={k.kind}>
                    {k.name}
                  </option>
                ))}
              </select>
            </label>
            {needsPeriod && (
              <label className="field compact period">
                <span>Period</span>
                <input
                  type="number"
                  inputMode="numeric"
                  min={2}
                  max={400}
                  value={period}
                  onChange={(e) => setPeriod(e.target.value)}
                />
              </label>
            )}
            <button className="button" type="submit" disabled={!periodOk || duplicate || full}>
              Add
            </button>
          </form>
          {full && <p className="helper">Up to {MAX_INDICATORS} indicators.</p>}
          {duplicate && !full && (
            <p className="helper">{indicatorLabel(candidate)} is already on.</p>
          )}
        </div>
      )}
    </div>
  );
}
