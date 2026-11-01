// SPDX-License-Identifier: AGPL-3.0-or-later
// Renders the PNG app icons from public/icon.svg. Run after changing the icon:
//   node apps/web/scripts/render-icons.mjs
// The PNGs are committed, so builds do not need a browser.
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const pub = join(dirname(fileURLToPath(import.meta.url)), '..', 'public');
const svg = await readFile(join(pub, 'icon.svg'), 'utf8');
const markOnly = svg.replace(/<rect[^>]*\/>/, '');

// Maskable icons are cropped to a circle or squircle by the OS: full-bleed
// background, with the mark inside the central 80% safe zone.
const maskable = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" fill="#08090b"/><g transform="translate(76.8 76.8) scale(0.7)">${markOnly.replace(/^<svg[^>]*>|<\/svg>$/g, '')}</g></svg>`;

const outputs = [
  ['icon-192.png', 192, svg],
  ['icon-512.png', 512, svg],
  ['icon-maskable-512.png', 512, maskable],
  ['apple-touch-icon.png', 180, maskable],
];

const browser = await chromium.launch();
for (const [name, size, source] of outputs) {
  const page = await browser.newPage({ viewport: { width: size, height: size } });
  const html = `<style>html,body{margin:0;background:transparent}svg{display:block;width:${size}px;height:${size}px}</style>${source}`;
  await page.setContent(html);
  await page.screenshot({ path: join(pub, name), omitBackground: true });
  await page.close();
}
await browser.close();
console.log('Rendered', outputs.map(([n]) => n).join(', '));
