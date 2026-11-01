// SPDX-License-Identifier: AGPL-3.0-or-later
import { money } from '../format';
import type { Live } from './hooks';
import { sourceLabel } from './types';

const time = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});
const dateTime = new Intl.DateTimeFormat(undefined, {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
});

/** "14:03:22" today, "31 Oct, 16:30" for older prices. */
export function stamp(iso: string, now = new Date()): string {
  const at = new Date(iso);
  return at.toDateString() === now.toDateString() ? time.format(at) : dateTime.format(at);
}

/** Price, change and where the price came from. Never shown without its source. */
export function QuoteHeader({ live, currency }: { live: Live | undefined; currency: string }) {
  const quote = live?.quote;
  if (!quote) {
    const state = live?.status?.state;
    return (
      <div className="quote" aria-live="polite">
        <div className="quote-meta">
          {state === 'no_source'
            ? 'No price source for this instrument'
            : state === 'error'
              ? 'Price source not responding'
              : 'Waiting for a price…'}
        </div>
      </div>
    );
  }
  const change = quote.change === null ? null : Number(quote.change);
  const direction = change === null || change === 0 ? 'flat' : change > 0 ? 'up' : 'down';
  return (
    <div className="quote" aria-live="polite">
      <div className="quote-line">
        <span className="quote-value">{money(quote.price, currency)}</span>
        {quote.change_pct !== null && (
          <span className="quote-change" data-direction={direction}>
            {change !== null && change > 0 ? '+' : ''}
            {quote.change_pct}%
          </span>
        )}
      </div>
      <div className="quote-meta">
        {sourceLabel(quote)} · {quote.delay === 'realtime' ? '' : 'as of '}
        {stamp(quote.at)}
        {quote.market_state === 'closed' && ' · market closed'}
        {live?.status?.state === 'error' && ' · reconnecting'}
      </div>
    </div>
  );
}
