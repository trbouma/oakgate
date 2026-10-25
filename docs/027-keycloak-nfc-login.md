# Keycloak NFC card and PIN login

OakGate's optional NFC login uses a custom Keycloak authenticator. It does not
create an OakGate session from a card directly, register new users, or link
accounts by email. Keycloak remains the OIDC issuer. The validated issuer/subject
pair maps to exactly the same Acorn as Google/email sign-in.

The feature defaults **off**. The normal `oakgate-web` client and realm browser
flow remain unchanged. A separate confidential `oakgate-nfc` client has a dedicated
browser-flow override containing only **OakGate NFC card and PIN**, REQUIRED.
Do not add Cookie authentication, identity-provider redirects, or password forms
to that dedicated flow. Never bind it as the realm's browser flow or use it for
`oakgate-web`, the admin console, registration or password recovery.

## Enrollment and login

1. During issuance, the signed-in holder explicitly requests card-and-PIN login.
   The POS cannot make this choice. The generated PIN stays off the card and POS.
2. The holder saves the PIN, and the POS writes and reads back the card.
3. Under Preferences → Your NFC cards, choose **Enable or unlock card sign-in**.
4. Reauthenticate through the normal Google/email client (`prompt=login`,
   `max_age=0`). OakGate requires a recent `auth_time`, the same issuer/subject,
   and the same current browser session. The OIDC state is one-use. Card issuance
   alone never enables login. Google may apply its own upstream session policy;
   this is fresh Keycloak authentication, not a guarantee of an upstream password prompt.
5. On a compatible device, choose **Sign in → NFC card and PIN**, read the card,
   and enter the four-digit PIN. Keycloak's server submits these credentials to
   OakGate over an authenticated backchannel, bound to a short-lived Keycloak
   authentication-session challenge.
6. OakGate checks the encrypted card, pinned instance key, activated status,
   expiry, revocation, enrollment, current wallet binding and, by default, PIN
   verifier. The explicit per-card exception is described below.
   The nonce is consumed once. Keycloak then looks up the returned **existing user
   ID in its own realm** and requires that user to be enabled.
7. Keycloak performs the normal authorization-code exchange. OakGate verifies
   signature, issuer, audience, nonce and PKCE before creating its Redis session.

This implementation uses the same four-digit PIN provisioned during issuance.
There is no change to NFC payment or balance permissions and no payment PIN
prompt. Existing cards without a PIN or explicit enrollment must be reissued.
Only OGC2 cards qualify. No Nostr event or Acorn private-key operation is needed.

## PIN guessing, revocation and recovery

Five wrong four-digit PIN attempts block that card's login. Counts are durable in
SQLite, updated atomically across concurrent requests, survive restart, and do
not reset after successful card logins. No automatic retry follows a timeout.
Only fresh normal-client reauthentication through **Enable or unlock card sign-in**
clears the counter. This does not reveal or change the PIN; a forgotten PIN needs
a new card. There is deliberately no public PIN-reset endpoint.

Withdrawing enrollment prevents future card logins without affecting receipts or
balance lookup. Revoking the card blocks all card capabilities. Neither action
terminates already-issued Keycloak or OakGate sessions; those still follow their
existing session lifetimes and logout mechanisms. Disable the Keycloak user and
revoke sessions separately when responding to an account compromise.

A copied card plus PIN can authenticate. A four-digit PIN with online lockout is
not equivalent to a FIDO2 token or a smart card with a non-exportable signing key.
The backchannel secret is an operator credential, not a user credential: protect
it, never place it in browser JavaScript, and never enable request-body logging
on the login endpoint. Login remains restricted to cards issued by this instance;
cross-instance NFC payments do not confer cross-instance login authority.

## Beelink deployment checklist

Keep an administrator session open and verify normal Google/email login before
changing anything. No database move, identity rotation or wallet migration is needed.

### 1. Prepare configuration

Add to the existing private `.env`:

```dotenv
OAKGATE_NFC_LOGIN_ENABLED=false
OAKGATE_NFC_CLIENT_ID=oakgate-nfc
OAKGATE_NFC_CLIENT_SECRET=
OAKGATE_NFC_BACKCHANNEL_SECRET=<output of openssl rand -hex 32>
COMPOSE_FILE=compose.yaml:compose.nfc.yaml
```

