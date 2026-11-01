// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { ReauthProvider } from '../components/Reauth';
import { afterEach, describe, expect, it } from 'vitest';
import { amount, money } from '../format';
import { defaultPreferences, mockApi } from '../test-api';
import { summarise } from './panels/Settings';
import type { Alert, Position, Research, ThesisVersion } from './types';
import { Workspace } from './Workspace';

const BAE = {
  id: 'LSE:BA.',
  symbol: 'BA.',
  name: 'BAE Systems',
  exchange: 'LSE',
  currency: 'GBX',
  asset_class: 'equity',
} as const;
const NVDA = {
  id: 'NASDAQ:NVDA',
  symbol: 'NVDA',
  name: 'NVIDIA',
  exchange: 'NASDAQ',
  currency: 'USD',
  asset_class: 'equity',
} as const;
const BTC = {
  id: 'CRYPTO:BTC-USD',
  symbol: 'BTC-USD',
  name: 'Bitcoin',
  exchange: 'CRYPTO',
  currency: 'USD',
  asset_class: 'crypto',
} as const;
const watched = (...items: (typeof BAE | typeof NVDA | typeof BTC)[]) =>
  items.map((i) => ({ ...i, added_at: '2026-10-30T10:00:00Z' }));

/** A workspace on BAE Systems, with the given watchlist and extra routes. */
function onBae(extra: Parameters<typeof mockApi>[0] = {}) {
  // Preferences are kept between calls, like the server does.
  let prefs: object = { ...defaultPreferences, last_instrument: BAE.id };
  return mockApi({
    'GET /preferences': () => [200, prefs],
    'GET /watchlist': [200, watched(BAE, NVDA, BTC)],
    'GET /instruments/LSE%3ABA.': [200, BAE],
    'PUT /preferences': (body) => {
      prefs = { ...prefs, ...(body as object) };
      return [200, prefs];
    },
    ...extra,
  });
}

function renderWorkspace(path = '/', role: 'owner' | 'member' = 'owner') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ReauthProvider>
        <Workspace role={role} />
      </ReauthProvider>
    </MemoryRouter>,
  );
}

const panel = (name: string) => screen.findByRole('complementary', { name });

afterEach(() => localStorage.clear());

