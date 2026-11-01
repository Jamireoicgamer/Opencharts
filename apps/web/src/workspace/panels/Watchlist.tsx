// SPDX-License-Identifier: AGPL-3.0-or-later
import { useSubmit } from '../../hooks';
import { money } from '../../format';
import { useQuotes } from '../../market/hooks';
import { ErrorMessage } from '../../components/Form';
import { useWorkspace } from '../context';
import { Icon } from '../Icon';
import { Panel } from '../Panel';
import { ASSET_CLASS_LABELS } from '../types';

export function WatchlistPanel({
  onClose,
  onSearch,
}: {
  onClose: () => void;
  onSearch: () => void;
}) {
  const { watchlist, instrument, select, removeFromWatchlist, reorderWatchlist } = useWorkspace();
  const action = useSubmit(async (work: () => Promise<void>) => work());
  const live = useQuotes(watchlist.map((w) => w.id));

  function move(index: number, by: -1 | 1) {
    const ids = watchlist.map((w) => w.id);
    const [moved] = ids.splice(index, 1);
    if (!moved) return;
    ids.splice(index + by, 0, moved);
    void action.run(() => reorderWatchlist(ids));
  }

  return (
    <Panel
      eyebrow="WORKSPACE / 01"
      title="Watchlist"
      subtitle="Follow only what matters."
      onClose={onClose}
    >
      {watchlist.length === 0 ? (
        <div className="panel-empty">
          <p>Your watchlist is empty.</p>
          <button type="button" className="button" onClick={onSearch}>
            Find instruments
          </button>
        </div>
      ) : (
        <ul className="watch-list" aria-label="Watchlist">
          {watchlist.map((item, index) => (
            <li
              key={item.id}
              className="watch-item"
              data-current={item.id === instrument?.id || undefined}
            >
              <button
                type="button"
                className="watch-select"
                aria-current={item.id === instrument?.id ? 'true' : undefined}
                onClick={() => select(item)}
              >
                <span className="ticker">{item.symbol}</span>
                <span className="watch-name">{item.name}</span>
                <span className="watch-meta">
                  {item.exchange} · {ASSET_CLASS_LABELS[item.asset_class]} · {item.currency}
                </span>
                <WatchPrice live={live[item.id]} currency={item.currency} />
              </button>
              <div className="watch-actions">
                <button
                  type="button"
                  className="icon-button small"
                  aria-label={`Move ${item.symbol} up`}
                  disabled={index === 0 || action.busy}
                  onClick={() => move(index, -1)}
                >
                  <Icon name="up" />
                </button>
                <button
                  type="button"
                  className="icon-button small"
                  aria-label={`Move ${item.symbol} down`}
                  disabled={index === watchlist.length - 1 || action.busy}
                  onClick={() => move(index, 1)}
                >
                  <Icon name="down" />
                </button>
                <button
                  type="button"
                  className="icon-button small"
                  aria-label={`Remove ${item.symbol}`}
                  disabled={action.busy}
                  onClick={() => void action.run(() => removeFromWatchlist(item.id))}
                >
                  <Icon name="trash" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <ErrorMessage message={action.error} />
      <button type="button" className="panel-action" onClick={onSearch}>
        <Icon name="plus" /> Add instruments
      </button>
    </Panel>
  );
}

function WatchPrice({
  live,
  currency,
}: {
  live: ReturnType<typeof useQuotes>[string] | undefined;
  currency: string;
}) {
  const quote = live?.quote;
  if (!quote) {
    return (
      <span className="watch-price muted">
        {live?.status?.state === 'no_source' ? 'no source' : '—'}
      </span>
    );
  }
  const pct = quote.change_pct === null ? null : Number(quote.change_pct);
  return (
    <span className="watch-price">
      <span>{money(quote.price, currency)}</span>
      {pct !== null && (
        <span data-direction={pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat'}>
          {pct > 0 ? '+' : ''}
          {quote.change_pct}%
        </span>
      )}
    </span>
  );
}
