// SPDX-License-Identifier: AGPL-3.0-or-later
import { NavLink, Navigate, Route, Routes } from 'react-router';
import type { Me } from '../../api';
import { Activity } from './Activity';
import { ApiKeys } from './ApiKeys';
import { Invites } from './Invites';
import { Security } from './Security';
import { Sessions } from './Sessions';

export function AccountPage({ user }: { user: Me }) {
  const canInvite = user.role === 'owner' || user.role === 'admin';
  return (
    <main className="account">
      <header className="account-head">
        <h1>{user.display_name}</h1>
        <p className="muted">
          {user.email} · {user.role}
        </p>
      </header>
      <nav className="tabs" aria-label="Account sections">
        <NavLink to="/account/security">Security</NavLink>
        <NavLink to="/account/sessions">Devices</NavLink>
        <NavLink to="/account/keys">API keys</NavLink>
        {canInvite && <NavLink to="/account/invites">Invites</NavLink>}
        <NavLink to="/account/activity">Activity</NavLink>
      </nav>
      <Routes>
        <Route index element={<Navigate to="sessions" replace />} />
        <Route path="security" element={<Security user={user} />} />
        <Route path="sessions" element={<Sessions />} />
        <Route path="keys" element={<ApiKeys />} />
        {canInvite && <Route path="invites" element={<Invites user={user} />} />}
        <Route path="activity" element={<Activity />} />
        <Route path="*" element={<Navigate to="sessions" replace />} />
      </Routes>
    </main>
  );
}
