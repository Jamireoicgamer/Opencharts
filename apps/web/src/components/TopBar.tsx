// SPDX-License-Identifier: AGPL-3.0-or-later
import { Link, NavLink } from 'react-router';
import { useSession } from '../session';
import { useApiHealth, type ApiHealth } from '../useApiHealth';

const statusLabel: Record<ApiHealth['state'], string> = {
  checking: 'API: checking',
  ok: 'API: ok',
  unreachable: 'API: unreachable',
};

export function TopBar() {
  const health = useApiHealth();
  const { session, signOut } = useSession();

  return (
    <header className="topbar">
      <Link to="/" className="brand">
        <svg className="brand-mark" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M3 3v18h18M6.5 15.5l4.2-4.2 3.5 2.2L20 6" />
        </svg>
        OpenChart AI
      </Link>
      <div className="topbar-actions">
        <span
          className="status"
          data-state={health.state}
          role="status"
          title={health.state === 'ok' ? `API version ${health.version}` : undefined}
        >
          {statusLabel[health.state]}
        </span>
        {session.status === 'signed-in' && (
          <>
            <NavLink to="/account" className="nav-link">
              {session.user.display_name}
            </NavLink>
            <button type="button" className="button ghost" onClick={() => void signOut()}>
              Sign out
            </button>
          </>
        )}
      </div>
    </header>
  );
}
