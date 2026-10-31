// SPDX-License-Identifier: AGPL-3.0-or-later
// Small typed client for the OpenChart API. A generated client replaces it in M2.

export type Role = 'owner' | 'admin' | 'member';

export interface Me {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  /** The owner requires two-factor and this user has not set it up yet. */
  mfa_setup_required?: boolean;
}

export type SecondFactor = 'totp' | 'passkey' | 'recovery';

export interface MfaRequired {
  mfa_required: true;
  methods: SecondFactor[];
}

export const needsSecondFactor = (r: Me | MfaRequired): r is MfaRequired => 'mfa_required' in r;

export interface PasskeyInfo {
  id: string;
  name: string;
  backed_up: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface SecurityStatus {
  has_password: boolean;
  totp: boolean;
  passkeys: PasskeyInfo[];
  google_email: string | null;
  recovery_codes_left: number;
  require_mfa: boolean;
  google_available: boolean;
}

export interface TotpSetup {
  secret: string;
  uri: string;
  qr_svg: string;
}

export interface RecoveryCodes {
  recovery_codes: string[] | null;
}

export interface SessionInfo {
  id: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  user_agent: string | null;
  ip: string | null;
  current: boolean;
}

export interface Invite {
  id: string;
  email: string | null;
  role: 'admin' | 'member';
  created_at: string;
  expires_at: string;
  used_at: string | null;
}

export interface CreatedInvite extends Invite {
  token: string;
}

export interface SecretInfo {
  name: string;
  provider: string | null;
  hint: string;
  created_at: string;
  updated_at: string;
}

export interface AuditEvent {
  id: number;
  user_id: string | null;
  action: string;
  target: string | null;
  ip: string | null;
  user_agent: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

interface ValidationIssue {
  loc?: (string | number)[];
  msg?: string;
}

/** Dispatched on window when the API says the session is gone (signed out elsewhere, expired). */
export const SESSION_ENDED_EVENT = 'openchart:session-ended';
/** Dispatched when the owner has made two-factor mandatory and this user has none yet. */
export const MFA_SETUP_REQUIRED_EVENT = 'openchart:mfa-setup-required';
/** API detail for actions that need the user to confirm who they are again. */
export const REAUTH_REQUIRED = 'reauth_required';

function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const issue = detail[0] as ValidationIssue;
    const field = issue.loc?.at(-1);
    return field
      ? `${String(field).replace('_', ' ')}: ${issue.msg ?? 'invalid'}`
      : (issue.msg ?? 'Invalid input');
  }
  if (status === 429) return 'Too many attempts. Try again later.';
  return status >= 500 ? 'The server had a problem. Try again.' : `Request failed (${status})`;
}

export async function api<T = void>(
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    credentials: 'same-origin',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    // Not JSON: an error page from the proxy (e.g. 429 or 502). Keep parsed null.
  }
  if (!response.ok) {
    const message = errorMessage(response.status, parsed);
    if (response.status === 401) window.dispatchEvent(new Event(SESSION_ENDED_EVENT));
    if (message === 'mfa_setup_required') window.dispatchEvent(new Event(MFA_SETUP_REQUIRED_EVENT));
    throw new ApiError(response.status, message);
  }
  return parsed as T;
}
