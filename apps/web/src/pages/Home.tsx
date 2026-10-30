// SPDX-License-Identifier: AGPL-3.0-or-later
export function HomePage() {
  return (
    <main className="chart-area">
      <div className="empty-chart">
        <h1>No data source connected</h1>
        <p>
          Live market data arrives in milestone M3. Nothing on this screen is simulated, so there is
          nothing to show yet.
        </p>
      </div>
    </main>
  );
}
