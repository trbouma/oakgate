# Safebox address discovery and social identity

Status: payment-reader migration implemented, 2026-10-19. Acorn provides the
version-1 parser, builder and secure resolver; OakGate and Safebox Web publish
the directory and use it for cash and Clear payment discovery. Safebox Web wallet-message delivery and attribution now use it too; OakGate
has no messaging interface and does not advertise that capability. Public NIP-05
responses retain their existing defaults. OakGate users can now set a separate social
npub in Preferences; Safebox Web social-key preferences remain future work.
It is a Mainstay-family application contract, not an established Nostr standard.

## Purpose and boundaries

One address, such as `alice@example.com`, should support three independent uses:

| Use | Lookup | Meaning |
| --- | --- | --- |
| Social identity | `/.well-known/nostr.json?name=alice` | Social Nostr public key and social relay hints, following NIP-05 |
| Wallet delivery | `/.well-known/safebox.json?name=alice` | Acorn public key, wallet relay hints and explicit delivery capabilities |
| Lightning | `/.well-known/lnurlp/alice` | Existing LNURL-pay service |

The social key and Acorn key may be equal, but clients must never assume they are.
The operator service identity is a third key: it signs service zap receipts and
must not become either user's identity. An address is a mutable domain-controlled
alias; it is not the durable Acorn identity or proof of a person's real identity.

Acorn owns portable discovery semantics, user-key operations and wallet protocols.
Stroma owns Nostr validation, signing, encryption and relay transport. Applications
own handle registration, public HTTP directory responses, consent, presentation,
workflow coordination and deployment policy. DNS/HTTPS directory assertions do not
prove a recipient is online, that a mint will redeem, or that a payment settled.

The mint policy remains unchanged: trust any mint from which Acorn can successfully
receive. Discovery must not introduce an issuer allowlist. Existing Clear routing
restrictions and asset identity `(mint, unit)` remain in force.

## Deployment and rollout

Phases 1 and 2, cash/Clear readers, and Safebox Web wallet-message delivery and
attribution are implemented. OakGate also implements the optional social-key
preference from phase 4; deployment compatibility restrictions still apply.
Acorn's resolver has no legacy fallback: it returns a distinct not-found error
only for HTTP 404 and never queries `nostr.json`. Applications own the explicit
legacy-domain policy described below.

1. Publish the Acorn commit containing `acorn.safebox_discovery`.
2. In each app, run `poetry update safebox-acorn`, inspect and commit its lockfile,
   then run its tests against installed dependencies. Keep the Git branch on `main`.
3. Deploy the apps and verify both directories for a claimed handle. Do not change
   its NIP-05 key. OakGate's endpoint uses the canonical `OAKGATE_PUBLIC_URL` domain.
4. Safebox Web uses `SAFEBOX_NIP05_EXTERNAL_RELAYS` as the explicitly configured
   public wallet relay list during dual publication. With no public relay list,
   it returns 404 rather than exposing an internal home relay. OakGate uses the
   existing approved Acorn bootstrap relay. Invalid public routing returns 503.
5. Deploy the payment readers with the correct legacy-domain configuration.
   Safebox Web also applies it to wallet messages. There is no automatic social-key cutover.

The payment readers require the published discovery API in the committed lockfiles.
Verify the installed revision before deploying; source-override testing does not
establish container deployability. A directory is ready only when a real handle
returns a validated version-1 response.

No database migration, new secret, service key or mint policy is introduced.
Cash/Clear receipt capabilities reflect current implementation/configuration;
Safebox Web advertises wallet messaging; OakGate does not yet provide it.

## Legacy coupling and remaining compatibility

Both applications default to their existing Acorn key as the NIP-05 identity
for legacy clients; OakGate can explicitly override its social identity. Migrated cash/Clear readers and Safebox Web wallet messaging
use `safebox.json`, except for explicitly permitted 404 legacy fallback. Local
lookups use the registered wallet key directly.

Acorn's generic address resolver still uses NIP-05 for `name@domain`; its social
and legacy APIs retain their semantics. Migrated applications pass explicit wallet
keys and routes into those APIs. Changing public NIP-05 mappings can still redirect
unmodified clients, so social-key separation requires the controlled cutover below.

