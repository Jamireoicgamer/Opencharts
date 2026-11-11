// SPDX-License-Identifier: AGPL-3.0-or-later
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { api, ApiError, MFA_SETUP_REQUIRED_EVENT, SESSION_ENDED_EVENT, type Me } from './api';
import { desktopSignIn, desktopToken, takeDesktopToken } from './desktop';

export type SessionState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'needs-setup' }
  | { status: 'signed-out' }
  | { status: 'signed-in'; user: Me };

interface SessionContextValue {
  session: SessionState;
  /** The desktop app: signed in by its launch token, so no sign-out. */
  desktop: boolean;
  signedIn: (user: Me) => void;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

interface Loaded {
  state: SessionState;
  desktop: boolean;
}

async function loadSession(): Promise<Loaded> {
  takeDesktopToken();
  let desktop = false;
  try {
    const status = await api<{ needs_setup: boolean; desktop?: boolean }>('GET', '/setup/status');
    // Only trust a stored token when the server says it is the desktop app.
    const token = status.desktop ? desktopToken() : null;
    desktop = token !== null;
    if (token && status.needs_setup) return await signedInBy(token);
    if (status.needs_setup) return { state: { status: 'needs-setup' }, desktop };
    try {
      return { state: { status: 'signed-in', user: await api<Me>('GET', '/auth/me') }, desktop };
    } catch (error) {
      if (token && error instanceof ApiError && error.status === 401)
        return await signedInBy(token);
      throw error;
    }
  } catch (error) {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403))
      return { state: { status: 'signed-out' }, desktop: false };
    return { state: { status: 'error', message: 'Cannot reach the OpenChart server.' }, desktop };
  }
}

async function signedInBy(token: string): Promise<Loaded> {
  return { state: { status: 'signed-in', user: await desktopSignIn(token) }, desktop: true };
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionState>({ status: 'loading' });
  const [desktop, setDesktop] = useState(false);
  const current = useRef(session);
  useEffect(() => {
    current.current = session;
  }, [session]);

  const apply = useCallback((loaded: Loaded) => {
    setSession(loaded.state);
    setDesktop(loaded.desktop);
  }, []);
  const refresh = useCallback(async () => apply(await loadSession()), [apply]);

  useEffect(() => {
    let active = true;
    void loadSession().then((loaded) => {
      if (active) apply(loaded);
    });
    return () => {
      active = false;
    };
  }, [apply]);

  // A 401 from any request means the session is gone (signed out on another
  // device, or expired): show the sign-in page instead of a broken screen.
  // The desktop app signs straight back in instead.
  useEffect(() => {
    const reload = () => void loadSession().then(apply);
    const ended = () => {
      if (current.current.status !== 'signed-in') return;
      if (desktop) {
        setSession({ status: 'loading' });
        reload();
      } else {
        setSession({ status: 'signed-out' });
      }
    };
    // The owner may make two-factor mandatory while this user is signed in:
    // reload who we are, so the app sends them to set it up.
    window.addEventListener(SESSION_ENDED_EVENT, ended);
    window.addEventListener(MFA_SETUP_REQUIRED_EVENT, reload);
    return () => {
      window.removeEventListener(SESSION_ENDED_EVENT, ended);
      window.removeEventListener(MFA_SETUP_REQUIRED_EVENT, reload);
    };
  }, [apply, desktop]);

  const signedIn = useCallback((user: Me) => setSession({ status: 'signed-in', user }), []);

  const signOut = useCallback(async () => {
    try {
      await api('POST', '/auth/logout');
    } finally {
      setSession({ status: 'signed-out' });
    }
  }, []);

  return (
    <SessionContext.Provider value={{ session, desktop, signedIn, signOut, refresh }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useSession must be used inside <SessionProvider>');
  return value;
}
