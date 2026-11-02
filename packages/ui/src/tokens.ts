// SPDX-License-Identifier: AGPL-3.0-or-later
// Design tokens carried over from the V4.1 prototype (legacy/index.html).
// tokens.css defines the same values as CSS custom properties; the test
// keeps the two in sync.

export const color = {
  bg: '#08090b',
  surface: '#101215',
  panel: '#111317',
  raised: '#191c21',
  border: '#22252a',
  line: '#25282d',
  muted: '#848991',
  text: '#f4f5f6',
  green: '#39c7a1',
  red: '#e87780',
  accent: '#b4abff',
  // Indicator lines, distinct from the candles and from each other.
  amber: '#e8b65a',
  blue: '#6aaef2',
  pink: '#e98fc6',
} as const;

export const motion = {
  fast: '110ms',
  normal: '170ms',
  panel: '200ms',
  ease: 'cubic-bezier(0.22, 1, 0.36, 1)',
} as const;

export const font = {
  sans: "Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
} as const;
