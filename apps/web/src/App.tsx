// SPDX-License-Identifier: AGPL-3.0-or-later
import { useApiHealth, type ApiHealth } from './useApiHealth';

const statusLabel: Record<ApiHealth['state'], string> = {
  checking: 'API: checking',
  ok: 'API: ok',
  unreachable: 'API: unreachable',
};

export function App() {
  const health = useApiHealth();

  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand">
          <svg className="brand-mark" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3 3v18h18M6.5 15.5l4.2-4.2 3.5 2.2L20 6" />
          </svg>
          OpenChart AI
        </span>
        <span
          className="status"
          data-state={health.state}
          role="status"
          title={health.state === 'ok' ? `API version ${health.version}` : undefined}
        >
          {statusLabel[health.state]}
        </span>
      </header>
      <main className="chart-area">
        <div className="empty-chart">
          <h1>No data source connected</h1>
          <p>
            Live market data arrives in milestone M3. Nothing on this screen is simulated, so there
            is nothing to show yet.
          </p>
        </div>
      </main>
    </div>
  );
}
