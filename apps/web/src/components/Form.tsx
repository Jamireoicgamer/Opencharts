// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from 'react';
import { ApiError } from '../api';

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
}

export function Field({ label, hint, ...input }: FieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} aria-describedby={hint ? hintId : undefined} {...input} />
      {hint && (
        <small id={hintId} className="field-hint">
          {hint}
        </small>
      )}
    </div>
  );
}

export function ErrorMessage({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="form-error" role="alert">
      {message}
    </p>
  );
}

/** Runs an async submit handler with a busy flag and a user-facing error message. */
export function useSubmit<T extends unknown[]>(handler: (...args: T) => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(...args: T) {
    setBusy(true);
    setError(null);
    try {
      await handler(...args);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Try again.');
    } finally {
      setBusy(false);
    }
  }

  return { busy, error, run };
}

export function formValues(event: FormEvent<HTMLFormElement>): Record<string, string> {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  return Object.fromEntries([...data.entries()].map(([k, v]) => [k, String(v)]));
}

export function AuthCard({
  title,
  intro,
  children,
}: {
  title: string;
  intro?: ReactNode;
  children: ReactNode;
}) {
  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="brand auth-brand">
          <svg className="brand-mark" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3 3v18h18M6.5 15.5l4.2-4.2 3.5 2.2L20 6" />
          </svg>
          OpenChart AI
        </div>
        <h1 id="auth-title">{title}</h1>
        {intro && <p className="auth-intro">{intro}</p>}
        {children}
      </section>
    </main>
  );
}
