// SPDX-License-Identifier: AGPL-3.0-or-later
// The main screen: an icon rail, the instrument on stage, and one panel at a
// time. The open panel is in the URL (?panel=thesis), so links and the back
// button work.
import { useCallback, useEffect, useState, type ComponentType } from 'react';
import { useSearchParams } from 'react-router';
import type { Role } from '../api';
import './workspace.css';
import { ErrorMessage } from '../components/Form';
import { money } from '../format';
import { useSubmit } from '../hooks';
import { ChartArea } from '../market/ChartArea';
import { IndicatorMenu } from '../market/IndicatorMenu';
import { MarketProvider, useConnection, useFiredAlerts, useQuotes } from '../market/hooks';
import { QuoteHeader } from '../market/QuoteHeader';
import type { FiredAlert } from '../market/types';
import { useWorkspace, WorkspaceProvider } from './context';
import { Icon, type IconName } from './Icon';
import { Palette } from './Palette';
import { AiPanel } from './panels/Ai';
import { AlertsPanel } from './panels/Alerts';
import { PortfolioPanel } from './panels/Portfolio';
import { ResearchPanel } from './panels/Research';
import { SettingsPanel } from './panels/Settings';
import { ThesisPanel } from './panels/Thesis';
import { WatchlistPanel } from './panels/Watchlist';
import { ASSET_CLASS_LABELS, PERIODS } from './types';

interface PanelProps {
  onClose: () => void;
  onSearch: () => void;
}

const PANELS = {
  watchlist: { label: 'Watchlist', icon: 'grid', component: WatchlistPanel },
  thesis: { label: 'Thesis', icon: 'bookmark', component: ThesisPanel },
  research: { label: 'Research', icon: 'doc', component: ResearchPanel },
  portfolio: { label: 'Portfolio', icon: 'layers', component: PortfolioPanel },
  alerts: { label: 'Alerts', icon: 'bell', component: AlertsPanel },
  ai: { label: 'AI', icon: 'spark', component: AiPanel },
  settings: { label: 'Settings', icon: 'settings', component: SettingsPanel },
} satisfies Record<string, { label: string; icon: IconName; component: ComponentType<PanelProps> }>;

type PanelName = keyof typeof PANELS;
const isPanel = (value: string | null): value is PanelName => value !== null && value in PANELS;

export function Workspace({ role }: { role: Role }) {
  return (
    <WorkspaceProvider>
      <MarketProvider>
        <WorkspaceLayout canConfigure={role === 'owner' || role === 'admin'} />
      </MarketProvider>
    </WorkspaceProvider>
  );
}

function WorkspaceLayout({ canConfigure }: { canConfigure: boolean }) {
  const { prefs, problem } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const [searching, setSearching] = useState(false);
  const requested = params.get('panel');
  const panel = isPanel(requested) ? requested : null;

  const openPanel = (name: PanelName | null) =>
    setParams(name && name !== panel ? { panel: name } : {}, { replace: panel !== null });

  // Ctrl/⌘ K opens search from anywhere on the page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setSearching(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const Current = panel ? PANELS[panel].component : null;

  return (
    <div className="workspace" data-compact={prefs.compact || undefined}>
      <nav className="rail" aria-label="Workspace">
        <button
          type="button"
          className="rail-button"
          aria-label="Search instruments (Ctrl K)"
          title="Search (Ctrl/⌘ K)"
          onClick={() => setSearching(true)}
        >
          <Icon name="search" />
        </button>
        {(Object.keys(PANELS) as PanelName[]).map((name) => (
          <button
            key={name}
            type="button"
            className="rail-button"
            aria-pressed={panel === name}
            title={PANELS[name].label}
            onClick={() => openPanel(name)}
          >
            <Icon name={PANELS[name].icon} />
            <span className="rail-label">{PANELS[name].label}</span>
          </button>
        ))}
      </nav>

      <Stage onSearch={() => setSearching(true)} canConfigure={canConfigure} />

      {Current && <Current onClose={() => openPanel(null)} onSearch={() => setSearching(true)} />}
      {searching && <Palette onClose={() => setSearching(false)} />}
      {problem && (
        <p className="toast" role="alert">
          {problem}
        </p>
      )}
      <AlertToasts />
    </div>
  );
}

/** "BTC-USD rose above $70,000 · now $70,512" */
export function describeAlert(a: FiredAlert): string {
  const symbol = a.instrument_id.split(':')[1] ?? a.instrument_id;
  const verb = a.direction === 'above' ? 'rose above' : 'fell below';
  return `${symbol} ${verb} ${money(a.level, a.currency)} · now ${money(a.price, a.currency)}`;
}