There is a separate older Acorn `pay_multi()` branch which reads
`/.well-known/safebox.json/<name>` after a Safebox flag in LNURL metadata. It
expects `pubkey`, `relays` and optional `ecash_relays`, then uses a nonce-bearing
kind-21401 flow. This is not the version-1 contract below. Do not turn that LNURL
flag on merely because the new endpoint exists, redirect the old route, or alias
it to the new response. Preserve existing legacy behaviour where deployed;
compatibility with that transport requires a separate, explicit adapter and tests.

## Version-1 HTTP contract

Canonical request:

```http
GET /.well-known/safebox.json?name=alice
```

Exactly one `name` parameter is required. Version 1 accepts ASCII local parts
matching `[a-z0-9_.-]{1,64}` after lowercasing. Providers may impose stricter
registration rules; discovery does not expand existing handle eligibility.
Trim surrounding address whitespace before splitting, normalize the domain to
lowercase IDNA, and encode query parameters with a URL library. Reject credentials,
fragments, ports and malformed address inputs. Do not enumerate all registrations
when `name` is missing. One response describes exactly one address.

Successful response (the sample key is illustrative):

```json
{
  "version": 1,
  "address": "alice@example.com",
  "pubkey": "b0635d6a9851d3aed0cd6c495b282167acf761729078d975fc341b22650b07b9",
  "relays": ["wss://spurline.safebox.dev"],
  "capabilities": {
    "acorn-ecash-transfer": {
      "transports": ["nip59"],
      "kinds": [7378],
      "units": ["sat"]
    },
    "clear-token-transfer": {
      "transports": ["nip59"],
      "kinds": [7379]
    }
  }
}
```

| Field | Requirement |
| --- | --- |
| `version` | Required integer, exactly `1` for this version; booleans are invalid |
| `address` | Required canonical address, matching the requested name and domain |
| `pubkey` | Required valid Nostr public key encoded as 64 lowercase hex characters; Acorn destination, never social or service key |
| `relays` | Required array of 1–8 unique absolute `wss://` URLs; no credentials or fragments; each at most 2,048 characters |
| `capabilities` | Required nonempty object containing explicit supported protocol descriptors |

Relay hints are public wallet delivery routes, not social relays or a promise of
availability. Passing validation does not bypass the caller's relay policy.
Acorn keeps responsibility for selecting/reaching delivery routes, including its
existing inbox discovery. Such discovery must remain bound to the resolved wallet
key and cannot substitute another key. Private standalone deployments may use
explicit local configuration; version-1 public discovery does not authorize
arbitrary private-network requests or insecure WebSocket endpoints.

Protocol descriptors use arrays of known transport names and integer inner-event
kinds. `nip59` denotes the existing gift-wrap transport; the outer kind is 1059,
not the listed inner kind. Receivers advertise only implemented, enabled receipt
paths. The initial registry is:

| Capability | Required transport/kind | Scope |
| --- | --- | --- |
| `acorn-ecash-transfer` | `nip59`, inner kind 7378 | Current Acorn cash transfer; `units` must include `sat` |
| `clear-token-transfer` | `nip59`, inner kind 7379 | Current Clear transfer; omitted `units` means no advertised unit restriction; a present list must be nonempty |
| `safebox-wallet-message` | `nip17`, inner kind 14 | Wallet messaging using the existing version-1 `safebox.dm` content envelope; only advertise after send, receive and attribution support are implemented |

A client must understand the selected capability and its required transport and
kind before using it. Unknown capabilities or additive fields are ignored; they
never authorize a send. Malformed required fields, malformed selected descriptors
and unknown top-level versions are errors. Do not infer capabilities from a key,
relay hint, domain name, social profile or LNURL `allowsNostr` field. Payment-request
formats such as NUT-18 keep their own explicit destination contracts.

Responses use `Content-Type: application/json`, `Access-Control-Allow-Origin: *`,
`X-Content-Type-Options: nosniff` and `Cache-Control: no-store` initially. Requests
need no authentication or cookies and must not change state. Return no secrets,
account identifiers, email addresses, balances or recovery material.

| HTTP status | Meaning |
| --- | --- |
| 200 | Valid, active wallet directory entry |
| 400 | Missing, duplicate or malformed name |
| 404 | No active/advertised wallet under that name, or endpoint absent on an older server |
| 410 | Optional deliberate retirement of a formerly served wallet address; never a legacy-fallback signal |
| 429 | Rate limited; client must back off |
| 503 | Directory temporarily unavailable |

Error bodies use `{"error":"not_found"}` or another stable code, with no keys or
capabilities. A client must not interpret an error as a successful directory
response. Missing endpoint and missing handle are not reliably distinguishable
from a 404 alone.