Generate the backchannel secret once, independently from every other secret.
Preserve all existing custody, service identity, cookie and OIDC keys. Preserve
`OAKGATE_DATA_DIR` and `KEYCLOAK_DATA_DIR` and verify the Lexar mount as usual.
`COMPOSE_FILE` is essential: it keeps future refreshes from reverting Keycloak to
the stock image. If you already use other Compose files, append this override to
your list rather than discarding them. The override builds the provider only on
the deployment machine. It adds no new public ports or host volumes.

```sh
mountpoint /mnt/lexar
docker compose config --quiet
./refresh-app.sh
docker compose up -d --build --no-deps keycloak
docker compose ps keycloak
docker compose logs --since=2m --tail=80 keycloak
```

Wait for Keycloak to become healthy. The Dockerfile compiles and tests the provider
against the same 26.8.0 version as the runtime. Future Keycloak upgrades must update
the POM and image together and rerun tests. Do not copy an untested provider JAR
across Keycloak versions. The ordinary app Docker build does not include Java.

### 2. Configure the OakGate realm

Create a confidential OpenID Connect client named **oakgate-nfc**:

- Client authentication: ON.
- Standard flow: ON. Disable implicit flow, direct access grants and service accounts.
- Root and home URL: `https://oakgate.safebox.dev`.
- Valid redirect URI: **only** `https://oakgate.safebox.dev/auth/callback`.
- Valid post-logout redirect URI: `https://oakgate.safebox.dev/`.
- Web origins: `https://oakgate.safebox.dev` (no wildcard).
- Require PKCE method **S256**. Keep ordinary `openid profile email` scopes and
  the default subject mapping; do not add a pairwise/pseudonymous subject mapper.
- Disable Full scope allowed; no admin roles or service-account permissions needed.

Copy this client's secret into `OAKGATE_NFC_CLIENT_SECRET` in `.env`.
Do not overwrite `OAKGATE_OIDC_CLIENT_SECRET` (the normal client).

In **Authentication → Flows**, create a new basic flow, `oakgate-nfc`.
Add the execution **OakGate NFC card and PIN**, set it to **REQUIRED**.
There should be exactly one execution. Under the `oakgate-nfc` client's
**Authentication flow overrides**, select it as the **Browser flow**.
Leave the realm's global browser binding and `oakgate-web` override unchanged.

The built-in login theme can render the provider's bundled page and script.
Keep Keycloak's default restrictive CSP. The HTTPS proxy must allow Web NFC on
its own origin; if you configure Permissions-Policy, use `nfc=(self)`, not `nfc=()`.
Do not embed the login page in an iframe or relax CSP to allow inline scripts.

The plugin calls the fixed Compose endpoint
`http://app:8000/api/cards/v1/login/verify` with its shared secret. Plain HTTP is
accepted only for this fixed Compose hop; separate-host deployments must use
HTTPS. Do not expose this as an anonymous browser verification API. You may block
this exact endpoint in the public Nginx location; Keycloak reaches it internally.

### 3. Enable and test

Set `OAKGATE_NFC_LOGIN_ENABLED=true`, then:

```sh
./refresh-app.sh
docker compose up -d --no-deps keycloak
```

The Keycloak environment change recreates its container; Redis and the POS need
no NFC-login-specific update. Deploy pending PIN/enrollment issuance changes to
both app and POS if those earlier changes are not already deployed.

- [ ] Google/email sign-in still works and admin access remains available.
- [ ] An opted-in verified card can be enabled only after same-account reauthentication.
- [ ] NFC login on Android Chrome returns to the same account and Acorn.
- [ ] Wrong PIN is rejected; five failures block even the correct PIN.
- [ ] Google/email remains usable; fresh reauthentication unlocks the card.
- [ ] Withdraw enrollment or revoke the card, then confirm a new card login fails.
- [ ] Disabled Keycloak users cannot log in with an otherwise-valid card.
- [ ] NFC-unavailable browsers explain the limitation and still allow normal login.
- [ ] Existing payment, receipt and card balance flows work unchanged.

Web NFC is browser/hardware dependent. Safari on iPhone/iPad and ordinary desktop
browsers do not gain NFC support from this change. Keep Google/email as a visible
fallback. Physical card and production Keycloak testing are deployment acceptance
checks; passing unit tests alone does not establish them.

### Rollback

Set `OAKGATE_NFC_LOGIN_ENABLED=false` and recreate app and Keycloak. Normal login
is independent of the NFC client. Keep the provider override while its flow is
configured; to return to the stock image, first disable the NFC client and remove
its flow override/execution, then remove `compose.nfc.yaml` from `COMPOSE_FILE`.
No stored cards, custody records or payment journals need deletion.

