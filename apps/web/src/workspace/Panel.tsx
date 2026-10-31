// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useId, useRef, type ReactNode } from 'react';
import { Icon } from './Icon';

/** A side panel: slides in over the chart on wide screens, fills the screen on phones. */
export function Panel({
  eyebrow,
  title,
  subtitle,
  onClose,
  wide = false,
  children,
}: {
  eyebrow: string;
  title: string;
  subtitle?: ReactNode;
  onClose: () => void;
  wide?: boolean;
  children: ReactNode;
}) {
  const titleId = useId();
  const heading = useRef<HTMLHeadingElement>(null);

  // Move focus to the panel so keyboard and screen-reader users land in it.
  useEffect(() => heading.current?.focus(), [title]);

  return (
    <aside
      className="panel"
      data-wide={wide || undefined}
      aria-labelledby={titleId}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose();
      }}
    >
      <header className="panel-header">
        <div>
          <div className="eyebrow">{eyebrow}</div>
          <h2 id={titleId} ref={heading} tabIndex={-1} className="panel-title">
            {title}
          </h2>
          {subtitle && <div className="panel-subtitle">{subtitle}</div>}
        </div>
        <button
          type="button"
          className="icon-button"
          aria-label={`Close ${title}`}
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </header>
      <div className="panel-body">{children}</div>
    </aside>
  );
}

/** The message shown in a panel that needs an instrument when none is chosen. */
export function NoInstrument({ onSearch }: { onSearch: () => void }) {
  return (
    <div className="panel-empty">
      <p>Choose an instrument first.</p>
      <button type="button" className="button" onClick={onSearch}>
        Search instruments
      </button>
    </div>
  );
}
