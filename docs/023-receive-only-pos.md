# Receive-only point-of-sale terminals

Status: **deployment, provisioning and browser-bound activation implemented; payment collection remains planned**. This note defines a separate POS
application using OakGate's existing receipt and settlement capabilities. It does
not grant existing account sessions new permissions or introduce another wallet.

## Purpose and trust model

An OakGate user can provision a dedicated browser as a point-of-sale terminal.
Staff can request and observe incoming Cash and Clear payments without signing
into the owner's account. Receipts always belong to that user's connected Acorn.

The authority is deliberately narrow: collecting funds into a fixed account.
Possession of a terminal credential must never authorize spending, changing the
recipient, or reading the owner's account. Theft could allow unwanted request
creation and observation of that terminal's receipts; rate limits and revocation
bound this risk. Browser binding adds protection against copying a credential
into another browser. The receive-only restrictions remain the primary boundary.

## Architecture and deployment

Run a separate FastAPI POS service from the OakGate repository, with a separate
container, configurable host bind address/port, and public HTTPS origin such as
`https://pos.oakgate.safebox.dev`. Share UI components with Receive rather than
copying its payment implementation. Configuration names are
`OAKGATE_POS_BIND_ADDRESS`, `OAKGATE_POS_PORT`, `OAKGATE_POS_PUBLIC_URL`,
`OAKGATE_POS_API_URL` and `OAKGATE_POS_COOKIE_KEY`; see the [deployment guide](024-pos-deployment.md).
Select an unused port at deployment time. Keep instance values in `.env`.

The browser talks only to its POS origin. A narrow POS backend forwards requests
to OakGate's dedicated terminal API. OakGate verifies the credential, device
proof, revocation state and permissions itself; the POS backend cannot assert an
arbitrary owner. No generic proxy to account routes is provided.

Only OakGate mounts the custody database and holds wallet custody encryption
keys. The POS service gets neither that database nor Acorn recovery material.
It does not run a competing settlement worker. A separate port/hostname provides
operational separation; authorization at the OakGate API enforces the boundary.

Nginx terminates TLS, sets the expected forwarded headers and forwards to the
configured POS listener. Use explicit proxy trust and restrict the internal API
route's reachability. Deploy and refresh POS independently, with a bounded health
wait and failure diagnostics; leave OakGate, Keycloak and Redis running unless
an explicitly coordinated update requires otherwise.

## Instance enablement

POS is opt-in. The setting defaults to:

```dotenv
OAKGATE_POS_ENABLED=false
```

The switch is implemented. Activation and terminal management are available when enabled; payment operations remain unavailable. The public `/api/pos/v1/status` endpoint is a diagnostic exception: it returns only feature availability, never account data.
OakGate is the authoritative enforcement point; hiding the UI or stopping the
separate POS container is not sufficient enforcement.

When disabled:

- Hide POS provisioning in Preferences.
- Reject activation and all POS API operations, including configuration reads,
  request creation and status polling.
- Reject existing POS credentials without deleting their keys, device bindings,
  policies or audit history. The POS browser can still clear its local cookie.
- Continue discovery, settlement and crash recovery for payments already
  initiated. Disabling terminal access must not strand incoming funds.

Enabling POS requires valid POS configuration, including the public HTTPS
origin, internal API destination and a separate cookie encryption key. Invalid
configuration must fail closed rather than enable a partially protected API.
Re-enabling does not override individual revocations or session expiry.

Disabling POS is an instance-wide access switch, separate from per-terminal
revocation. Once the setting is applied to all running OakGate API processes,
no new POS operation is authorized, including with an existing cookie. Normal
`.env` changes require a service restart/recreation; editing the file alone is
not a live kill switch. Already-authorized operations may complete and must
retain their recovery records. The standalone POS app should show that the
service is unavailable when access is disabled, without exposing account data.

## Allowed authority

| Operation | Terminal capability |
| --- | --- |
| Read terminal configuration | Terminal name, allowed Cash currencies, allowed Clear asset names/units and receiving limits; no balance |
| Create Cash request | Amount in sats, or validated currency amount using the existing conversion rules |
| Create Clear request | Whole-number amount and a server-approved asset identifier |
| Read request/status | Only a request issued by this credential, including its public payment code and receipt state |
| Logout | End the terminal session and clear its cookie |
| Spend, refund, transfer, change recipient | Never allowed |
| Account history, balances, records, messages, preferences, recovery | Never allowed |
| Provision, approve replacement device, revoke or widen permissions | Owner's authenticated OakGate account only |

