// SPDX-License-Identifier: AGPL-3.0-or-later
// OpenChart's service worker. It makes the app installable and lets the app
// shell open without a connection. It never stores anything from /api/:
// account and market data always come from the server, and nothing personal
// is left in the browser's cache after signing out.

const SHELL_CACHE = 'openchart-shell-v1';
const ASSET_CACHE = 'openchart-assets-v1';
const MAX_ASSETS = 80;

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.add('/'))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  const keep = new Set([SHELL_CACHE, ASSET_CACHE]);
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((n) => !keep.has(n)).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

async function trim(cache) {
  const keys = await cache.keys();
  await Promise.all(
    keys.slice(0, Math.max(0, keys.length - MAX_ASSETS)).map((k) => cache.delete(k)),
  );
}

/** Pages: the network first, so a deploy shows at once; the cached shell when offline. */
async function page(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(SHELL_CACHE);
      await cache.put('/', response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match('/');
    return cached ?? Response.error();
  }
}

/** Build assets have content hashes in their names, so a cached copy is never stale. */
async function asset(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    const cache = await caches.open(ASSET_CACHE);
    await cache.put(request, response.clone());
    await trim(cache);
  }
  return response;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) return; // Always the network, never cached.
  if (request.mode === 'navigate') event.respondWith(page(request));
  else if (url.pathname.startsWith('/assets/')) event.respondWith(asset(request));
});
