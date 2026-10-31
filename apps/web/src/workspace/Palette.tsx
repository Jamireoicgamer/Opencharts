// SPDX-License-Identifier: AGPL-3.0-or-later
// Ctrl/⌘ K: search the instrument catalogue and jump to one.
import { useEffect, useId, useRef, useState } from 'react';
import { api } from '../api';
import { useWorkspace } from './context';
import { Icon } from './Icon';
import { ASSET_CLASS_LABELS, type Instrument } from './types';

const DEBOUNCE_MS = 150;

export function Palette({ onClose }: { onClose: () => void }) {
  const { watchlist, select } = useWorkspace();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Instrument[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [active, setActive] = useState(0);
  const listId = useId();
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const q = query.trim();
    if (!q) return;
    let current = true;
    const timer = setTimeout(() => {
      api<Instrument[]>('GET', `/instruments?q=${encodeURIComponent(q)}&limit=20`).then(
        (found) => {
          if (!current) return;
          setResults(found);
          setFailed(false);
          setActive(0);
        },
        () => current && setFailed(true),
      );
    }, DEBOUNCE_MS);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [query]);

  // With no query, offer the watchlist.
  const options: Instrument[] = query.trim() ? (results ?? []) : watchlist;
  const heading = query.trim() ? 'Instruments' : 'Your watchlist';

  function choose(instrument: Instrument | undefined) {
    if (!instrument) return;
    select(instrument);
    onClose();
  }

  return (
    <div
      className="dialog-backdrop palette-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="palette" role="dialog" aria-modal="true" aria-label="Search instruments">
        <div className="palette-input">
          <Icon name="search" />
          <input
            ref={input}
            autoFocus
            role="combobox"
            aria-label="Search instruments"
            aria-expanded="true"
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={options[active] ? `${listId}-${active}` : undefined}
            placeholder="Search by ticker or company…"
            value={query}
            maxLength={60}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') onClose();
              else if (e.key === 'ArrowDown') {
                e.preventDefault();
                setActive((i) => Math.min(i + 1, options.length - 1));
              } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setActive((i) => Math.max(i - 1, 0));
              } else if (e.key === 'Enter') {
                e.preventDefault();
                choose(options[active]);
              }
            }}
          />
          <kbd>Esc</kbd>
        </div>
        <div className="palette-head" aria-hidden="true">
          {heading}
        </div>
        <ul id={listId} role="listbox" aria-label={heading} className="palette-list">
          {options.map((item, index) => (
            <li
              key={item.id}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              className="palette-option"
              onMouseEnter={() => setActive(index)}
              onClick={() => choose(item)}
            >
              <span className="ticker">{item.symbol}</span>
              <span className="palette-name">{item.name}</span>
              <span className="palette-meta">
                {item.exchange} · {ASSET_CLASS_LABELS[item.asset_class]}
              </span>
            </li>
          ))}
        </ul>
        <p className="palette-foot muted" role="status">
          {query.trim() && failed
            ? 'Search failed. Check your connection.'
            : query.trim() && results?.length === 0
              ? 'Nothing matches. More markets arrive with data sources in M3.'
              : !query.trim() && watchlist.length === 0
                ? 'Type a ticker such as NVDA, or a name such as Rolls-Royce.'
                : '↑ ↓ to move · Enter to open'}
        </p>
      </div>
    </div>
  );
}
