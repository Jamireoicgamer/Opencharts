// SPDX-License-Identifier: AGPL-3.0-or-later
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, ApiError, type Me } from './api';

export type SessionState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'needs-setup' }
  | { status: 'signed-out' }
  | { status: 'signed-in'; user: Me };

interface SessionContextValue {
  session: SessionState;
  signedIn: (user: Me) => void;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

async function loadSession(): Promise<SessionState> {
  try {
    const { needs_setup } = await api<{ needs_setup: boolean }>('GET', '/setup/status');
    if (needs_setup) return { status: 'needs-setup' };
    return { status: 'signed-in', user: await api<Me>('GET', '/auth/me') };
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return { status: 'signed-out' };
    return { status: 'error', message: 'Cannot reach the OpenChart server.' };
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionState>({ status: 'loading' });

  const refresh = useCallback(async () => setSession(await loadSession()), []);

  useEffect(() => {
    let active = true;
    void loadSession().then((state) => {
      if (active) setSession(state);
    });
    return () => {
      active = false;
    };
  }, []);

  const signedIn = useCallback((user: Me) => setSession({ status: 'signed-in', user }), []);

  const signOut = useCallback(async () => {
    try {
      await api('POST', '/auth/logout');
    } finally {
      setSession({ status: 'signed-out' });
    }
  }, []);

  return (
    <SessionContext.Provider value={{ session, signedIn, signOut, refresh }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useSession must be used inside <SessionProvider>');
  return value;
}
