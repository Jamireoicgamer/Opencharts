// SPDX-License-Identifier: AGPL-3.0-or-later
// Data left by the V4.1 prototype (legacy/index.html), which kept everything
// in this browser's localStorage under "oc-*" keys. The server does the
// mapping and validation; this file only finds and packages the data.

import { UserError } from '../hooks';

const PREFIX = 'oc-';
const IGNORED = new Set(['oc-storage-test']);
/** The prototype's data is small; anything bigger is not what we are looking for. */
export const MAX_IMPORT_BYTES = 1_000_000;

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null; // Blocked by browser settings.
  }
}

function legacyKeys(store: Storage): string[] {
  const keys: string[] = [];
  for (let i = 0; i < store.length; i++) {
    const key = store.key(i);
    if (key?.startsWith(PREFIX) && !IGNORED.has(key)) keys.push(key);
  }
  return keys;
}

/** The prototype's items in this browser, or null when there are none. */
export function findLegacyData(): { format: 'localstorage'; items: Record<string, string> } | null {
  const store = storage();
  if (!store) return null;
  const items: Record<string, string> = {};
  for (const key of legacyKeys(store)) {
    const value = store.getItem(key);
    if (value !== null) items[key] = value;
  }
  return Object.keys(items).length > 0 ? { format: 'localstorage', items } : null;
}

/** Remove the prototype's copy once it is safely on the server. */
export function clearLegacyData(): void {
  const store = storage();
  if (!store) return;
  for (const key of legacyKeys(store)) store.removeItem(key);
}

/** Read an uploaded `openchart-workspace.json`. Throws a readable message. */
export async function readExportFile(file: File): Promise<Record<string, unknown>> {
  if (file.size > MAX_IMPORT_BYTES)
    throw new UserError('That file is too large to be a prototype export.');
  let parsed: unknown;
  try {
    parsed = JSON.parse(await file.text());
  } catch {
    throw new UserError('That file is not valid JSON.');
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new UserError('That file is not a prototype export.');
  }
  return parsed as Record<string, unknown>;
}
