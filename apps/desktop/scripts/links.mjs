// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Unversioned library names (libpq.so, libpq.dylib) are only for compiling
 * against. Versioned ones (libicudata.so.60, libicudata.68.dylib) are what
 * the PostgreSQL binaries load, so they must be bundled.
 */
export function isDevelopmentLink(target) {
  return /^lib[^.]+\.(so|dylib)$/.test(target.split('/').pop());
}
