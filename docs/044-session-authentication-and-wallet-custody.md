# Session authentication and wallet custody

Design note — 1 November 2026

OakGate separates browser authentication from durable wallet custody. Its browser
cookie identifies a server-side session; it does not carry an Acorn private key.
Safebox-web instead uses an encrypted, browser-held bootstrap credential that
the application decrypts to construct an Acorn. Both applications can operate
with the private key in server memory, but obtain and retain it differently.

This comparison describes Safebox-web at `aceab17` and OakGate at `22de1fb`.
It concerns the implemented browser-session paths, not a claim that every service,
worker or deployment has identical storage and lifecycle behavior. This note
does not change runtime behavior.

## The distinction at a glance

| Mechanism | Safebox-web | OakGate |
| --- | --- | --- |
| Initial access | Supply credentials, create an Acorn, or decrypt an authorized card credential | Authenticate through Keycloak, then resolve the identity's wallet mapping |
| HTTPS session cookie | `__Host-safebox_session` | `__Host-oakgate_session` |
| Cookie value | Authenticated encrypted bootstrap credentials | Random opaque session identifier |
| Wallet key for ordinary access | Inside encrypted cookie; decrypted in application memory | Encrypted durable custody row; decrypted in application memory |
| Session validation | Decrypt, authenticate and check token age/fields | Hash identifier, look up Redis record, check expiration |
| Identity basis | Acorn key in bootstrap credentials | Validated Keycloak issuer and subject |
| Default session lifetime | 30 days | 7 days |
| Browser SameSite policy | Strict | Lax |
| Local logout | Clear browser credential cookie | Delete Redis session and clear browser cookie; attempt Keycloak logout |
| NFC login result | Normal encrypted bootstrap cookie | Normal OIDC authentication and opaque session cookie |

Defaults are configurable, not measurements of a particular deployment. Both
production cookies are Secure, HttpOnly, host-only and scoped to `/`. Explicit
development/insecure modes are exceptions, not production security equivalents.

## Safebox-web bootstrap credentials

### Cookie contents and encryption

`SessionCredentials` in `app/security.py` contains `nsec` and `bootstrap_relay`,
plus optional home mint, deferred recovery mnemonic, record-protection key and
backup-confirmation state, currency, language and a credential version.
“Encrypted nsec cookie” is shorthand that understates the potential sensitivity
of the complete payload. Optional fields need not be populated in every session.

Current `SessionCipher` output begins `v2.`. It uses AES-256-GCM with a fresh
12-byte random nonce and an HKDF-SHA256-derived 32-byte key. Master material
comes from `SAFEBOX_COOKIE_KEY`; the derivation context and authenticated
additional data are `safebox-web/session-cookie/v2`. Encrypted JSON contains the
credentials, issuance time, purpose and envelope version. Nonce and ciphertext
are base64url encoded for transport. AES-GCM, not base64, provides encryption
and tamper detection.

Decoding checks authenticated decryption, purpose/version, issuance time and
credential fields. Tokens more than 60 seconds in the future or older than the
configured lifetime are rejected. Unprefixed legacy Fernet cookies remain
readable subject to their age limit; new encoding uses v2. Credential version
and encrypted-envelope version are separate fields.

`SAFEBOX_SESSION_TTL_HOURS` controls lifetime, with legacy
`SAFEBOX_SESSION_TTL_SECONDS` as fallback. The default is 720 hours. Browser
expiry and server-side token-age checks both apply. Paths that reissue the
cookie, including preference updates, create a fresh issuance time; ordinary
requests do not unconditionally renew it.

### Request execution and background work

`get_session_credentials` reads and decodes the cookie. `build_acorn` passes
the recovered `nsec` and bootstrap relay to Acorn. This ordinary session path
does not look up a durable user-wallet private-key row or opaque session registry.
The app holds usable secret material while servicing the operation.

Client-held ciphertext does **not** mean client-only cryptography or that the
operator cannot use the key. The running server has the cookie decryption key
and receives the encrypted credential. A trusted application runtime remains
part of the security model.

The background Acorn factory captures credentials in memory for a job. Clearing
a browser cookie does not cancel an already-running job or erase its captured
credentials. The inspected finalization/payment database models store non-secret
coordination state; that does not imply that unrelated service-wallet credentials
or every other feature are credential-free.

### Disconnect and recovery

The disconnect route requires CSRF validation and recovery confirmation, then
clears the cookies. The inspected session decoder has no individual-session
denylist lookup. A separately copied valid cookie therefore remains usable until
expiry or another applicable protection prevents use. Clearing the original
browser cannot erase that copy.

Changing the master cookie key invalidates cookies encrypted under the old key,
but is a broad operational action, not per-session logout. Other mechanisms may
use or derive from that secret; rotation needs an inventory and migration plan,
not an improvised session-revocation procedure.

The holder needs independent recovery material and the correct bootstrap context
to reconnect without a surviving usable credential. Cookies are not recommended
backup media. Recovery of wallet authority also does not guarantee availability
of mint proofs, relay records or Blossom files.

