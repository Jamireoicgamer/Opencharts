// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { Link } from 'react-router';
import { api } from '../../api';
import { ErrorMessage } from '../../components/Form';
import { useSubmit } from '../../hooks';
import { useWorkspace } from '../context';
import { clearLegacyData, findLegacyData, readExportFile } from '../legacy';
import { Panel } from '../Panel';
import { DataSources } from './DataSources';
import type { ImportResult, Preferences } from '../types';

type Toggle = 'show_grid' | 'show_ohlc' | 'compact';

const TOGGLES: { key: Toggle; title: string; detail: string }[] = [
  { key: 'show_grid', title: 'Chart grid', detail: 'Subtle horizontal reference lines' },
  {
    key: 'show_ohlc',
    title: 'Crosshair values',
    detail: 'Open, high, low and close when hovering',
  },
  { key: 'compact', title: 'Compact layout', detail: 'Give the chart more room on small screens' },
];

function download(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function summarise(result: ImportResult): string {
  const parts = [
    [result.watchlist, 'watchlist item'],
    [result.theses, 'thesis version'],
    [result.research, 'research page'],
    [result.positions, 'holding'],
    [result.alerts, 'alert'],
    [result.drawings ?? 0, 'drawing'],
  ]
    .filter(([n]) => Number(n) > 0)
    .map(([n, label]) => `${n} ${label}${n === 1 ? '' : 's'}`);
  if (result.preferences) parts.push('preferences');
  const added = parts.length > 0 ? `Imported ${parts.join(', ')}.` : 'Nothing new to import.';
  const skipped =
    result.skipped_symbols.length > 0
      ? ` Not in the catalogue yet, so skipped: ${result.skipped_symbols.join(', ')}.`
      : '';
  return added + skipped;
}

export function SettingsPanel({ onClose }: { onClose: () => void }) {
  const { prefs, updatePrefs, reload } = useWorkspace();
  const [legacy, setLegacy] = useState(findLegacyData);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [imported, setImported] = useState(false);

  const exporter = useSubmit(async () => {
    const data = await api<unknown>('GET', '/export');
    download(data, `openchart-export-${new Date().toISOString().slice(0, 10)}.json`);
  });
  const importer = useSubmit(async (payload: () => Promise<object>, fromBrowser: boolean) => {
    setOutcome(null);
    const data = await payload();
    // Our own exports (from the desktop app or a server) and the prototype's
    // files go to different importers.
    const path =
      (data as { format?: unknown }).format === 'openchart-export' ? '/import' : '/import/legacy';
    const result = await api<ImportResult>('POST', path, data);
    setOutcome(summarise(result));
    setImported(fromBrowser);
    reload();
  });

  return (
    <Panel
      eyebrow="WORKSPACE"
      title="Settings"
      subtitle="Saved to your account on this server."
      onClose={onClose}
    >
      <h3 className="list-heading">Appearance</h3>
      <div className="settings-list">
        {TOGGLES.map(({ key, title, detail }) => (
          <label key={key} className="setting-line">
            <span>
              <strong>{title}</strong>
              <small>{detail}</small>
            </span>
            <input
              type="checkbox"
              checked={prefs[key]}
              onChange={(e) =>
                void updatePrefs({ [key]: e.target.checked } as Partial<Preferences>)
              }
            />
          </label>
        ))}
      </div>

      <h3 className="list-heading" id="data-sources">
        Data sources
      </h3>
      <DataSources />

      <h3 className="list-heading">Your data</h3>
      <p className="helper">
        Download everything in your workspace as JSON: watchlist, theses with every version,
        research, holdings, alerts, chart drawings and preferences. Import the file into OpenChart
        anywhere else, such as the desktop app or a server, to move your workspace there.
      </p>
      <button
        type="button"
        className="button"
        disabled={exporter.busy}
        onClick={() => void exporter.run()}
      >
        Export my workspace
      </button>
      <ErrorMessage message={exporter.error} />
      <label className="field">
        <span>Import an OpenChart export</span>
        <input
          type="file"
          accept="application/json,.json"
          disabled={importer.busy}
          onChange={(e) => {
            const input = e.currentTarget;
            const file = input.files?.[0];
            if (!file) return;
            void importer
              .run(() => readExportFile(file), false)
              .finally(() => {
                input.value = '';
              });
          }}
        />
      </label>
      <ErrorMessage message={importer.error} />
      {outcome && (
        <div className="notice" role="status">
          <p>{outcome} Importing again adds nothing twice.</p>
          {imported && legacy && (
            <button
              type="button"
              className="button ghost"
              onClick={() => {
                clearLegacyData();
                setLegacy(null);
                setImported(false);
              }}
            >
              Remove the prototype&rsquo;s copy from this browser
            </button>
          )}
        </div>
      )}

      <h3 className="list-heading">Import from the prototype</h3>
      {legacy ? (
        <div className="notice">
          <p>
            This browser has data from the OpenChart prototype ({Object.keys(legacy.items).length}{' '}
            saved items). Import it into your account to keep it.
          </p>
          <div className="row-inline">
            <button
              type="button"
              className="button primary"
              disabled={importer.busy}
              onClick={() => void importer.run(async () => legacy, true)}
            >
              Import from this browser
            </button>
          </div>
        </div>
      ) : (
        <p className="helper">
          No prototype data found in this browser. If you used the prototype elsewhere, choose
          &ldquo;Export workspace&rdquo; there and import the file above.
        </p>
      )}
      <h3 className="list-heading">Account</h3>
      <p className="helper">
        Sign-in methods, two-factor, sessions and API keys are on the{' '}
        <Link to="/account">account page</Link>.
      </p>
    </Panel>
  );
}
