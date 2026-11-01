// SPDX-License-Identifier: AGPL-3.0-or-later
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import { api, ApiError } from '../api';
import { MarketStream, type Connection } from './stream';
import type { FeedStatus, FiredAlert, History, Quote } from './types';

const StreamContext = createContext<MarketStream | null>(null);

/** Opens the shared live-price connection for everything below it. */
export function MarketProvider({
  children,
  stream: given,
}: {
  children: ReactNode;
  stream?: MarketStream;
}) {
  const [stream] = useState(() => given ?? new MarketStream());
  useEffect(() => () => stream.close(), [stream]);
  return <StreamContext.Provider value={stream}>{children}</StreamContext.Provider>;
}

function useStream(): MarketStream {
  const stream = useContext(StreamContext);
  if (!stream) throw new Error('useStream must be used inside <MarketProvider>');
  return stream;
}

export interface Live {
  quote: Quote | undefined;
  status: FeedStatus | undefined;
}

/** Live quotes and feed status for these instruments, kept up to date. */
export function useQuotes(ids: string[]): Record<string, Live> {
  const stream = useStream();
  const key = ids.join(',');
  useEffect(() => (key ? stream.watch(key.split(',')) : undefined), [stream, key]);
  const version = useSyncExternalStore(
    useCallback((onChange) => stream.subscribe(onChange), [stream]),
    () => stream.version,
  );
  return useMemo(() => {
    const result: Record<string, Live> = {};
    for (const id of key ? key.split(',') : []) {
      result[id] = { quote: stream.quotes.get(id), status: stream.statuses.get(id) };
    }
    return result;
    // `version` changes whenever the stream's maps do.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream, key, version]);
}

export function useConnection(): Connection {
  const stream = useStream();
  return useSyncExternalStore(
    useCallback((onChange) => stream.subscribe(onChange), [stream]),
    () => stream.connection,
  );
}

/** Calls back when one of this user's price alerts fires. */
export function useFiredAlerts(callback: (alert: FiredAlert) => void): void {
  const stream = useStream();
  useEffect(() => stream.onAlert(callback), [stream, callback]);
}

export type CandleState =
  | { status: 'loading' }
  | { status: 'ready'; history: History }
  | { status: 'no_source' }
  | { status: 'error' };

/** Price history for a chart period. */
export function useCandles(id: string | null, period: string) {
  const [attempt, setAttempt] = useState(0);
  const key = id ? `${id}|${period}|${attempt}` : null;
  const [result, setResult] = useState<{ key: string; state: CandleState } | null>(null);
  useEffect(() => {
    if (!key || !id) return;
    let active = true;
    api<History>('GET', `/market/candles/${encodeURIComponent(id)}?period=${period}`).then(
      (history) => active && setResult({ key, state: { status: 'ready', history } }),
      (error: unknown) => {
        if (!active) return;
        const noSource = error instanceof ApiError && error.message === 'no_source';
        setResult({ key, state: { status: noSource ? 'no_source' : 'error' } });
      },
    );
    return () => {
      active = false;
    };
  }, [key, id, period]);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const state: CandleState = result?.key === key ? result.state : { status: 'loading' };
  return { state, retry };
}
