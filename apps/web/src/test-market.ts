// SPDX-License-Identifier: AGPL-3.0-or-later
// Test doubles for market data: a WebSocket the test drives, and a stand-in
// for the chart library (jsdom has no canvas). Installed in test-setup.ts.
import { vi } from 'vitest';

export class FakeSocket {
  static instances: FakeSocket[] = [];
  readyState = 0;
  sent: unknown[] = [];
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  static get last(): FakeSocket {
    const socket = FakeSocket.instances.at(-1);
    if (!socket) throw new Error('No socket was opened');
    return socket;
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }

  close(): void {
    this.readyState = 3;
  }

  // Test controls ----------------------------------------------------------
  open(): void {
    this.readyState = 1;
    this.onopen?.(new Event('open'));
  }

  receive(message: unknown): void {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(message) }));
  }

  drop(): void {
    this.readyState = 3;
    this.onclose?.(new CloseEvent('close'));
  }
}

export interface FakeChart {
  options: Record<string, unknown>;
  series: { kind: string; data: unknown[]; updates: unknown[] }[];
  removed: boolean;
}

export const charts: FakeChart[] = [];

export const chartModule = {
  ColorType: { Solid: 'solid' },
  CrosshairMode: { Normal: 0 },
  CandlestickSeries: { type: 'Candlestick' },
  LineSeries: { type: 'Line' },
  createChart: vi.fn((_el: HTMLElement, options: Record<string, unknown>) => {
    const chart: FakeChart = { options, series: [], removed: false };
    charts.push(chart);
    return {
      addSeries: (definition: { type: string }) => {
        const entry = { kind: definition.type, data: [] as unknown[], updates: [] as unknown[] };
        chart.series.push(entry);
        return {
          setData: (data: unknown[]) => {
            entry.data = data;
          },
          update: (bar: unknown) => entry.updates.push(bar),
        };
      },
      timeScale: () => ({ fitContent: () => undefined }),
      subscribeCrosshairMove: () => undefined,
      remove: () => {
        chart.removed = true;
      },
    };
  }),
};
