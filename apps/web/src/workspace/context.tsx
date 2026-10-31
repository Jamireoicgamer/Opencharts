// SPDX-License-Identifier: AGPL-3.0-or-later
// Workspace state shared by the stage and the panels: preferences, the
// instrument on screen and the watchlist. Everything lives on the server, so
// the same workspace appears in every browser the person signs in from.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { api, ApiError } from '../api';
import { instrumentPath, type Instrument, type Preferences, type WatchlistItem } from './types';

interface WorkspaceValue {
  prefs: Preferences;
  instrument: Instrument | null;
  watchlist: WatchlistItem[];
  /** A problem saving or loading, shown until the next successful change. */
  problem: string | null;
  select: (instrument: Instrument) => void;
  updatePrefs: (change: Partial<Preferences>) => Promise<void>;
  addToWatchlist: (id: string) => Promise<void>;
  removeFromWatchlist: (id: string) => Promise<void>;
  reorderWatchlist: (ids: string[]) => Promise<void>;
  /** Fetch everything again, e.g. after an import. */
  reload: () => void;
}

const WorkspaceContext = createContext<WorkspaceValue | null>(null);

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | {
      status: 'ready';
      prefs: Preferences;
      watchlist: WatchlistItem[];
      instrument: Instrument | null;
    };

type Ready = Extract<LoadState, { status: 'ready' }>;

async function loadWorkspace(): Promise<LoadState> {
  const [prefs, watchlist] = await Promise.all([
    api<Preferences>('GET', '/preferences'),
    api<WatchlistItem[]>('GET', '/watchlist'),
  ]);
  const id = prefs.last_instrument ?? watchlist[0]?.id ?? null;
  let instrument: Instrument | null = watchlist.find((w) => w.id === id) ?? null;
  if (id && !instrument) {
    instrument = await api<Instrument>('GET', instrumentPath(id)).catch(() => null);
  }
  return { status: 'ready', prefs, watchlist, instrument };
}

const failure = (error: unknown) =>
  error instanceof ApiError ? error.message : 'Could not save. Check your connection.';

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [problem, setProblem] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let active = true;
    loadWorkspace().then(
      (loaded) => active && setState(loaded),
      () => active && setState({ status: 'error' }),
    );
    return () => {
      active = false;
    };
  }, [version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  /** Run a change; on success replace part of the state, on failure keep it and explain. */
  const change = useCallback(
    async <T,>(request: () => Promise<T>, apply: (result: T) => Partial<Ready>) => {
      try {
        const result = await request();
        setProblem(null);
        setState((prev) => (prev.status === 'ready' ? { ...prev, ...apply(result) } : prev));
      } catch (error) {
        setProblem(failure(error));
        throw error;
      }
    },
    [],
  );

  const updatePrefs = useCallback(
    async (patch: Partial<Preferences>) => {
      // Show the change at once; the server's answer is the final word.
      setState((prev) =>
        prev.status === 'ready' ? { ...prev, prefs: { ...prev.prefs, ...patch } } : prev,
      );
      try {
        await change(
          () => api<Preferences>('PUT', '/preferences', patch),
          (prefs) => ({ prefs }),
        );
      } catch {
        // Put back what the server has.
        reload();
      }
    },
    [change, reload],
  );

  const value = useMemo<WorkspaceValue | null>(() => {
    if (state.status !== 'ready') return null;
    const setWatchlist = (watchlist: WatchlistItem[]) => ({ watchlist });
    return {
      prefs: state.prefs,
      instrument: state.instrument,
      watchlist: state.watchlist,
      problem,
      select: (instrument) => {
        setState((prev) => (prev.status === 'ready' ? { ...prev, instrument } : prev));
        void updatePrefs({ last_instrument: instrument.id });
      },
      updatePrefs,
      addToWatchlist: (id) =>
        change(
          () => api<WatchlistItem[]>('POST', '/watchlist', { instrument_id: id }),
          setWatchlist,
        ),
      removeFromWatchlist: (id) =>
        change(
          () => api<WatchlistItem[]>('DELETE', `/watchlist/${encodeURIComponent(id)}`),
          setWatchlist,
        ),
      reorderWatchlist: (ids) =>
        change(
          () => api<WatchlistItem[]>('PUT', '/watchlist/order', { instrument_ids: ids }),
          setWatchlist,
        ),
      reload,
    };
  }, [state, problem, change, updatePrefs, reload]);

  if (state.status === 'loading') {
    return (
      <p className="workspace-splash muted" role="status">
        Loading your workspace…
      </p>
    );
  }
  if (!value) {
    return (
      <div className="workspace-splash" role="alert">
        <p className="muted">Could not load your workspace.</p>
        <button type="button" className="button" onClick={reload}>
          Try again
        </button>
      </div>
    );
  }
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceValue {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error('useWorkspace must be used inside <WorkspaceProvider>');
  return value;
}
