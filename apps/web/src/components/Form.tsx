// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, type FormEvent, type InputHTMLAttributes, type ReactNode } from 'react';
import { BrandMark } from './BrandMark';

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
          <BrandMark />
          OpenChart AI
        </div>
        <h1 id="auth-title">{title}</h1>
        {intro && <p className="auth-intro">{intro}</p>}
        {children}
      </section>
    </main>
  );
}
