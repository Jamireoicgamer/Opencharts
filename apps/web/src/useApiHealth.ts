// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react';

export type ApiHealth =
  { state: 'checking' } | { state: 'ok'; version: string } | { state: 'unreachable' };

export function useApiHealth(): ApiHealth {
  const [health, setHealth] = useState<ApiHealth>({ state: 'checking' });

  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/health', { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = (await res.json()) as { status?: string; version?: string };
        if (body.status !== 'ok') throw new Error('Unexpected health response');
        setHealth({ state: 'ok', version: body.version ?? 'unknown' });
      })
      .catch(() => {
        if (!controller.signal.aborted) setHealth({ state: 'unreachable' });
      });
    return () => controller.abort();
  }, []);

  return health;
}
