// SPDX-License-Identifier: AGPL-3.0-or-later
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { color, font, motion } from './tokens';

function rootVariables(css: string): Record<string, string> {
  const block = /:root\s*\{([^}]*)\}/.exec(css)?.[1] ?? '';
  const vars: Record<string, string> = {};
  for (const [, name = '', value = ''] of block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    vars[name] = value.trim();
  }
  return vars;
}

describe('design tokens', () => {
  const css = rootVariables(readFileSync(new URL('./tokens.css', import.meta.url), 'utf8'));

  it('defines every token in tokens.css with the same value', () => {
    const expected = {
      ...Object.fromEntries(Object.entries(color).map(([k, v]) => [`--${k}`, v])),
      ...Object.fromEntries(Object.entries(motion).map(([k, v]) => [`--motion-${k}`, v])),
      ...Object.fromEntries(Object.entries(font).map(([k, v]) => [`--font-${k}`, v])),
    };
    expect(css).toEqual(expected);
  });
});