The owner is derived from the stored credential mapping, never from a submitted
owner ID, address or npub. Clear mint/unit choices come from an allowlist resolved
by OakGate. The terminal cannot submit arbitrary mint or relay URLs. Existing
mint acceptance policy is unchanged. Do not return full balance objects merely
to populate an asset selector.

A terminal request identifier is not sufficient authorization: verify both
credential and ownership on every lookup. The initial scope is individual
request status, not a full terminal ledger or an account transaction feed.

## Provisioning and activation

1. In authenticated OakGate Preferences, the owner creates a named POS terminal
   with a name. OakGate requires a connected Acorn. Receiving asset selection and
   limits will be added with payment support; this stage cannot create receipts.
2. Generate an opaque, high-entropy random POS key, shown once for entry or QR
   activation. Store only its verifier hash, with a public credential identifier,
   owner mapping, policy, creation time and revocation state. Do not put the secret
   in URL query strings, logs or analytics. NFC activation is a later transport
   for the same credential, not extra wallet authority.
3. On the POS origin, the browser generates an ECDSA P-256 key pair using Web
   Crypto. Mark the private key non-exportable and store its `CryptoKey` in
   IndexedDB; export only the public key. Verify a store/read/sign round trip
   before reporting activation successful.
4. The browser submits the POS key, public key and signed activation challenge.
   OakGate atomically binds an unbound credential to that public key. Concurrent
   activation attempts cannot both succeed. Possession of an unbound key permits
   its first activation, so protect it until activation is complete.
5. OakGate returns a terminal session bound to the credential and device. The POS
   backend sets a dedicated authenticated-encrypted cookie containing a high-entropy terminal
   session token. The activation credential is not retained in the cookie. It must not contain an Acorn key or an
   OakGate account session.
6. Preferences displays the terminal name, activation/last-seen times, status and
   a short public-key fingerprint. The fingerprint is a display aid; verification
   uses the complete registered key, not the shortened fingerprint.

Use a versioned canonical public-key representation for the fingerprint, such as
SHA-256 over the P-256 uncompressed public point. Do not fingerprint browser
version, canvas, IP address or screen dimensions. The registered key identifies
a browser installation, not provably the physical tablet.

An already-bound credential cannot enroll another key. If the browser retains
its device key, entering the original POS key can establish a new session after
logout. Losing either required item requires owner-authorized replacement or
reissuance in OakGate. Do not offer a bearer-only fallback or automatically
replace a device key when IndexedDB is missing.

## Cookie and browser proof

Use a distinct `__Host-` cookie with `Secure`, `HttpOnly`, `Path=/`, no `Domain`,
and an appropriate restrictive SameSite setting. Its authenticated encryption
key belongs only to the POS service and is separate from custody encryption and
account-session keys. Do not share cookies across `*.oakgate.safebox.dev`.

JavaScript can sign requests with the device key without reading the HttpOnly
cookie. The POS backend decrypts the cookie and forwards the session token plus the
original device proof to OakGate. Verify exact origin/CSRF requirements as well:
SameSite alone does not distinguish sibling subdomains. Keep activation and API
responses non-cacheable, apply a restrictive CSP and avoid third-party scripts.

Each authorized API call carries a fresh signed challenge. Define a versioned,
unambiguous byte format before implementation. Bind the proof to the terminal
session, credential/device identifier, intended audience, HTTP method, exact API
path and query, hash of request-body bytes, and short-lived server nonce.
OakGate verifies the signature and atomically consumes the nonce. Nonces must
not become reusable after a worker restart or across replicas. No side effect
occurs before authentication, authorization and replay validation succeed.

Use maintained cryptographic APIs, document the P-256 signature encoding, and
include interoperable browser/server test vectors. Do not claim conformance to
DPoP or another proof standard unless its full requirements are implemented.

