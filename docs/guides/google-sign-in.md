# Set up Google sign-in

Google sign-in is optional. Once it's on, people can link their Google account under **Account → Security** and use it to sign in, and invited people can join with Google instead of a password.

A Google account can never create an account on your server by itself. It must be linked by someone who is already signed in, or come with an invite. If an account has two-factor turned on, Google sign-in still asks for the second step.

## What you need

- Your server reachable over **HTTPS on a domain name**, for example `https://charts.example.com`. Google does not allow plain HTTP addresses (except `localhost`) or bare IP addresses as redirect targets. A Cloudflare Tunnel or Tailscale Funnel gives you HTTPS without opening ports.
- `OPENCHART_PUBLIC_ORIGIN` set to that exact address.
- A Google account to create the OAuth client with.

## 1. Create the OAuth client in Google Cloud

1. Open the [Google Cloud console](https://console.cloud.google.com/) and create a project (for example "OpenChart").
2. Go to **APIs & Services → OAuth consent screen**:
   - user type **External** (or **Internal** if you use Google Workspace and only your organisation signs in);
   - app name "OpenChart AI", your email as the support and developer contact;
   - scopes: `openid`, `email` and `profile` (the defaults are enough);
   - while the app is in **Testing**, add the Google accounts that will sign in as **test users**. Only those accounts can use it until you publish the app.
3. Go to **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - application type **Web application**;
   - **Authorised redirect URI**: `https://charts.example.com/api/auth/google/callback`, using your own address and keeping the path exactly as shown;
   - leave "Authorised JavaScript origins" empty. It isn't needed.
4. Copy the **Client ID** and **Client secret**.

## 2. Give them to OpenChart

The client secret goes in the secrets folder, never in an environment variable or a file you commit:

```bash
printf '%s' 'YOUR-CLIENT-SECRET' > secrets/openchart_google_client_secret
```

Then start the stack with the client ID and your public address:

```bash
OPENCHART_PUBLIC_ORIGIN=https://charts.example.com OPENCHART_GOOGLE_CLIENT_ID=YOUR-CLIENT-ID.apps.googleusercontent.com docker compose up -d
```

To keep these settings, put them in a `.env` file next to `compose.yaml`, which Docker Compose reads automatically:

```
OPENCHART_PUBLIC_ORIGIN=https://charts.example.com
OPENCHART_GOOGLE_CLIENT_ID=YOUR-CLIENT-ID.apps.googleusercontent.com
```

If you set up OpenChart before Google sign-in existed, run `sh scripts/gen-secrets.sh` once more first. It only adds the missing `openchart_google_client_secret` file and never changes existing secrets.

## 3. Check it works

1. Open your server's address. The sign-in page now shows **Continue with Google**.
2. Sign in the usual way, open **Account → Security** and choose **Link a Google account**.
3. Sign out, then use **Continue with Google**.

If something goes wrong, the page explains it, and **Account → Activity** (for the owner) records failed Google sign-ins with the reason. Common causes:

| Message | Fix |
|---|---|
| Google shows `redirect_uri_mismatch` | The redirect URI in Google Cloud must match `OPENCHART_PUBLIC_ORIGIN` + `/api/auth/google/callback` exactly, including `https` and any port. |
| "That Google account isn't linked" | Link it first from Account → Security while signed in. |
| Google says the app is in testing / access blocked | Add the account as a test user on the OAuth consent screen, or publish the app. |
| "Google sign-in did not work" | Check the client secret file and that the API container can reach `oauth2.googleapis.com` and `www.googleapis.com`. |

## Turning it off

Empty the secret file, or unset `OPENCHART_GOOGLE_CLIENT_ID`, and restart. Linked Google identities stay in the database but can't be used. Before turning it off, make sure everyone who joined with Google has set a password or added a passkey under Account → Security.
