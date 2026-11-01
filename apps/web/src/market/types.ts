// SPDX-License-Identifier: AGPL-3.0-or-later
// Market data from the API. Amounts are decimal strings, as elsewhere.

export type Delay = 'realtime' | 'delayed' | 'eod';

export interface Quote {
  instrument_id: string;
  price: string;
  previous_close: string | null;
  change: string | null;
  change_pct: string | null;
  currency: string;
  at: string;
  source: string;
  delay: Delay;
  delay_minutes: number | null;
  market_state: 'open' | 'closed' | 'unknown';
}

export type FeedState = 'connecting' | 'live' | 'no_source' | 'error';

export interface FeedStatus {
  instrument_id: string;
  state: FeedState;
  source: string | null;
}

export interface FiredAlert {
  alert_id: string;
  instrument_id: string;
  direction: 'above' | 'below';
  level: string;
  price: string;
  currency: string;
  note: string;
  at: string;
}

export interface QuoteResult {
  instrument_id: string;
  quote: Quote | null;
  reason: 'no_source' | 'unavailable' | null;
}

export interface Candle {
  t: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string | null;
}

export interface History {
  instrument_id: string;
  period: string;
  interval: '5m' | '1h' | '1d';
  candles: Candle[];
  sources: string[];
  stale: boolean;
}

export type Provider = 'coinbase' | 'kraken' | 'yahoo' | 'twelvedata';

export interface SourceInfo {
  provider: Provider;
  label: string;
  coverage: string;
  active: boolean;
  // Only for owners and admins:
  enabled: boolean | null;
  priority: number | null;
  needs_terms: boolean;
  terms_accepted: boolean | null;
  needs_key: boolean;
  key_hint: string | null;
}

export const SOURCE_LABELS: Record<string, string> = {
  coinbase: 'Coinbase',
  kraken: 'Kraken',
  yahoo: 'Yahoo Finance',
  twelvedata: 'Twelve Data',
};

/** "Coinbase · real-time" / "Yahoo Finance · delayed 15 min" / "… · delayed" */
export function sourceLabel(q: Pick<Quote, 'source' | 'delay' | 'delay_minutes'>): string {
  const source = SOURCE_LABELS[q.source] ?? q.source;
  if (q.delay === 'realtime') return `${source} · real-time`;
  if (q.delay === 'eod') return `${source} · end of day`;
  return q.delay_minutes ? `${source} · delayed ${q.delay_minutes} min` : `${source} · delayed`;
}
