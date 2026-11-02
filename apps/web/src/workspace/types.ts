// SPDX-License-Identifier: AGPL-3.0-or-later
// Shapes returned by the workspace API. Amounts arrive as decimal strings so
// nothing is lost to floating point.

export type AssetClass = 'equity' | 'etf' | 'crypto' | 'fx' | 'index';

export interface Instrument {
  id: string;
  symbol: string;
  name: string;
  exchange: string;
  currency: string;
  asset_class: AssetClass;
}

export interface WatchlistItem extends Instrument {
  added_at: string;
}

export type Conviction = 'not_assessed' | 'low' | 'moderate' | 'high';
export type Horizon = 'not_set' | 'under_1y' | '1_3y' | '3_5y' | 'over_5y';

export interface ThesisInput {
  summary: string;
  key_risk: string;
  bull_case: string;
  bear_case: string;
  fair_value: string | null;
  entry_price: string | null;
  conviction: Conviction;
  horizon: Horizon;
}

export interface ThesisVersion extends ThesisInput {
  id: string;
  created_at: string;
}

export interface Thesis {
  current: ThesisVersion | null;
  history: ThesisVersion[];
}

export interface ResearchTask {
  id: string;
  label: string;
  done: boolean;
  position: number;
}

export interface Research {
  notes: string;
  updated_at: string;
  tasks: ResearchTask[];
}

export type Account = 'isa' | 'gia' | 'sipp' | 'other';

export interface Position {
  id: string;
  instrument: Instrument;
  quantity: string;
  average_price: string | null;
  account: Account;
  note: string;
  created_at: string;
  updated_at: string;
}

export interface Alert {
  id: string;
  instrument: Instrument;
  direction: 'above' | 'below';
  price: string;
  note: string;
  active: boolean;
  created_at: string;
  triggered_at: string | null;
}

export const PERIODS = ['1D', '1W', '1M', '3M', '1Y', 'ALL'] as const;
export type Period = (typeof PERIODS)[number];
export type RiskProfile = 'conservative' | 'balanced' | 'aggressive';

export type IndicatorKind = 'sma' | 'ema' | 'bollinger' | 'vwap' | 'volume' | 'rsi' | 'macd';

export interface Indicator {
  kind: IndicatorKind;
  /** The period for SMA, EMA, Bollinger and RSI; null for the others. */
  period: number | null;
}

export interface Preferences {
  chart_type: 'candle' | 'line';
  period: Period;
  show_grid: boolean;
  show_ohlc: boolean;
  compact: boolean;
  risk_profile: RiskProfile;
  last_instrument: string | null;
  indicators: Indicator[];
}

export interface ImportResult {
  watchlist: number;
  theses: number;
  research: number;
  positions: number;
  alerts: number;
  drawings?: number;
  preferences: boolean;
  skipped_symbols: string[];
}

/** Path segment for an instrument id such as `LSE:BA.`. */
export const instrumentPath = (id: string) => `/instruments/${encodeURIComponent(id)}`;

export const CONVICTION_LABELS: Record<Conviction, string> = {
  not_assessed: 'Not assessed',
  low: 'Low',
  moderate: 'Moderate',
  high: 'High',
};

export const HORIZON_LABELS: Record<Horizon, string> = {
  not_set: 'Not set',
  under_1y: 'Less than 1 year',
  '1_3y': '1–3 years',
  '3_5y': '3–5 years',
  over_5y: '5+ years',
};

export const ACCOUNT_LABELS: Record<Account, string> = {
  isa: 'ISA',
  gia: 'General account',
  sipp: 'SIPP',
  other: 'Other',
};

export const ASSET_CLASS_LABELS: Record<AssetClass, string> = {
  equity: 'Equity',
  etf: 'ETF',
  crypto: 'Crypto',
  fx: 'FX',
  index: 'Index',
};
