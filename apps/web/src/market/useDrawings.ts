// SPDX-License-Identifier: AGPL-3.0-or-later
// The user's drawings for one instrument, saved on the server.
import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import type { Drawing, DrawingInput } from './drawings';

export interface DrawingsApi {
  drawings: Drawing[];
  error: string | null;
  add: (input: DrawingInput) => Promise<Drawing | null>;
  change: (id: string, patch: Partial<Pick<Drawing, 'points' | 'color' | 'text'>>) => Promise<void>;
  remove: (id: string) => Promise<void>;
  clear: () => Promise<void>;
}

export function useDrawings(instrumentId: string): DrawingsApi {
  const base = `/instruments/${encodeURIComponent(instrumentId)}/drawings`;
  const [state, setState] = useState<{ base: string; drawings: Drawing[] }>({ base, drawings: [] });
  const [error, setError] = useState<string | null>(null);
  const fail = useCallback((e: unknown) => {
    setError(e instanceof Error ? e.message : 'The drawing could not be saved.');
  }, []);

  const reload = useCallback(() => {
    api<Drawing[]>('GET', base).then(
      (drawings) => setState({ base, drawings }),
      (e: unknown) => fail(e),
    );
  }, [base, fail]);

  useEffect(() => {
    let active = true;
    api<Drawing[]>('GET', base).then(
      (drawings) => active && setState({ base, drawings }),
      (e: unknown) => active && fail(e),
    );
    return () => {
      active = false;
    };
  }, [base, fail]);

  const set = useCallback(
    (update: (drawings: Drawing[]) => Drawing[]) =>
      setState((s) => (s.base === base ? { base, drawings: update(s.drawings) } : s)),
    [base],
  );

  const add = useCallback(
    async (input: DrawingInput) => {
      setError(null);
      try {
        const created = await api<Drawing>('POST', base, input);
        set((d) => [...d, created]);
        return created;
      } catch (e) {
        fail(e);
        return null;
      }
    },
    [base, set, fail],
  );

  const change = useCallback(
    async (id: string, patch: Partial<Pick<Drawing, 'points' | 'color' | 'text'>>) => {
      setError(null);
      // Show the change at once; the server's copy replaces it.
      set((d) => d.map((x) => (x.id === id ? { ...x, ...patch } : x)));
      try {
        const saved = await api<Drawing>('PATCH', `${base}/${id}`, patch);
        set((d) => d.map((x) => (x.id === id ? saved : x)));
      } catch (e) {
        fail(e);
        reload();
      }
    },
    [base, set, fail, reload],
  );

  const remove = useCallback(
    async (id: string) => {
      setError(null);
      set((d) => d.filter((x) => x.id !== id));
      try {
        await api('DELETE', `${base}/${id}`);
      } catch (e) {
        fail(e);
        reload();
      }
    },
    [base, set, fail, reload],
  );

  const clear = useCallback(async () => {
    setError(null);
    set(() => []);
    try {
      await api('DELETE', base);
    } catch (e) {
      fail(e);
      reload();
    }
  }, [base, set, fail, reload]);

  return {
    drawings: state.base === base ? state.drawings : [],
    error,
    add,
    change,
    remove,
    clear,
  };
}
