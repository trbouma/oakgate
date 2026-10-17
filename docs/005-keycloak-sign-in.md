# Connect OakGate sign-in

OakGate now uses Keycloak's authorization-code flow with PKCE. The **Sign in** button opens the `oakgate` realm login page, where the existing Google provider is available. Google credentials belong only in Keycloak.

## Create the application client

In Keycloak's admin console, select the **oakgate** realm. Under **Clients → Create client**, use:

| Setting | Value |
| --- | --- |
| Client type | OpenID Connect |
| Client ID | `oakgate-web` |
| Client authentication | On |
| Standard flow | On |
| Implicit flow, direct access grants, service accounts | Off |
| Root URL / Home URL | `https://oakgate.safebox.dev` |
| Web origins | Leave empty; token exchange happens on the server |

Add these **Valid redirect URIs**, each as an exact entry without wildcards:

```text
https://oakgate.safebox.dev/auth/callback
http://127.0.0.1:8801/auth/callback
```

Add these **Valid post logout redirect URIs**:

```text
https://oakgate.safebox.dev/
http://127.0.0.1:8801/
```

Set the client's **Proof Key for Code Exchange Code Challenge Method** to **S256** in its advanced settings. Keep the ID-token signature algorithm at **RS256**. Save, then copy the secret from the client's **Credentials** tab. This is the OakGate client secret, not the downloaded Google secret.

The local callback makes development possible with the same client. Use a separate development client with its own secret and local redirect entries when you need stronger environment separation. Match `OAKGATE_OIDC_CLIENT_ID` accordingly.

## Test locally with Poetry

```sh
poetry install
cp .env.dev.example .env.dev
chmod 600 .env.dev
```

Put the Keycloak client secret in `OAKGATE_OIDC_CLIENT_SECRET` inside `.env.dev`, then run:

```sh
./dev.sh
```

Open <http://127.0.0.1:8801>, choose **Sign in**, then Google on the Keycloak page. After consent, OakGate displays your account name and email. Test **Sign out** too: it clears the OakGate session and opens Keycloak's logout confirmation. Signing out does not sign you out of Google itself.

Use `127.0.0.1`, not `localhost`, to match the registered callback. Changing the local port requires updating both `OAKGATE_PUBLIC_URL` and the client's redirect/logout entries. Development uses in-memory sessions and needs no local containers; reloading the server logs you out. `.env.dev` is ignored by Git and loaded by `dev.sh`; the deployment `.env` is separate.

## Deploy on Beelink

Add these entries to the existing `.env`, preserving its other settings:

```dotenv
OAKGATE_PUBLIC_URL=https://oakgate.safebox.dev
OAKGATE_OIDC_ISSUER=https://keycloak.safebox.dev/realms/oakgate
OAKGATE_OIDC_CLIENT_ID=oakgate-web
OAKGATE_OIDC_CLIENT_SECRET=<paste the Keycloak oakgate-web client secret>
```

After committing and pulling the repository changes, build on Beelink:

```sh
docker compose up -d --build app
docker compose ps app sessions
```

Compose starts a private Redis session service with no published port. Session persistence is disabled and `/data` is temporary memory storage; no external-drive directory is needed for sessions. Restarting Redis logs everyone out. Existing Keycloak data stays in `/mnt/bitcoin/keycloak`.

OakGate's public URL determines callback URLs and secure cookies; incoming Host and forwarded headers cannot change them. Keep the existing HTTPS Nginx proxy to port 8801. Uvicorn access logging is disabled to avoid logging authorization codes. Also exclude the callback query string from Nginx access logs, or disable logging for that exact location. For the current separate proxy host, an example inside OakGate's HTTPS server block is:

```nginx
location = /auth/callback {
    access_log off;
    proxy_pass http://100.70.55.66:8801;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-For $remote_addr;
}
```

Use the same reachable upstream as your existing OakGate proxy. Validate and reload Nginx after editing. Never paste callback URLs with codes or client secrets into logs or support messages.

## Behavior and limits of this first slice

- `/account` requires a session; `/api/me` returns the signed-in profile or HTTP 401.
- Identity is the issuer plus Keycloak subject (`iss`, `sub`), not an email address.
- Login state is bound to the browser, expires after ten minutes, and can be consumed once. The server validates the token signature, issuer, audience, nonce, and timestamps.
- Browser cookies are opaque, HttpOnly, and SameSite=Lax; deployment uses Secure host-only cookies. Profile data and CSRF values stay in server-side storage.
- Sessions last at most 30 minutes and never longer than the ID token's remaining lifetime. There is no refresh-token handling yet; Keycloak SSO can make the next sign-in quick.
- Logout requires a POST with a session-bound CSRF token. Local logout still succeeds if Keycloak is unavailable. Keycloak may ask for confirmation because OakGate does not retain an ID token for logout.
- Back-channel logout is not implemented: revoking a Keycloak session does not immediately invalidate an already-issued OakGate session. Its short expiry limits this delay.
- A session-store outage fails closed. `/health` is process liveness, not an authentication-readiness check.
- This authenticates users permitted by the realm; the sign-in layer adds no role-based access policy. [Acorn creation and custody storage](007-acorn-custody.md) are now provided by a separate application layer; Go Independent remains deferred.

Automated tests use a simulated OIDC server and signed tokens. Complete a real Google login and logout on both local and deployed origins after configuring the client; those live checks cannot be replaced by the automated suite.