Copying only the cookie or decrypted POS credential must fail on an already-bound
terminal without a valid device signature. Non-exportable means Web Crypto does
not permit export/wrapping of the private key; it is not a guarantee of hardware
storage or protection from malicious same-origin JavaScript, browser-profile
cloning, extensions, malware or someone using the unlocked terminal. Web Crypto
supports serializable key objects for browser storage, but persistence must be
tested on target browsers. See the [Web Crypto specification](https://www.w3.org/TR/WebCryptoAPI/)
and [CryptoKey extractability](https://developer.mozilla.org/en-US/docs/Web/API/CryptoKey/extractable).

The device key is an authorization key, not a Nostr identity or an Acorn key.
Browser signing here is explicitly part of the agreed device-binding design.
All operations involving a user's wallet private key remain exclusively in
Acorn; all Nostr interactions remain through Acorn/Stroma. The device proof does
not authorize implementing wallet signing in POS or OakGate.

## API shape and payment recovery

Implemented authorization routes and planned payment routes:

| Route | Purpose |
| --- | --- |
| `POST /api/pos/v1/activation-challenges` | Short-lived activation challenge; rate-limited and no account disclosure |
| `POST /api/pos/v1/activate` | Verify credential and proof, atomically bind or authenticate the registered device |
| `POST /api/pos/v1/challenges` | Obtain a fresh nonce for a terminal session; grants no payment operation itself |
| `POST /api/pos/v1/config` | Name, device fingerprint and receive-only scope; receiving assets/limits come with payment support |
| `POST /api/pos/v1/requests` | Create one durable request using an idempotency key |
| `GET /api/pos/v1/requests/{id}` | Read this credential's request and status |
| `POST /api/pos/v1/logout` | Invalidate this terminal session |

Apply per-key, per-owner and activation-source limits, including a cap on
outstanding requests. Strictly bound amounts, descriptions, payload sizes and
poll frequency. Return no account-existence detail on authentication failure.

Reuse OakGate's validated fiat-to-sats conversion, invoice journal, Clear request
creation and discovery/settlement workers. Persist the terminal credential ID
with each request for ownership checks. Durable idempotency is scoped to the
credential and operation, bound to the body hash: retries return the same request;
a different body with the same idempotency key conflicts. A new nonce permits a
safe retry after a lost response without duplicating the invoice. Preserve
existing uncertain-operation recovery; never retry an uncertain mint operation
as a fresh request just because the HTTP call timed out.

Terminal status keeps the current distinction: Waiting for payment, Checking
payment status when lookup fails, Payment detected while settlement continues,
and Received only after Acorn confirms credit. Detection may end foreground
polling while background recovery finishes. It is not a final-settlement claim.
Cancel stops local polling and opens a blank request; it does not revoke an
already-issued payment code. Logout or credential revocation must not discard
pending receipts or prevent settlement into the rightful Acorn.

## Device lifecycle, backups and operator controls

Logout invalidates the terminal session server-side and clears its cookie. The
browser may retain its non-exportable device key, which alone cannot log back in.
Revocation disables the POS credential and all associated sessions immediately;
check it on every operation. Replacement currently means revoking the old terminal and issuing a new key
from the owner's account; audit records are retained. A dedicated device
can clear browser data, but cannot turn that action into account access.

Store credential verifiers, public device keys, policy, revocation/session state,
request ownership and idempotency records durably in OakGate's existing storage.
Do not log the raw credential, cookie or activation payload. Use Redis only for
explicitly disposable short-lived state; its loss must invalidate challenges or
sessions safely, never remove the durable payment journal or resurrect access.

Back up this state with OakGate's custody data and configuration. Back up the POS
cookie key separately with restricted permissions, or deliberately require
reactivation after its loss. The browser private key has no server backup.
Restoring older authorization state can resurrect revoked terminals: invalidate
all terminal sessions and require owner review of credentials after a stale
restore. Follow the existing mint/payment-state recovery rules independently.

Replacing an Acorn, removing an account or completing Go Independent must disable
its terminal credentials rather than silently redirect them to a new wallet.
The full Go Independent workflow remains deferred; this dependency must be
included in its eventual implementation. Google is not involved in terminal
operation; owner management uses OakGate's provider-independent account mapping.

## Implementation stages and acceptance checks

1. Build credential provisioning/revocation and the scoped API with durable
   ownership/idempotency, using the existing receiving services.
2. Add browser key enrollment, proof verification, replay protection, session
   lifecycle and the isolated cookie boundary.
3. Deploy the separate POS service and reuse the compact Receive UI, currency
   selection, keypad, QR copying, progress and receipt feedback.
4. Test on iPad Safari, mobile and desktop browsers, including restart and storage
   eviction. Add NFC/managed device workflows only after this core is verified.

Before release, verify that:

- POS defaults off; disabling it rejects existing credentials and new activation
  while preserving pending settlement; invalid enablement configuration fails closed;

- changing owner, request ID, asset, URL, amount or signed bytes cannot bypass scope;
- a copied cookie/credential without the device key fails, replay fails, and two
  first-activation attempts cannot bind two devices;
- logout, revocation and replacement invalidate old sessions without interrupting
  settlement; cleared browser storage requires authorized reactivation;
- request retries, browser reloads, service restarts and concurrent submissions
  never duplicate payment creation or credit, and stale-rate handling is preserved;
- payment detection remains responsive, while failed settlement remains recoverable;
- POS cannot reach account-only endpoints, access custody storage or expose full
  balances/history, and a compromised POS service still cannot spend via this API;
- terminal management and all wallet paths preserve Acorn/Stroma boundaries.

## Implemented activation protocol and defaults

The activation key is `ogpos1.<random identifier>.<256-bit random secret>`.
Only its SHA-256 verifier is persisted. An unused key expires after 24 hours;
a bound key may authenticate the same device again until revoked. Each successful
activation replaces previous sessions for that terminal. Sessions expire after
seven days. Owners can have ten unrevoked terminals and provision at most ten
per hour. Revoke expired unused entries to free a slot.

Challenges expire after 60 seconds, allow at most 60 issues per terminal per
minute, and are consumed atomically with the authorized operation in SQLite.
API calls are limited to 120 per minute per actual peer (the POS proxy shares
this budget); forwarded source headers are not trusted. This conservative
activation-stage rate limit will need revisiting when payment polling is added.

The exact proof message is a compact JSON array encoded as UTF-8:

```text
["oakgate-pos-proof-v1", public_origin, terminal_id, session_id,
 "POST", exact_backend_path, "", sha256(canonical_operation_body), nonce, expires_unix]
```

For activation, `session_id` is empty and the canonical operation body is
compact JSON `[terminal_id, public_key]`. For config/logout it is `{}`.
The credential/session secret and proof envelope are excluded from this body;
there are no other accepted action parameters. Query strings and extra JSON
fields are rejected. Future payment bodies must define their own signed bytes.
The server generates and stores the exact message; the browser checks its version,
audience, operation, body hash, nonce and expiry before signing it. Public keys
are base64url-encoded uncompressed P-256 points; signatures are base64url-encoded
64-byte IEEE P1363 `r || s`, the Web Crypto format. Server verification converts
that format to DER for cryptography's ECDSA SHA-256 verifier. This is a scoped
application protocol, not a claim of DPoP conformance.

The private `CryptoKey` is non-exportable and persisted through IndexedDB.
A sign/verify round trip after reading it back must succeed before enrollment.
An atomic IndexedDB read/write transaction keeps simultaneous tabs from
replacing the device key. Missing keys fail closed; they do not silently rebind
a terminal. Target Safari/iPad storage persistence still needs deployment testing.

The host-only `__Host-oakgate_pos` Secure, HttpOnly, SameSite=Strict cookie uses
Fernet authenticated encryption with a POS-specific payload prefix and seven-day
TTL. Its plaintext is only the terminal session token, never a wallet credential.
Normal logout uses a signed proof and invalidates the server session. **Clear
local session** only removes the browser cookie and is available during an outage
or lost device-key situation; it does not revoke server state. Revoke the terminal
from Preferences if the cookie may have been copied. This distinction is deliberate.

Tables `pos_terminals`, `pos_sessions`, `pos_challenges`, `pos_limits` and
`pos_audit` live in `custody.sqlite3`, so existing consistent custody backups
include them. Device public keys, verifier hashes and lifecycle timestamps are
stored; no device private key is sent to the server. Authorization checks the
original `wallet_id` is still active, preventing retargeting after replacement.
Revocation remains available to owners while POS is disabled. No Acorn private-key
operation is added by activation, and no receipt or payment row is modified.

Payment endpoints remain unavailable. Asset policies, amount caps, request
ownership and durable payment idempotency are prerequisites for the next stage.