Fetches require HTTPS with certificate verification, bounded time and response
size (proposed defaults: 5 seconds total, 64 KiB), and no redirects. Server-side
clients must reject nonpublic destination addresses and pin a validated DNS result
to the TLS request to prevent DNS rebinding. Do not use ambient HTTP proxies.
Validate JSON types, reject duplicate object keys, and validate public keys through
Stroma. Share contract fixtures and parsing semantics across products; retain
explicit application policies without weakening these network guards.

## Resolution and payment safety

1. Resolve an address through version-1 Safebox discovery, or the equivalent
   validated local directory entry. Check the requested capability before export,
   minting, signing or publication.
2. Bind the canonical address, wallet key, selected protocol and relay policy to
   the prepared operation. Confirmation must not silently replace them. If a fresh
   lookup changes the destination or capability, require a new review; persist the
   selected identity for durable retry rather than resolving it again on restart.
3. If the endpoint returns 404 or a valid response lacks cash support, an ordinary
   cash payment may prepare an LNURL route and show it for confirmation. Clear,
   continuity-only transfers and wallet messages report unsupported delivery.
4. Malformed responses, unsupported versions, retirement, timeouts and temporary
   failures stop wallet discovery. They do not trigger implicit NIP-05 fallback.
   A user may explicitly choose a separately reviewed Lightning payment when safe.
5. After any direct send starts, an uncertain outcome must never cause automatic
   Lightning fallback, a changed recipient, or a second export. Existing durable
   journals, reconciliation and Acorn-native history remain authoritative.

Delivery acknowledgement and recipient redemption remain separate outcomes.
OakGate may redeem in the background; Safebox Web may require an online user.
No new discovery flag claims immediate settlement.

## Social identity, messages and zaps

Keep standard NIP-05 responses for social clients, including their required
cross-origin access. A social profile must publish the matching `nip05` value for
clients to show the association. The wallet directory must not overwrite social
profile data or require OakGate to hold a social private key.

OakGate users can save a social npub in Preferences while authenticated. Stroma
validates its public-key encoding and curve point. Per the product decision, this
setting does not require a proof-of-control challenge. Nostr clients verify the
association by comparing the signed kind-0 profile's `nip05` value with the public
NIP-05 response. OakGate does not claim to have verified social-key control and
never requests or stores that key's secret.

The public association is stored separately in SQLite `user_social_preferences`,
keyed by the existing issuer/subject owner. Changing it does not modify custody,
Acorn ownership, payment routes or wallet-message destinations. Clearing it restores
the existing Acorn-key NIP-05 response. The preference follows the account when its
handle changes; removed/inactive handles are not published. A connected active
Acorn is still required for the existing public address lifecycle.

When a social npub is set, `nostr.json` publishes only its social key, without
wallet capability extensions or wallet relay hints. `safebox.json` and local wallet
routing always use the Acorn binding. No social relay preference is introduced.

Wallet-message address resolution and claimed-sender attribution use
`safebox.json`; social messaging and social attribution continue using NIP-05.
The UI must distinguish these purposes. Authenticated event signatures establish
the sender key; directory lookup establishes only the current address association.
A renamed/reassigned address must not rewrite historical counterparties or turn an
old message into a claim about its new owner. Already explicit npub destinations
retain their existing meaning and do not undergo address reinterpretation.

Keep LNURL `nostrPubkey` as the receipt-signing service key. A signed zap request
may name any social recipient in its `p` tag; it need not match the Acorn key or
have a registered social-to-wallet association. The authenticated encrypted
callback determines the credited Acorn. Preserve the original signed request and
its social recipient in the receipt, without rewriting its `p` tag. Validate the
signature, recipient-key format, optional amount, LNURL and service `P` tag.
Default invoice compatibility mode does not enforce description-hash binding.
This zap behaviour is independent of NIP-05 wallet discovery migration.

## Migration without silent breakage

A new endpoint alone cannot make old NIP-05-based senders safe after a social-key
change. Public servers cannot prove that every third-party sender has upgraded.
Compatibility therefore requires a staged rollout and a constrained final cutover.

### Phase 1: additive Acorn API and contract fixtures