## Backups and verification

Back up custody.sqlite3 consistently with its WAL, plus the custody key, service
identity, NFC backchannel secret, both OIDC client secrets and Keycloak data/config.
New tables are `nfc_login_attempts` and `nfc_login_nonces`; the existing encrypted
`nfc_login_requests` rows now support `active` as well as `requested`/`withdrawn`.
Restoring an old backup can restore an old revocation or attempt count: reconcile
card status and rotate the backchannel secret if recovering from compromise.

Tests cover durable lockout, concurrent guesses, replay, current wallet binding,
revocation, expiry, pending/withdrawn enrollment, fresh same-user OIDC activation,
and the separate client audience. Java tests cover client isolation, disabled and
missing users, malformed/mismatched backend replies, timeout and fail-closed config.
The plugin follows Keycloak's [Authentication SPI](https://www.keycloak.org/docs/latest/server_development/#_auth_spi).

## Troubleshooting card verification

If the error stays on Keycloak's card/PIN screen, verification failed before the
OIDC callback. Do not repeatedly guess the PIN. After deploying diagnostic
changes to both app and the Keycloak provider, make one attempt and inspect:

```sh
docker compose logs --since=5m --tail=100 app keycloak
```

The operator logs use fixed `NFC login` phases and never include card bytes,
PINs, headers, subjects, response bodies or exception messages:

- `backchannel_auth` (app): login disabled, secret missing/too short, or the
  Keycloak/app backchannel secrets differ. Recreate both containers after an env change.
- `backchannel` (Keycloak): HTTP status or exception class identifies endpoint or
  connection failure. A 401 needs the corresponding app rejection phase.
- `form_or_expired_challenge`: missing input or more than two minutes on the form.
- `card_decode`, `card_or_wallet_inactive`: invalid card or changed issuer/card/wallet state.
- `enrollment_not_active`: issuance succeeded but login enrollment is not active.
- `identity_binding`: stored enrollment does not match the configured identity.
- `pin_incorrect`, `pin_locked`: incorrect PIN or five failures. Use ordinary
  sign-in and fresh reauthentication to unlock; do not edit failure counters.
- `user_missing_or_disabled`: the returned subject is not an enabled user in the
  selected Keycloak realm. Do not create a replacement user or link by email.

Public responses remain generic; diagnostic detail is for the operator only.


## Optional card-only sign-in

In **Preferences → Your NFC cards**, each verified, enrolled card has **Require
PIN for sign-in**, default **On**. Existing cards without a policy row also require
PIN; issuing another card does not inherit an earlier card's preference.

To choose **Off — card only**, explicitly acknowledge that anyone holding or
copying the card can access the account, then choose **Verify sign-in and save**.
The change is applied only after fresh Google/email authentication by the same
owner in the same session. Cancellation, stale authentication or a different
account leaves the setting unchanged. Turning the requirement back on uses the
same fresh-authentication flow. The PIN itself is retained, not reset or disclosed.

When Off, leave the PIN field blank on Keycloak's card login screen. The browser
and plugin allow a blank field, but OakGate's server alone decides whether that
specific card can log in without a PIN. A blank PIN never bypasses an On policy.
Enrollment, card expiry/revocation, wallet binding, issuer identity, challenge
replay protection and Keycloak user checks still apply. Payments are unchanged.
This grants full account login, not merely receive-only POS access. POS devices
that have read the card credential could also use it for login when PIN is Off.

The `nfc_login_policy` table is included in custody database backups. Missing
policy means PIN required. Policy changes use the existing activation mechanism
and reset failed PIN attempts only after fresh authentication. Withdrawing
login enrollment or revoking the card blocks both PIN and card-only login.

Deploy the app **and rebuild Keycloak** for the optional-PIN form and plugin;
no new environment variable or card rewrite is required. This preference does
not bypass a backchannel connection/configuration error.


### Empty JSON body on the internal connection

The Java verifier explicitly uses HTTP/1.1 for its credential POST. Java's default
cleartext HTTP/2 upgrade (`h2c`) was reproduced against Uvicorn: ASGI received an
empty body, followed by an invalid HTTP request, despite a valid Java JSON body.
This caused `JSONDecodeError` before card/PIN verification. The identical request
using HTTP/1.1 delivered the full body. Do not enable h2c negotiation for this hop.
After updating, rebuild only the Keycloak provider/container; no secret changes,
card reissuance or PIN-policy changes are required for this transport fix.
