// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useEffect, useState } from 'react';
import { ApiError } from './api';
import { passkeyErrorMessage } from './webauthn';

/** Thrown when the person closes a dialog; not an error worth showing. */
export class Cancelled extends Error {
  constructor() {
    super('Cancelled');
    this.name = 'Cancelled';
  }
}

/** Runs an async submit handler with a busy flag and a user-facing error message. */
export function useSubmit<T extends unknown[]>(handler: (...args: T) => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(...args: T) {
    setBusy(true);
    setError(null);
    try {
      await handler(...args);
    } catch (err) {
      if (err instanceof Cancelled) return;
      setError(
        err instanceof ApiError
          ? err.message
          : (passkeyErrorMessage(err) ?? 'Something went wrong. Try again.'),
      );
    } finally {
      setBusy(false);
    }
  }

  return { busy, error, run };
}

/** Loads data from the API; `reload()` fetches it again. */
export function useLoad<T>(load: () => Promise<T>) {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({
    data: null,
    error: null,
  });
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    load().then(
      (data) => {
        if (active) setState({ data, error: null });
      },
      () => {
        if (active) setState((prev) => ({ ...prev, error: 'Could not load this list.' }));
      },
    );
    return () => {
      active = false;
    };
  }, [load, version]);
  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { ...state, reload };
}
