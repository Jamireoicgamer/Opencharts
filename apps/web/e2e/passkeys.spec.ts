// SPDX-License-Identifier: AGPL-3.0-or-later
// Real WebAuthn ceremonies in Chromium, using its virtual authenticator, against
// a fake API. Proves the browser wiring: options in, a genuine credential out.
import { expect, test, type Page } from '@playwright/test';

const owner = { id: 'u1', email: 'owner@example.com', display_name: 'Ada', role: 'owner' };
const challenge = 'dGVzdC1jaGFsbGVuZ2UtMTIzNDU2Nzg5MA';

async function virtualAuthenticator(page: Page) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  await cdp.send('WebAuthn.addVirtualAuthenticator', {
    options: {
      protocol: 'ctap2',
      transport: 'internal',
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
    },
  });
}

test('adds a passkey, then signs in with it', async ({ page }) => {
  await virtualAuthenticator(page);
  const posted: Record<string, unknown>[] = [];
  let signedIn = true;
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const key = `${route.request().method()} ${url.pathname.replace('/api', '')}`;
    const body = route.request().postDataJSON() as Record<string, unknown> | null;
    const json = (status: number, value: unknown) => route.fulfill({ status, json: value });
    switch (key) {
      case 'GET /health':
        return json(200, { status: 'ok', version: '0.1.0' });
      case 'GET /setup/status':
        return json(200, { needs_setup: false });
      case 'GET /auth/me':
        return signedIn ? json(200, owner) : json(401, { detail: 'Not signed in' });
      case 'GET /auth/providers':
        return json(200, { google: false });
      case 'GET /account/security':
        return json(200, {
          has_password: true,
          totp: false,
          passkeys: [],
          google_email: null,
          recovery_codes_left: 0,
          require_mfa: false,
          google_available: false,
        });
      case 'POST /account/security/passkeys/options':
        return json(200, {
          rp: { id: 'localhost', name: 'OpenChart AI' },
          user: { id: 'dTE', name: owner.email, displayName: owner.display_name },
          challenge,
          pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
          authenticatorSelection: { residentKey: 'required', userVerification: 'required' },
          attestation: 'none',
          timeout: 60000,
        });
      case 'POST /account/security/passkeys':
        posted.push(body ?? {});
        return json(201, { id: 'p1', recovery_codes: null });
      case 'POST /auth/logout':
        signedIn = false;
        return route.fulfill({ status: 204 });
      case 'POST /auth/passkey/options':
        return json(200, {
          challenge,
          rpId: 'localhost',
          userVerification: 'required',
          timeout: 60000,
        });
      case 'POST /auth/passkey':
        posted.push(body ?? {});
        signedIn = true;
        return json(200, owner);
      default:
        return json(404, { detail: 'Not found' });
    }
  });

  await page.goto('/account/security');
  await page.getByLabel('Name').fill('Virtual key');
  await page.getByRole('button', { name: 'Add a passkey' }).click();
  await expect.poll(() => posted.length).toBe(1);
  const registration = posted[0] as {
    name: string;
    credential: { response: Record<string, string> };
  };
  expect(registration.name).toBe('Virtual key');
  expect(registration.credential.response.attestationObject).toBeTruthy();
  expect(registration.credential.response.clientDataJSON).toBeTruthy();

  await page.getByRole('button', { name: 'Sign out' }).click();
  await page.getByRole('button', { name: 'Sign in with a passkey' }).click();
  // Signed in again, back on the page we left.
  await expect(page.getByRole('heading', { name: 'Sign-in and security' })).toBeVisible();
  const assertion = posted[1] as { credential: { id: string; response: Record<string, string> } };
  // The browser signed with the passkey it just created.
  expect(assertion.credential.id).toBe((posted[0] as { credential: { id: string } }).credential.id);
  expect(assertion.credential.response.signature).toBeTruthy();
});
