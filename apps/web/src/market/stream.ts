// SPDX-License-Identifier: AGPL-3.0-or-later
// One live connection per tab: a WebSocket to /api/market/stream that the
// whole app shares. Components say which instruments they watch; the
// connection keeps the server's subscription in sync, reconnects with
// backoff, and while it is down polls /api/market/quotes instead, so prices
// keep updating (more slowly) behind proxies that block WebSockets.
import { api } from '../api';
import type { FeedStatus, FiredAlert, Quote, QuoteResult } from './types';

export type Connection = 'connecting' | 'live' | 'polling' | 'offline';

type Listener = () => void;
type AlertListener = (alert: FiredAlert) => void;

export const POLL_MS = 15_000;
const MAX_BACKOFF_MS = 30_000;
/** After this many failed connection attempts in a row, poll until one succeeds. */
const FAILURES_BEFORE_POLLING = 2;

export interface SocketLike {
  readyState: number;
  onopen: ((ev: Event) => void) | null;
  onclose: ((ev: CloseEvent) => void) | null;
  onmessage: ((ev: MessageEvent) => void) | null;
  send(data: string): void;
  close(): void;
}

export type SocketFactory = (url: string) => SocketLike;

const OPEN = 1;

function defaultUrl(): string {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${scheme}//${window.location.host}/api/market/stream`;
}

export class MarketStream {
  quotes = new Map<string, Quote>();
  statuses = new Map<string, FeedStatus>();
  connection: Connection = 'connecting';
  /** Bumped on every change, so React can tell when to re-render. */
  version = 0;

  private counts = new Map<string, number>();
  private listeners = new Set<Listener>();
  private alertListeners = new Set<AlertListener>();
  private socket: SocketLike | null = null;
  private failures = 0;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private pollTimer: ReturnType<typeof setInterval> | undefined;
  private closed = false;

  constructor(
    private readonly makeSocket: SocketFactory = (url) => new WebSocket(url),
    private readonly url: string = defaultUrl(),
  ) {
    this.connect();
  }

  // Subscriptions ---------------------------------------------------------

  /** Watch instruments; returns a function that stops watching them. */
  watch(ids: string[]): () => void {
    const added = ids.filter((id) => {
      const n = this.counts.get(id) ?? 0;
      this.counts.set(id, n + 1);
      return n === 0;
    });
    if (added.length > 0) {
      this.sendCommand('watch', added);
      if (this.connection === 'polling') void this.poll(added);
    }
    return () => {
      const removed = ids.filter((id) => {
        const n = (this.counts.get(id) ?? 1) - 1;
        if (n <= 0) this.counts.delete(id);
        else this.counts.set(id, n);
        return n <= 0;
      });
      if (removed.length > 0) this.sendCommand('unwatch', removed);
    };
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  onAlert(listener: AlertListener): () => void {
    this.alertListeners.add(listener);
    return () => this.alertListeners.delete(listener);
  }

  close(): void {
    this.closed = true;
    clearTimeout(this.retryTimer);
    clearInterval(this.pollTimer);
    this.socket?.close();
  }

  // Internals ---------------------------------------------------------------

  private emit(): void {
    this.version += 1;
    for (const listener of this.listeners) listener();
  }

  private setConnection(state: Connection): void {
    if (this.connection === state) return;
    this.connection = state;
    if (state === 'polling') this.startPolling();
    else if (state === 'live') this.stopPolling();
    this.emit();
  }

  private sendCommand(type: 'watch' | 'unwatch', ids: string[]): void {
    if (this.socket?.readyState === OPEN) this.socket.send(JSON.stringify({ type, ids }));
  }

  private connect(): void {
    if (this.closed) return;
    let socket: SocketLike;
    try {
      socket = this.makeSocket(this.url);
    } catch {
      this.scheduleRetry();
      return;
    }
    this.socket = socket;
    socket.onopen = () => {
      this.failures = 0;
      this.setConnection('live');
      const ids = [...this.counts.keys()];
      if (ids.length > 0) this.sendCommand('watch', ids);
    };
    socket.onmessage = (event) => this.handle(event.data);
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.scheduleRetry();
    };
  }

  private scheduleRetry(): void {
    if (this.closed) return;
    this.failures += 1;
    if (this.failures >= FAILURES_BEFORE_POLLING) this.setConnection('polling');
    else this.setConnection('connecting');
    const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** (this.failures - 1));
    this.retryTimer = setTimeout(() => this.connect(), delay);
  }

  private handle(raw: unknown): void {
    if (typeof raw !== 'string') return;
    let message: { type?: string } & Record<string, unknown>;
    try {
      message = JSON.parse(raw);
    } catch {
      return;
    }
    switch (message.type) {
      case 'quote': {
        const quote = message as unknown as Quote;
        this.quotes.set(quote.instrument_id, quote);
        this.emit();
        break;
      }
      case 'status': {
        const status = message as unknown as FeedStatus;
        this.statuses.set(status.instrument_id, status);
        this.emit();
        break;
      }
      case 'alert':
        for (const listener of this.alertListeners) listener(message as unknown as FiredAlert);
        break;
    }
  }

  private startPolling(): void {
    if (this.pollTimer !== undefined) return;
    void this.poll([...this.counts.keys()]);
    this.pollTimer = setInterval(() => void this.poll([...this.counts.keys()]), POLL_MS);
  }

  private stopPolling(): void {
    clearInterval(this.pollTimer);
    this.pollTimer = undefined;
  }

  private async poll(ids: string[]): Promise<void> {
    for (let i = 0; i < ids.length; i += 50) {
      const batch = ids.slice(i, i + 50);
      let results: QuoteResult[];
      try {
        results = await api<QuoteResult[]>(
          'GET',
          `/market/quotes?ids=${batch.map(encodeURIComponent).join(',')}`,
        );
      } catch {
        if (this.connection === 'polling') this.setConnection('offline');
        return;
      }
      for (const r of results) {
        if (r.quote) {
          this.quotes.set(r.instrument_id, r.quote);
          this.statuses.set(r.instrument_id, {
            instrument_id: r.instrument_id,
            state: 'live',
            source: r.quote.source,
          });
        } else {
          this.statuses.set(r.instrument_id, {
            instrument_id: r.instrument_id,
            state: r.reason === 'no_source' ? 'no_source' : 'error',
            source: null,
          });
        }
      }
      if (this.connection === 'offline') this.setConnection('polling');
      this.emit();
    }
  }
}
