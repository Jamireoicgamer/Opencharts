// SPDX-License-Identifier: AGPL-3.0-or-later
// Small typed client for the OpenChart API. A generated client replaces it in M2.

export type Role = 'owner' | 'admin' | 'member';

export interface Me {
  id: string;
  email: string;
  display_name: string;
  role: Role;
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
  return status >= 500 ? 'The server had a problem. Try again.' : `Request failed (${status})`;
}

export async function api<T = void>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
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
  const parsed: unknown = text ? JSON.parse(text) : null;
  if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, parsed));
  return parsed as T;
}
