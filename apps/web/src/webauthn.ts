// SPDX-License-Identifier: AGPL-3.0-or-later
// Passkey ceremonies: fetch options from the API, run them in the browser,
// send the result back.
import { startAuthentication, startRegistration } from '@simplewebauthn/browser';
import { api } from './api';

type Options = Parameters<typeof startAuthentication>[0]['optionsJSON'];
type CreationOptions = Parameters<typeof startRegistration>[0]['optionsJSON'];

export const passkeysSupported = () => typeof window.PublicKeyCredential === 'function';

/** Ask the browser for a passkey assertion and post it. */
export async function signWithPasskey<T>(optionsPath: string, verifyPath: string): Promise<T> {
  const options = await api<Options>('POST', optionsPath);
  const credential = await startAuthentication({ optionsJSON: options });
  return api<T>('POST', verifyPath, { credential });
}

/** Create a new passkey and post it. */
export async function createPasskey<T>(name: string): Promise<T> {
  const options = await api<CreationOptions>('POST', '/account/security/passkeys/options');
  const credential = await startRegistration({ optionsJSON: options });
  return api<T>('POST', '/account/security/passkeys', { name, credential });
}

/** Turn browser WebAuthn errors into something a person can act on. */
export function passkeyErrorMessage(error: unknown): string | null {
  if (error instanceof Error && error.name === 'NotAllowedError') {
    return 'The passkey request was cancelled or timed out.';
  }
  if (error instanceof Error && error.name === 'InvalidStateError') {
    return 'This passkey is already registered.';
  }
  return null;
}
