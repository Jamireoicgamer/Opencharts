// SPDX-License-Identifier: AGPL-3.0-or-later
import type { ReactNode } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router';
import { ReauthProvider } from './components/Reauth';
import { TopBar } from './components/TopBar';
import { AccountPage } from './pages/account';
import { Workspace } from './workspace/Workspace';
import { LoginPage } from './pages/Login';
import { RegisterPage } from './pages/Register';
import { SetupPage } from './pages/Setup';
import { useSession } from './session';

function Splash({ message }: { message: string }) {
  return (
    <main className="auth-page">
      <p className="muted" role="status">
        {message}
      </p>
    </main>
  );
}

/** Pages for signed-out visitors: setup (only before the owner exists), sign in, register. */
function Public({ page, children }: { page: 'setup' | 'login' | 'register'; children: ReactNode }) {
  const { session } = useSession();
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/';
  if (session.status === 'loading') return <Splash message="Loading…" />;
  if (session.status === 'error') return <Splash message={session.message} />;
  // Once signed in, continue to the page that sent the visitor here.
  if (session.status === 'signed-in') return <Navigate to={from} replace />;
  if (session.status === 'needs-setup' && page !== 'setup') return <Navigate to="/setup" replace />;
  if (session.status === 'signed-out' && page === 'setup') return <Navigate to="/login" replace />;
  return children;
}

function SignedIn() {
  const { session, desktop } = useSession();
  const location = useLocation();
  if (session.status === 'loading') return <Splash message="Loading…" />;
  if (session.status === 'error') return <Splash message={session.message} />;
  if (session.status === 'needs-setup') return <Navigate to="/setup" replace />;
  if (session.status === 'signed-out')
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  // The owner requires two-factor: nothing else until it is set up.
  if (session.user.mfa_setup_required && location.pathname !== '/account/security')
    return <Navigate to="/account/security" replace />;

  return (
    <ReauthProvider desktop={desktop}>
      <div className="shell">
        <TopBar />
        <Routes>
          <Route index element={<Workspace role={session.user.role} />} />
          <Route path="account/*" element={<AccountPage user={session.user} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </ReauthProvider>
  );
}

export function App() {
  return (
    <Routes>
      <Route
        path="/setup"
        element={
          <Public page="setup">
            <SetupPage />
          </Public>
        }
      />
      <Route
        path="/login"
        element={
          <Public page="login">
            <LoginPage />
          </Public>
        }
      />
      <Route
        path="/register"
        element={
          <Public page="register">
            <RegisterPage />
          </Public>
        }
      />
      <Route path="/*" element={<SignedIn />} />
    </Routes>
  );
}
