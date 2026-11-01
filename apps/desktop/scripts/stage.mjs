// SPDX-License-Identifier: AGPL-3.0-or-later
// Gathers what the desktop app bundles into apps/desktop/build:
//   postgres/  official PostgreSQL 16 binaries for this platform, from the
//              @embedded-postgres npm packages (pinned, hash-checked by the
//              pnpm lockfile), trimmed to what the app runs
//   api/       the frozen API (build it first: apps/api/scripts/freeze.py)
//   web/       the built web app (pnpm --filter @opencharts/web build)
import {
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
} from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isDevelopmentLink } from './links.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const desktop = resolve(here, '..');
const build = join(desktop, 'build');
const platform = process.platform === 'win32' ? 'windows' : process.platform;
const key = `${platform}-${process.arch}`;
const exe = process.platform === 'win32' ? '.exe' : '';

function fail(message) {
  console.error(`stage: ${message}`);
  process.exit(1);
}

function size(path) {
  const stat = statSync(path);
  if (!stat.isDirectory()) return stat.size;
  return readdirSync(path).reduce((total, name) => total + size(join(path, name)), 0);
}

// Postgres.
const pkg = join(desktop, 'node_modules', '@embedded-postgres', key);
if (!existsSync(join(pkg, 'native'))) {
  fail(`no PostgreSQL build for ${key}; run pnpm install on that platform`);
}
const postgres = join(build, 'postgres');
rmSync(postgres, { recursive: true, force: true });
cpSync(join(pkg, 'native'), postgres, { recursive: true, dereference: true });
// The package records symlinks separately; bundles can't rely on links, so copy.
const links = join(postgres, 'pg-symlinks.json');
if (existsSync(links)) {
  for (const { source, target } of JSON.parse(readFileSync(links, 'utf8'))) {
    if (isDevelopmentLink(target)) continue;
    const from = join(postgres, source.replace(/^native\//, ''));
    const to = join(postgres, target.replace(/^native\//, ''));
    if (!existsSync(to)) cpSync(from, to);
  }
  rmSync(links);
}
// Only the server and the tools the app runs.
const keep = new Set(['postgres', 'initdb', 'pg_ctl'].map((name) => name + exe));
for (const name of readdirSync(join(postgres, 'bin'))) {
  const isLibrary = name.endsWith('.dll') && !/^wx|^testplug/i.test(name);
  if (!keep.has(name) && !isLibrary) rmSync(join(postgres, 'bin', name));
}
rmSync(join(postgres, 'include'), { recursive: true, force: true });
// Static libraries, build metadata and the embedded-SQL client libraries
// aren't used by the server.
for (const name of readdirSync(join(postgres, 'lib'))) {
  if (/\.(a|lib)$|^pkgconfig$|^lib(ecpg|pgtypes)/.test(name)) {
    rmSync(join(postgres, 'lib', name), { recursive: true });
  }
}
for (const name of ['postgres', 'initdb', 'pg_ctl']) {
  if (!existsSync(join(postgres, 'bin', name + exe))) fail(`PostgreSQL package has no ${name}`);
}
cpSync(join(desktop, 'licenses', 'PostgreSQL.txt'), join(postgres, 'LICENSE-PostgreSQL.txt'));

// The frozen API.
const api = join(build, 'api', `openchart-api${exe}`);
if (!existsSync(api) || !statSync(api).isFile()) {
  fail('no frozen API; run: uv sync --group desktop && uv run python apps/api/scripts/freeze.py');
}

// The web app.
const dist = resolve(desktop, '..', 'web', 'dist');
if (!existsSync(join(dist, 'index.html'))) {
  fail('no web build; run: pnpm --filter @opencharts/web build');
}
const web = join(build, 'web');
rmSync(web, { recursive: true, force: true });
mkdirSync(web, { recursive: true });
cpSync(dist, web, { recursive: true });

const mb = (path) => `${(size(path) / 1e6).toFixed(0)} MB`;
console.log(
  `staged for ${key}: postgres ${mb(postgres)}, api ${mb(join(build, 'api'))}, web ${mb(web)}`,
);