## OakGate authentication and session creation

### Keycloak establishes identity

OakGate starts an OIDC authorization-code flow with independently random state,
nonce and PKCE verifier. It stores the transaction under a key derived from a
browser-binding cookie and state. Callback processing atomically consumes that
transaction, preventing reuse.

Normal and NFC clients share a callback but have separate client credentials.
The saved transaction selects the expected client. OakGate's OIDC code validates
the identity response, including issuer, audience, signature, nonce and expiry.
Email is a display/contact attribute, not the wallet ownership key.

The ordinary login callback creates a fresh `secrets.token_urlsafe(32)` session
ID: 32 random bytes represented as URL-safe text. Redis uses
`oakgate:session:` followed by SHA-256 of that ID as its lookup key. The record
contains the user's validated issuer/subject and display attributes, a CSRF
secret and `expires_at`. It contains no nsec or OIDC token. Replacing a browser
session also deletes that browser's previous session record.

The cookie contains the raw random ID, not its hash. It does not need encryption
or a signature: an arbitrary substituted value has no matching authorized
server-side record. Its unpredictability and protection remain essential.
Hashing the Redis key limits direct replay from a read-only copy of the session
index; it does not protect against a compromised application or an attacker with
session-store write access.

### Subsequent access and expiry

`current_session` hashes the cookie value, reads Redis and checks expiry. It does
not contact Keycloak or refresh an OIDC token for each protected request.
`OAKGATE_SESSION_TTL_SECONDS` defaults to 604800 seconds. Cookie lifetime, Redis
TTL and application expiry are aligned at creation; ordinary reads do not extend
this fixed lifetime.

Keycloak's own cookies belong to its identity-provider session and origin.
OakGate does not read those cookies to authorize its pages. A Keycloak session,
an OakGate Redis session and an Acorn wallet are distinct objects with distinct
lifetimes.

Secure sign-in configuration requires Redis. `MemoryStore` is for development
and loses sessions on restart. Redis data loss can require fresh sign-in without
deleting durable custody. Unavailability must not be bypassed by trusting an
unresolvable cookie.

## OakGate durable custody and Acorn execution

`identity_key` computes SHA-256 over compact JSON `[iss, sub]`. This owner key
locates the wallet row in the custody database. It is not derived from email,
the session ID, the NFC card ID or the private key.

`CustodyStore` uses Fernet with `OAKGATE_CUSTODY_KEY` to encrypt a payload containing
owner and wallet material. Retrieval checks that the embedded owner matches the
requested owner. Wallet status is separately tracked. The database supports the
SQLite or PostgreSQL deployment paths; session Redis and durable custody have
different purposes.

The central `AcornBackend.wallet` adapter passes decrypted material, including
`nsec` and relay, into Acorn. User-key signing, derivation and wallet operations
belong inside Acorn under OakGate's architectural boundary. Custody encryption
with an operator secret does not authorize implementing those operations in the
web application.

The operator-controlled runtime can decrypt custody. Encryption protects a copied
database when its key is not also exposed; it is not end-to-end encryption against
the operator. Compromise of the custody database and its key has a different,
potentially much larger impact than one stolen browser session.

The same Keycloak issuer/subject preserves ownership mapping across normal and
NFC login. Recreating an account or moving identity providers with a new subject
does not automatically recover the wallet, even with the same email address.
Identity migration needs an explicitly authorized mapping.

## NFC authenticates access without changing custody

Safebox-web's card format encrypts private-key bytes, bootstrap relay, PIN,
generation and issuance/expiry metadata in a CBOR credential. Following a bound
one-use browser challenge, PIN and current card-policy checks, login decrypts
that credential and issues the ordinary session cookie. Blocking future card
use does not add a card-policy lookup to every existing session-cookie decode.

OakGate's OGC2 card is different. Its authenticated header identifies the issuer
origin and pinned instance public key. Its encrypted body contains a random card
ID, random card secret and issuance/expiry times—not the Acorn nsec. The database
binds it to its owner and wallet. The generated PIN stays off the card; OakGate
stores an encrypted salted scrypt verifier and requires explicit login enrollment.
PIN-free login is an explicit per-card exception.

Keycloak's dedicated NFC authenticator sends card credentials to OakGate's
protected verification endpoint with a shared backchannel secret and short-lived
authentication-session challenge. OakGate checks card authority, enrollment,
wallet binding, issuer, replay and PIN policy. Keycloak resolves the returned
subject to an existing enabled realm user, then completes normal OIDC login.
OakGate creates the same type of opaque session as ordinary sign-in.

The dedicated flow excludes cookie-based authentication: an existing Keycloak
SSO session does not silently replace its card ceremony. Federated NFC payments
do not confer cross-home login authority. An OakGate card is not a portable
wallet recovery credential. See [Keycloak NFC login](027-keycloak-nfc-login.md).

## Expiry and revocation are separate controls

