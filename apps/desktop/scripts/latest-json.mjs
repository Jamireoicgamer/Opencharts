// SPDX-License-Identifier: AGPL-3.0-or-later
// Writes the updater's latest.json from the CI installers:
//   node latest-json.mjs <installers dir> <version> <owner/repo> <tag>
// Each platform's folder holds its update bundle and the bundle's .sig
// (the signature the app checks against its built-in public key).
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const [dir, version, repo, tag] = process.argv.slice(2);
if (!dir || !version || !repo || !tag) {
  console.error('usage: latest-json.mjs <installers dir> <version> <owner/repo> <tag>');
  process.exit(1);
}

// Which file the updater installs on each platform.
const BUNDLE = {
  'windows-x86_64': (name) => name.endsWith('-setup.exe'),
  'darwin-aarch64': (name) => name.endsWith('.app.tar.gz'),
  'darwin-x86_64': (name) => name.endsWith('.app.tar.gz'),
};

const platforms = {};
for (const [platform, isBundle] of Object.entries(BUNDLE)) {
  const folder = join(dir, `openchart-${platform}`);
  if (!existsSync(folder)) continue;
  const bundle = readdirSync(folder).find(isBundle);
  if (!bundle || !existsSync(join(folder, `${bundle}.sig`))) continue;
  platforms[platform] = {
    signature: readFileSync(join(folder, `${bundle}.sig`), 'utf8').trim(),
    url: `https://github.com/${repo}/releases/download/${tag}/${encodeURIComponent(bundle)}`,
  };
}

if (Object.keys(platforms).length === 0) {
  console.error('latest-json: no signed update bundles found (is the update key configured?)');
  process.exit(1);
}

console.log(
  JSON.stringify(
    {
      version,
      notes: `OpenChart desktop ${version}`,
      pub_date: new Date().toISOString(),
      platforms,
    },
    null,
    2,
  ),
);
