// SPDX-License-Identifier: AGPL-3.0-or-later
import { lazy, Suspense } from 'react';
import { Link } from 'react-router';
import type { Indicator } from '../workspace/types';
import { useCandles, type Live } from './hooks';
import { useDrawings } from './useDrawings';
import { SOURCE_LABELS } from './types';

// The chart library is loaded on first use, keeping the first page load small.
const PriceChart = lazy(() => import('./Chart').then((m) => ({ default: m.PriceChart })));

export function ChartArea({
  instrumentId,
  live,
  period,
  chartType,
  showGrid,
  showOhlc,
  indicators,
  canConfigure,
}: {
  instrumentId: string;
  live: Live | undefined;
  period: string;
  chartType: 'candle' | 'line';
  showGrid: boolean;
  showOhlc: boolean;
  indicators: Indicator[];
  /** Owners and admins can turn sources on, so they get a link to do it. */
  canConfigure: boolean;
}) {
  const { state, retry } = useCandles(instrumentId, period);
  const drawings = useDrawings(instrumentId);

  if (state.status === 'loading') {
    return (
      <div className="chart-message" role="status">
        <p className="muted">Loading prices…</p>
      </div>
    );
  }
  if (state.status === 'no_source') {
    return (
      <div className="chart-message">
        <h2>No data source covers this instrument</h2>
        <p>
          {canConfigure ? (
            <>
              Turn one on in <Link to="?panel=settings">Settings → Data sources</Link>. UK and US
              shares need Yahoo Finance (delayed) or a Twelve Data key.
            </>
          ) : (
            'Ask the owner of this server to turn on a data source for it.'
          )}
        </p>
      </div>
    );
  }
  if (state.status === 'error') {
    return (
      <div className="chart-message" role="alert">
        <h2>Prices are unavailable right now</h2>
        <p>Every source for this instrument failed to answer.</p>
        <button type="button" className="button" onClick={retry}>
          Try again
        </button>
      </div>
    );
  }
  const { history } = state;
  if (history.candles.length === 0) {
    return (
      <div className="chart-message">
        <h2>No trading in this period</h2>
        <p>Choose a longer period.</p>
      </div>
    );
  }
  return (
    <>
      <Suspense
        fallback={
          <div className="chart-message" role="status">
            <p className="muted">Loading chart…</p>
          </div>
        }
      >
        <PriceChart
          history={history}
          quote={live?.quote}
          chartType={chartType}
          showGrid={showGrid}
          showOhlc={showOhlc}
          indicators={indicators}
          drawings={drawings}
        />
      </Suspense>
      <p className="chart-source">
        History: {history.sources.map((s) => SOURCE_LABELS[s] ?? s).join(', ') || 'saved prices'}
        {history.stale && ' · sources not responding, showing saved prices'}
        <span className="chart-credit">
          Chart by{' '}
          <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">
            TradingView
          </a>
        </span>
      </p>
    </>
  );
}