| Action | Effect and boundary |
| --- | --- |
| Safebox-web disconnect | Removes that browser's cookie; does not centrally revoke copies or cancel captured background credentials |
| OakGate logout | Deletes the current Redis session, clears cookies and attempts Keycloak logout; other local sessions are separate |
| OakGate session deletion/expiry | Prevents subsequent lookup; does not erase custody or cancel work already authorized |
| Keycloak disablement/revocation | Affects provider authentication; the inspected OakGate request path does not recheck it on every active local session |
| Card revocation/enrollment withdrawal | Blocks future card authentication according to policy; does not itself terminate existing app sessions |
| Wallet departure/key migration | Separate from logout and card replacement; requires its own supported workflow and state checks |

The ability to delete a Redis record is not a claim that a user-wide “log out all
devices” interface or Keycloak backchannel-logout propagation is implemented.
Incident response must address both provider and application sessions. An
operation already in progress may complete after access is revoked.

## Threat model and recovery implications

Both cookies are bearer credentials. Anyone obtaining a usable cookie can attempt
the actions permitted to that session without decrypting it. Safebox-web's token
additionally carries encrypted key material; the matching master secret can
expose that material. OakGate's cookie alone does not decrypt custody, but its
valid session authorizes access to an app that can perform wallet operations.
Opaque does not mean harmless.

Secure limits transmission to HTTPS; HttpOnly prevents ordinary JavaScript reads;
SameSite limits cross-site sending; the `__Host-` prefix prevents Domain scoping
and requires a secure root-path cookie in supporting browsers. None stops XSS
from acting through an authenticated page, malware, server compromise or every
CSRF scenario. Application CSRF checks remain necessary. OakGate's Lax setting
accommodates the cross-site OIDC callback; Safebox-web's direct bootstrap flow
uses Strict. Neither establishes user presence for each wallet operation.

OakGate recovery disclosure requires fresh same-account authentication through
the normal client, recent signed `auth_time`, the same active browser session
and a two-minute one-use reveal authorization. Acorn checks the recovery identity;
the ordinary session alone does not authorize disclosure. This does not make all
other session actions safe after theft, or guarantee a new upstream Google
password prompt. See [Recovery disclosure](016-recovery-disclosure.md).

For restoration, preserve custody data, the matching custody key, identity
mapping/Keycloak state and other required operational secrets. Redis sessions
are not wallet backups. Independent Acorn recovery also depends on correct
recovery semantics and external data. Recovery disclosure is implemented; a
complete Go Independent/departure workflow must not be inferred from it. See
[Backup and recovery plan](036-backup-and-recovery-plan.md).

## Operational guidance and future work

Keep session stores, custody, issuer card keys and identity-provider state
distinct in backup, rotation and incident-response procedures. Never log cookies,
nsecs, PINs, recovery phrases, decrypted custody or credential request bodies.
Do not copy production cookies into diagnostic reports.

Deployment acceptance should exercise both login routes, logout, expiry, card
revocation, wrong-PIN lockout and recovery step-up on the configured services.
Confirm the same issuer/subject resolves to the same wallet. Inspect actual cookie
flags and lifetime without recording values. Test Redis loss separately from
custody restoration, accounting for proxy HTTPS handling and browser NFC support.

Potential hardening includes explicit user-wide session revocation,
Keycloak-to-application revocation propagation, stronger step-up for selected
wallet actions, and individual-session revocation for client-held bootstrap
credentials. These are options, not features established by this review.

## Source map and verification

Paths below are relative to each repository at the revision named above, not
deployment secrets or local machine paths.

| Repository | Source | Mechanism |
| --- | --- | --- |
| Safebox-web | `app/security.py`, `app/config.py` | Credentials, encryption, age checks and cookies |
| Safebox-web | `app/dependencies.py` | Request Acorn and background credential capture |
| Safebox-web | `app/main.py` | Connection, reissuance and disconnect |
| Safebox-web | `app/nfc_cards.py`, `app/nfc_login.py`, `app/models.py` | Card credentials, policy, challenges and job coordination |
| OakGate | `app/auth.py`, `app/oidc.py`, `app/sessions.py`, `app/config.py` | OIDC, random cookies, Redis lifecycle and logout |
| OakGate | `app/custody.py`, `app/wallets.py` | Owner mapping, custody encryption and Acorn boundary |
| OakGate | `app/nfc_cards.py`, `app/nfc_login.py`, `keycloak/nfc/` | Card capability and Keycloak authentication |
| OakGate | `app/recovery.py` | Fresh-authentication recovery disclosure |

Review checks passed: 13 focused Safebox-web tests covering connection, session
cipher/lifetime, reissuance and disconnect; 49 OakGate authentication, NFC login
and Acorn-boundary tests. These are automated checks, not a new audit of live
deployment configuration or physical NFC behavior.

Related guides: [Identity storage and backups](008-identity-storage-backups.md),
[Authentication design](001-authentication-design.md), and
[Keycloak operations](028-keycloak-operations.md).