Add an explicitly named wallet-address discovery API returning a typed result with
canonical address, wallet key, capabilities, relay hints and discovery source.
Do not change the generic NIP-05 resolver, social APIs, existing transfer signatures
or explicit-key behaviour. Initially applications call the new resolver and pass
its explicit wallet key and relay hints to existing Acorn transfer methods.
Existing callers continue to work unchanged. New named APIs or explicit opt-in
parameters can later provide wallet-aware address convenience; do not silently
change ambiguous `name@domain` semantics in existing APIs.

Publish Acorn with shared version-1 success/error/security fixtures. Run existing
Safebox Web and OakGate tests against the installed release/locked revision, not
only a source override. Keep Acorn and Stroma dependency declarations on `main`
where already configured; update and commit resolved lock revisions deliberately.
No Stroma change is required unless validation or transport support is missing.

### Phase 2: dual publication, identical keys

Safebox Web and OakGate publish `safebox.json` from their existing handle-to-Acorn
binding. Keep `nostr.json` and its existing extensions unchanged, with the same
Acorn key. Local and external directory results must agree. Do not enable a
separate social key yet. Discovery must not need a recipient login session.

Publish only enabled capabilities, using bounded public lookups; do not expose
custody secrets to build the response. OakGate obtains user public identity through
Acorn. Safebox Web continues storing only its public registration data.

### Phase 3: upgrade all maintained senders and message consumers

Move Safebox Web cash/Clear address routing and OakGate cash/Clear preparation to
the new Acorn resolver. Update wallet-message destinations and attribution together.
Preserve Clear guards, public-network restrictions, pending-send protection,
confirmation binding and existing mint policy. Keep social lookup on NIP-05.

For controlled rollout only, offer an explicit per-domain legacy compatibility
policy. A 404 from the new endpoint may permit the old NIP-05 wallet lookup only
for domains known to keep social and wallet keys equal. Record the legacy source
in the prepared operation. Never enable generic NIP-05 fallback for arbitrary
domains, and never fallback on malformed data, 410, timeouts or 5xx. Remove existing
blanket inference that a NIP-05 key plus relays proves wallet support.

Keep old APIs available during this phase; document their legacy address semantics.
Ship migration tests before tightening defaults in maintained applications. Old
receivers remain reachable through the deliberate compatibility policy or ordinary
Lightning, rather than a hidden change to their meaning.

### Phase 4: enable separate social identities only where safe

Keep existing public handles in equal-key compatibility mode while any supported
legacy sender relies on their NIP-05 mapping. Do not automatically rewrite them.
Changing `nostr.json` on the same old address while preserving compatibility with
all unmodified senders is impossible: they will still use the social key as a
wallet key. A capability field cannot stop clients that never read it.

For upgraded, controlled peers, remove legacy fallback for the domain and verify
new discovery end to end before enabling opt-in social-key binding. For addresses
with uncontrolled legacy clients, preserve the old mapping and offer a distinct
social alias/domain during transition, or establish a documented breaking-change
cutover outside this nonbreaking rollout. New deployments can start with the split
contract, but must still disclose that old NIP-05-based wallet clients are unsupported.
The same-address social/wallet experience is the target, not a promise that old
clients can automatically interpret it correctly.

### Rollback and retirement

Before any split, endpoint and reader changes can roll back while equal-key legacy
responses remain valid. After a split, rolling senders back to NIP-05 wallet lookup
is unsafe. Preserve the new endpoint, disable new sends if necessary, and restore
only software that understands the split. Keep in-flight recipients pinned and
reconcile outcomes before retry. Do not delete old endpoints or APIs until their
consumers and pending operations have migrated under an explicit version policy.

## Persistence, continuity and acceptance

Back up provider handle-to-wallet and optional social-key associations alongside
existing registration/custody data and keys. A restore must preserve opt-in migration
state and retirement records so it cannot resurrect an obsolete destination or
legacy fallback. Discovery is a directory, not portable wallet state: independent
Acorn recovery continues using the user's recovery phrase and bootstrap relay.
A domain address may be lost when leaving a provider without losing the Acorn.

Implementation acceptance must cover:

- Same address with deliberately different social and wallet keys: social lookup
  returns only the social key; cash, Clear and wallet messages use only the wallet.
- Upgraded sender to upgraded receiver, upgraded sender to explicitly supported
  legacy receiver, and legacy sender to an unchanged equal-key receiver.
- Missing capabilities, unknown version, invalid keys, duplicate names/JSON keys,
  redirects, private DNS results, rebinding, oversized bodies and bounded timeouts.
- A wallet-key change between review and confirmation and during crash recovery;
  no silent retargeting, second export or Lightning retry after an uncertain send.