function AlertToasts() {
  const [fired, setFired] = useState<FiredAlert[]>([]);
  useFiredAlerts(useCallback((alert: FiredAlert) => setFired((list) => [...list, alert]), []));
  if (fired.length === 0) return null;
  return (
    <div className="alert-toasts" role="alert">
      {fired.map((a) => (
        <div key={a.alert_id} className="alert-toast">
          <Icon name="bell" />
          <span>
            <strong>Price alert</strong> {describeAlert(a)}
            {a.note && <small>{a.note}</small>}
          </span>
          <button
            type="button"
            className="icon-button small"
            aria-label="Dismiss alert"
            onClick={() => setFired((list) => list.filter((x) => x.alert_id !== a.alert_id))}
          >
            <Icon name="close" />
          </button>
        </div>
      ))}
    </div>
  );
}

const CONNECTION_LABELS = {
  connecting: 'CONNECTING TO LIVE PRICES',
  live: 'LIVE PRICES',
  polling: 'LIVE CONNECTION UNAVAILABLE · UPDATING EVERY 15 S',
  offline: 'PRICES OFFLINE',
} as const;

function Stage({ onSearch, canConfigure }: { onSearch: () => void; canConfigure: boolean }) {
  const { instrument, prefs, updatePrefs, watchlist, addToWatchlist, removeFromWatchlist } =
    useWorkspace();
  const watching = instrument !== null && watchlist.some((w) => w.id === instrument.id);
  const live = useQuotes(instrument ? [instrument.id] : []);
  const connection = useConnection();
  const current = instrument ? live[instrument.id] : undefined;
  const star = useSubmit(async () => {
    if (!instrument) return;
    await (watching ? removeFromWatchlist(instrument.id) : addToWatchlist(instrument.id));
  });

  return (
    <main className="stage">
      <section className="asset-header">
        {instrument ? (
          <div>
            <div className="overline">
              {instrument.exchange} <span aria-hidden="true">·</span> {instrument.symbol}{' '}
              <span aria-hidden="true">·</span> {ASSET_CLASS_LABELS[instrument.asset_class]}{' '}
              <span aria-hidden="true">·</span> {instrument.currency}
            </div>
            <h1 className="asset-name">
              <button
                type="button"
                onClick={onSearch}
                aria-label={`${instrument.name}. Change instrument`}
              >
                {instrument.name}
                <Icon name="chevron" />
              </button>
            </h1>
          </div>
        ) : (
          <div>
            <div className="overline">NO INSTRUMENT</div>
            <h1 className="asset-name">
              <button type="button" onClick={onSearch}>
                Choose an instrument
                <Icon name="chevron" />
              </button>
            </h1>
          </div>
        )}
        {instrument && (
          <div className="asset-actions">
            <QuoteHeader live={current} currency={instrument.currency} />
            <button
              type="button"
              className="icon-button"
              aria-pressed={watching}
              aria-label={watching ? 'Remove from watchlist' : 'Add to watchlist'}
              title={watching ? 'Remove from watchlist' : 'Add to watchlist'}
              disabled={star.busy}
              onClick={() => void star.run()}
            >
              <Icon name="star" filled={watching} />
            </button>
          </div>
        )}
      </section>
      <ErrorMessage message={star.error} />

      <section className="toolbar" aria-label="Chart options">
        <div className="timeframes" role="group" aria-label="Period">
          {PERIODS.map((p) => (
            <button
              key={p}
              type="button"
              aria-pressed={prefs.period === p}
              onClick={() => void updatePrefs({ period: p })}
            >
              {p}
            </button>
          ))}
        </div>
        <div className="toolbar-actions">
          <button
            type="button"
            className="toolbar-button"
            aria-label={
              prefs.chart_type === 'candle' ? 'Switch to line chart' : 'Switch to candles'
            }
            title={prefs.chart_type === 'candle' ? 'Candles' : 'Line'}
            onClick={() =>
              void updatePrefs({ chart_type: prefs.chart_type === 'candle' ? 'line' : 'candle' })
            }
          >
            <Icon name={prefs.chart_type === 'candle' ? 'candle' : 'line'} />
          </button>
          <IndicatorMenu
            indicators={prefs.indicators}
            onChange={(indicators) => void updatePrefs({ indicators })}
          />
        </div>
      </section>

      <div className="chart-shell">
        {instrument ? (
          <ChartArea
            key={instrument.id}
            instrumentId={instrument.id}
            live={current}
            period={prefs.period}
            chartType={prefs.chart_type}
            showGrid={prefs.show_grid}
            showOhlc={prefs.show_ohlc}
            indicators={prefs.indicators}
            canConfigure={canConfigure}
          />
        ) : (
          <div className="chart-message">
            <Icon name="chart" />
            <h2>Choose an instrument</h2>
            <p>Search with Ctrl/⌘ K, or open your watchlist.</p>
          </div>
        )}
      </div>
      <footer className="stage-footer">
        <span className="footer-status" data-connection={connection}>
          <span className="dot" aria-hidden="true" /> {CONNECTION_LABELS[connection]}
        </span>
        <span className="footer-hint">Ctrl/⌘ K to search</span>
      </footer>
    </main>
  );
}