describe('stage and search', () => {
  it('starts empty and honest for a new account', async () => {
    mockApi({});
    renderWorkspace();
    expect(await screen.findByRole('button', { name: /Choose an instrument/ })).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'Choose an instrument', level: 2 }),
    ).toBeInTheDocument();
    expect(screen.getByText(/CONNECTING TO LIVE PRICES/)).toBeInTheDocument();
  });

  it('finds an instrument with Ctrl+K and remembers the choice', async () => {
    const api = mockApi({
      'GET /instruments?q=nvi&limit=20': [200, [NVDA]],
      'PUT /preferences': (body) => [200, { ...defaultPreferences, ...(body as object) }],
    });
    renderWorkspace();
    await screen.findByRole('button', { name: /Choose an instrument/ });
    const user = userEvent.setup();
    await user.keyboard('{Control>}k{/Control}');
    const search = screen.getByRole('combobox', { name: 'Search instruments' });
    await user.type(search, 'nvi');
    expect(await screen.findByRole('option', { name: /NVIDIA/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await user.keyboard('{Enter}');
    expect(await screen.findByRole('heading', { name: /NVIDIA/ })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(api.calls.find((c) => c.method === 'PUT')?.body).toEqual({
      last_instrument: NVDA.id,
    });
  });

  it('opens on the last instrument and toggles it on the watchlist', async () => {
    const api = onBae({
      'GET /watchlist': [200, []],
      'POST /watchlist': [201, watched(BAE)],
    });
    renderWorkspace();
    expect(await screen.findByText('BAE Systems')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Add to watchlist' }));
    expect(await screen.findByRole('button', { name: 'Remove from watchlist' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(api.calls.find((c) => c.method === 'POST')?.body).toEqual({ instrument_id: BAE.id });
  });

  it('saves the period and chart type', async () => {
    const api = onBae();
    renderWorkspace();
    await screen.findByText('BAE Systems');
    await userEvent.click(screen.getByRole('button', { name: '1Y' }));
    await userEvent.click(screen.getByRole('button', { name: 'Switch to line chart' }));
    expect(screen.getByRole('button', { name: '1Y' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Switch to candles' })).toBeInTheDocument();
    const puts = api.calls.filter((c) => c.method === 'PUT').map((c) => c.body);
    expect(puts).toEqual([{ period: '1Y' }, { chart_type: 'line' }]);
  });

  it('explains a failed save and keeps the workspace usable', async () => {
    onBae({ 'PUT /preferences': [500] });
    renderWorkspace();
    await screen.findByText('BAE Systems');
    await userEvent.click(screen.getByRole('button', { name: '1Y' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The server had a problem');
  });
});

describe('watchlist', () => {
  it('opens from the rail, selects, reorders and removes', async () => {
    const api = onBae({
      'PUT /watchlist/order': (body) => {
        const ids = (body as { instrument_ids: string[] }).instrument_ids;
        const all = watched(BAE, NVDA, BTC);
        return [200, ids.map((id) => all.find((i) => i.id === id))];
      },
      'DELETE /watchlist/CRYPTO%3ABTC-USD': [200, watched(BAE, NVDA)],
    });
    renderWorkspace();
    await screen.findByText('BAE Systems');
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Watchlist' }));
    const list = within(await panel('Watchlist'));
    expect(list.getByRole('button', { name: /BAE Systems/ })).toHaveAttribute('aria-current');

    await user.click(list.getByRole('button', { name: 'Move NVDA up' }));
    await waitFor(() => expect(list.getAllByRole('listitem')[0]).toHaveTextContent('NVIDIA'));
    expect(api.calls.find((c) => c.path === '/watchlist/order')?.body).toEqual({
      instrument_ids: [NVDA.id, BAE.id, BTC.id],
    });

    await user.click(list.getByRole('button', { name: 'Remove BTC-USD' }));
    await waitFor(() => expect(list.queryByText('Bitcoin')).not.toBeInTheDocument());

    await user.click(list.getByRole('button', { name: /NVIDIA/ }));
    expect(await screen.findByRole('heading', { name: /NVIDIA/, level: 1 })).toBeInTheDocument();
  });

  it('closes with Escape', async () => {
    onBae();
    renderWorkspace('/?panel=watchlist');
    const aside = await panel('Watchlist');
    fireEvent.keyDown(aside, { key: 'Escape' });
    await waitFor(() => expect(aside).not.toBeInTheDocument());
  });
});

const version = (over: Partial<ThesisVersion>): ThesisVersion => ({
  id: 'v1',
  created_at: '2026-10-20T09:00:00Z',
  summary: '',
  key_risk: '',
  bull_case: '',
  bear_case: '',
  fair_value: null,
  entry_price: null,
  conviction: 'not_assessed',
  horizon: 'not_set',
  ...over,
});

describe('thesis', () => {
  it('saves a new version and can load an old one into the editor', async () => {
    const old = version({ summary: 'Rearmament cycle', fair_value: '2200.0000000000' });
    const api = onBae({
      'GET /instruments/LSE%3ABA./thesis': [200, { current: old, history: [old] }],
      'POST /instruments/LSE%3ABA./thesis': (body) => [
        201,
        version({ ...(body as object), id: 'v2', created_at: '2026-10-31T09:00:00Z' }),
      ],
    });
    renderWorkspace('/?panel=thesis');
    const thesis = within(await panel('Thesis'));
    const summary = await thesis.findByLabelText('The investment case');
    expect(summary).toHaveValue('Rearmament cycle');
    expect(thesis.getByLabelText('Fair value (GBX)')).toHaveValue('2200');

    const user = userEvent.setup();
    await user.clear(summary);
    await user.type(summary, 'Orders keep growing');
    await user.selectOptions(thesis.getByLabelText('Conviction'), 'high');
    await user.clear(thesis.getByLabelText('Fair value (GBX)'));
    await user.click(thesis.getByRole('button', { name: 'Save version' }));
    expect(await thesis.findByText('Saved as a new version.')).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === 'POST')?.body).toMatchObject({
      summary: 'Orders keep growing',
      conviction: 'high',
      fair_value: null,
      entry_price: null,
    });

    await user.click(thesis.getByRole('tab', { name: /History/ }));
    expect(thesis.getByRole('tab', { name: /History/ })).toHaveTextContent('2');
    const [newest, oldest] = thesis.getAllByRole('listitem');
    expect(newest).toHaveTextContent('Orders keep growing');
    await user.click(
      within(oldest as HTMLElement).getByRole('button', { name: 'Load into editor' }),
    );
    expect(thesis.getByLabelText('The investment case')).toHaveValue('Rearmament cycle');
  });

  it('asks before deleting the history', async () => {
    const old = version({ summary: 'x' });
    const api = onBae({
      'GET /instruments/LSE%3ABA./thesis': [200, { current: old, history: [old] }],
      'DELETE /instruments/LSE%3ABA./thesis': [204],
    });
    renderWorkspace('/?panel=thesis');
    const thesis = within(await panel('Thesis'));
    const user = userEvent.setup();
    await user.click(await thesis.findByRole('tab', { name: /History/ }));
    await user.click(thesis.getByRole('button', { name: 'Delete thesis history…' }));
    expect(api.calls.some((c) => c.method === 'DELETE')).toBe(false);
    await user.click(thesis.getByRole('button', { name: 'Delete all versions' }));
    expect(await thesis.findByText(/No versions yet/)).toBeInTheDocument();
  });
});

describe('research', () => {
  const research: Research = {
    notes: 'Start',
    updated_at: '2026-10-31T09:00:00Z',
    tasks: [{ id: 't1', label: 'Read results', done: false, position: 0 }],
  };

  it('ticks tasks and saves notes on its own', async () => {
    const api = onBae({
      'GET /instruments/LSE%3ABA./research': [200, research],
      'PATCH /research/tasks/t1': [
        200,
        { ...research, tasks: [{ ...research.tasks[0], done: true }] },
      ],
      'PUT /instruments/LSE%3ABA./research/notes': [200, research],
    });
    renderWorkspace('/?panel=research');
    const pane = within(await panel('Research'));
    const user = userEvent.setup();
    await user.click(await pane.findByRole('checkbox', { name: 'Read results' }));
    await waitFor(() => expect(pane.getByRole('checkbox', { name: 'Read results' })).toBeChecked());

    await user.type(pane.getByLabelText('Notes'), ' and more');
    // Saved after a pause in typing, without leaving the field.
    await waitFor(() => expect(pane.getByText('Saved')).toBeInTheDocument(), { timeout: 3000 });
    expect(api.calls.filter((c) => c.path.endsWith('/notes')).at(-1)?.body).toEqual({
      body: 'Start and more',
    });
  });

  it('keeps the text when a save fails and retries it', async () => {
    let attempts = 0;
    const api = onBae({
      'GET /instruments/LSE%3ABA./research': [200, research],
      'PUT /instruments/LSE%3ABA./research/notes': () => [++attempts === 1 ? 500 : 200, research],
    });
    renderWorkspace('/?panel=research');
    const pane = within(await panel('Research'));
    const notes = await pane.findByLabelText('Notes');
    await userEvent.type(notes, '!');
    fireEvent.blur(notes);
    expect(await pane.findByText(/Could not save/)).toBeInTheDocument();
    expect(notes).toHaveValue('Start!');
    // Leaving the field again sends the unsaved text again.
    fireEvent.blur(notes);
    expect(await pane.findByText('Saved')).toBeInTheDocument();
    const sent = api.calls.filter((c) => c.path.endsWith('/notes')).map((c) => c.body);
    expect(sent).toEqual([{ body: 'Start!' }, { body: 'Start!' }]);
  });
});

describe('portfolio and alerts', () => {
  it('records a holding without inventing a value', async () => {
    const made: Position = {
      id: 'p1',
      instrument: BAE,
      quantity: '120.0000000000',
      average_price: '1985.5000000000',
      account: 'isa',
      note: '',
      created_at: '2026-10-31T09:00:00Z',
      updated_at: '2026-10-31T09:00:00Z',
    };
    const api = onBae({ 'GET /positions': [200, []], 'POST /positions': [201, made] });
    renderWorkspace('/?panel=portfolio');
    const pane = within(await panel('Holdings & risk'));
    expect(await pane.findByText('No holdings recorded yet.')).toBeInTheDocument();
    const user = userEvent.setup();
    await user.type(pane.getByLabelText('Quantity'), '120');
    await user.type(pane.getByLabelText('Average price (GBX)'), '1985.5');
    await user.click(pane.getByRole('button', { name: 'Add holding' }));
    const group = within(await pane.findByRole('region', { name: 'ISA' }));
    expect(group.getByText(/120 units at 1,985.5p · value —/)).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === 'POST')?.body).toEqual({
      instrument_id: BAE.id,
      quantity: '120',
      average_price: '1985.5',
      account: 'isa',
      note: '',
    });
  });

  it('adds and pauses an alert', async () => {
    const alert: Alert = {
      id: 'a1',
      instrument: BAE,
      direction: 'below',
      price: '1800.0000000000',
      note: '',
      active: true,
      created_at: '2026-10-31T09:00:00Z',
      triggered_at: null,
    };
    const api = onBae({
      'GET /alerts': [200, []],
      'POST /alerts': [201, alert],
      'PATCH /alerts/a1': [200, { ...alert, active: false }],
    });
    renderWorkspace('/?panel=alerts');
    const pane = within(await panel('Price alerts'));
    const user = userEvent.setup();
    await user.selectOptions(await pane.findByLabelText('When the price goes'), 'below');
    await user.type(pane.getByLabelText('Price (GBX)'), '1800');
    await user.click(pane.getByRole('button', { name: 'Add alert' }));
    expect(await pane.findByText(/below 1,800p/)).toBeInTheDocument();
    await user.click(pane.getByRole('button', { name: 'Pause' }));
    expect(await pane.findByText('Paused')).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === 'POST')?.body).toEqual({
      instrument_id: BAE.id,
      direction: 'below',
      price: '1800',
      note: '',
    });
  });
});

describe('settings and the prototype import', () => {
  it('finds the prototype data in this browser and imports it', async () => {
    localStorage.setItem('oc-watch-symbols', '["BA."]');
    localStorage.setItem('oc-thesis-BA.', '{"text":"x"}');
    localStorage.setItem('oc-storage-test', '1');
    localStorage.setItem('unrelated', 'keep');
    const api = onBae({
      'POST /import/legacy': [
        200,
        {
          watchlist: 1,
          theses: 1,
          research: 0,
          positions: 0,
          alerts: 0,
          preferences: false,
          skipped_symbols: ['MYSTERY'],
        },
      ],
    });
    renderWorkspace('/?panel=settings');
    const pane = within(await panel('Settings'));
    expect(pane.getByText(/2 saved items/)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(pane.getByRole('button', { name: 'Import from this browser' }));
    // The workspace reloads after an import; find the panel again.
    const after = within(await panel('Settings'));
    expect(
      await after.findByText(/Imported 1 watchlist item, 1 thesis version\. .*MYSTERY/),
    ).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === '/import/legacy')?.body).toEqual({
      format: 'localstorage',
      items: { 'oc-watch-symbols': '["BA."]', 'oc-thesis-BA.': '{"text":"x"}' },
    });

    await user.click(after.getByRole('button', { name: /Remove the prototype/ }));
    expect(localStorage.getItem('oc-watch-symbols')).toBeNull();
    expect(localStorage.getItem('unrelated')).toBe('keep');
  });

  it('rejects an upload that is not JSON before sending it', async () => {
    const api = onBae();
    renderWorkspace('/?panel=settings');
    const pane = within(await panel('Settings'));
    expect(pane.getByText(/No prototype data found/)).toBeInTheDocument();
    const file = new File(['not json'], 'openchart-workspace.json', { type: 'application/json' });
    await userEvent.upload(pane.getByLabelText('Upload openchart-workspace.json'), file);
    expect(await pane.findByRole('alert')).toHaveTextContent('That file is not valid JSON.');
    expect(api.calls.some((c) => c.path === '/import/legacy')).toBe(false);
  });

  it('syncs appearance settings to the server', async () => {
    const api = onBae();
    renderWorkspace('/?panel=settings');
    const pane = within(await panel('Settings'));
    await userEvent.click(pane.getByRole('checkbox', { name: /Compact layout/ }));
    expect(api.calls.find((c) => c.method === 'PUT')?.body).toEqual({ compact: true });
  });
});

describe('formatting', () => {
  it('keeps decimal strings exact', () => {
    expect(amount('1234567.5000000000')).toBe('1,234,567.5');
    expect(amount('0.0000000100')).toBe('0.00000001');
    expect(money('1985.5000000000', 'GBX')).toBe('1,985.5p');
    expect(money('70000.0000000000', 'USD')).toBe('$70,000');
    expect(money('5.0000000000', 'JPY')).toBe('5 JPY');
  });

  it('summarises an import', () => {
    expect(
      summarise({
        watchlist: 0,
        theses: 0,
        research: 0,
        positions: 0,
        alerts: 0,
        preferences: false,
        skipped_symbols: [],
      }),
    ).toBe('Nothing new to import.');
  });
});