- Disabled/retired recipients, handle changes, local/external parity, preserved
  mint acceptance and Clear routing rules, and Acorn-only transaction history.
- Wallet-message attribution distinct from social attribution, plus mismatched
  social zap recipients accepted and preserved while the callback wallet is credited.
- Existing Acorn APIs and Safebox Web tests passing unchanged, app tests against
  the installed locked dependencies, and boundary tests for Acorn/Stroma ownership.
- Small controlled cash/Clear/message deliveries across both applications,
  OakGate background redemption, and offline Safebox Web receipt on return.

## References

- [NIP-05: social key/address association](https://github.com/nostr-protocol/nips/blob/master/05.md)
- [Direct Safebox payments: current implementation](014-direct-ecash-payments.md)
- [Clear payments and routing guards](015-clear-payments.md)
- [Lightning receiving and zaps](009-lightning-receiving.md)
- [Mainstay principles](010-mainstay-principles.md)
- [Identity mapping and backups](008-identity-storage-backups.md)

## Payment reader rollout configuration

OakGate uses `OAKGATE_SAFEBOX_DOMAINS`; Safebox Web uses
`SAFEBOX_LEGACY_DOMAINS`. Both default to `safebox.dev`, accept comma-separated
exact domains, and allow an explicit empty value to disable legacy compatibility.
Only list older domains whose NIP-05 names still refer to wallet keys. Remove a
domain before any social/wallet split. A v1 404 is the sole trigger for legacy
lookup; malformed responses, unknown versions, timeouts and other HTTP statuses
stop preparation. A missing capability never triggers a social-key lookup.
Cash can use ordinary LNURL when no wallet route is advertised; Clear cannot.

Local recipients resolve from registered wallet bindings, without public HTTP or
social discovery. OakGate keeps operator relay approval and pins the wallet key,
relay and discovery source in its encrypted review journal. Confirmation does
not resolve the address again. Safebox Web passes explicit wallet keys and relay
hints to Acorn, including its persisted Clear jobs. No mint acceptance policy,
user-key ownership or uncertain-send retry behaviour changes in this rollout.

Deploy the lockfiles containing Acorn's published discovery API. Verify both
public endpoints for an existing handle before deploying the readers. Controlled
real cash/Clear delivery checks remain operator acceptance steps; automated tests
use fake wallets and do not move funds. Safebox Web messaging is migrated;
OakGate messaging and Safebox Web social-key preferences remain later work.

## Wallet-message reader rollout

Safebox Web resolves address destinations and claimed-sender attribution through
the message capability. It uses the existing `SAFEBOX_LEGACY_DOMAINS` policy only
after 404, never after missing capabilities or errors. Delivery passes an explicit
wallet npub and relay list to Acorn, retaining Stroma transport and the existing
`safebox.dm` envelope. Social lookup remains separate; explicit npub destinations
keep their semantics. Local wallet bindings support private community relays.

Only Safebox Web advertises messaging today. OakGate must not advertise it until
it has working send, receive and attribution support. The existing published Acorn
API suffices for this migration; no legacy/social Acorn APIs are changed.
Attribution displays current association, leaves the authenticated sender visible,
and does not hide messages when verification fails. It uses at most ten distinct
bounded lookups per page without reusing the social-identity cache.

## Enabling a distinct social npub in OakGate

Save the public npub in **Preferences → Social npub**, then set the matching
`handle@domain` as `nip05` in the signed Nostr profile. Saving only the OakGate
preference does not update the external profile or prove key control. No operator
flag or additional secret is needed. Invalid input rejects the whole preferences
save; public-key and handle changes are committed atomically.

Before using distinct keys, remove this domain from known senders' legacy wallet
fallback lists (`OAKGATE_SAFEBOX_DOMAINS` / `SAFEBOX_LEGACY_DOMAINS`) and verify v1
wallet discovery. Unmodified clients that infer a wallet key from NIP-05 cannot
safely use the split address. No server setting can correct those clients. Keep
the field blank if those clients must retain the existing equal-key behaviour.
The preference form explains this limitation. Existing users are not migrated
automatically, and neither Acorn nor Safebox Web is changed by this release.

Back up `user_social_preferences` with the rest of `custody.sqlite3`. It contains
only public npubs and owner indexes. Restoring an older backup can restore an older
social association, so check both directories after restoration. Disabling or
rolling back this feature must not silently restore wallet keys as social identities
for users who have selected a distinct key.
