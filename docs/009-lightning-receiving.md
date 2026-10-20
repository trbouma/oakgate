# Receiving Lightning payments and zaps

Date: 2026-10-18  
Status: Implemented; offline recovery tests pass. Live paid-invoice verification remains to be done.

OakGate receives payments directly into the user's connected Acorn. It holds the Acorn private key, so it can complete receipt while the user is signed out. There is no intermediate service Acorn or later transfer to the user. The underlying cash proofs and encrypted relay events use the same safebox-acorn architecture.

## Address and configuration

Connect or create an Acorn, then choose a handle in **Preferences**. The **Balances** page shows its Lightning address, for example `alice@oakgate.safebox.dev`. The domain comes from `OAKGATE_PUBLIC_URL`, never the incoming Host header. Public address discovery requires an HTTPS origin without an explicit port.

```dotenv
OAKGATE_BOOTSTRAP_MINT=https://mint.safebox.dev
OAKGATE_ZAP_RELAYS=wss://relay.primal.net,wss://relay.damus.io,wss://nos.lol
OAKGATE_RECEIVE_MIN_SAT=1
OAKGATE_RECEIVE_MAX_SAT=1000000
OAKGATE_PAYMENT_POLL_SECONDS=5
OAKGATE_REQUIRE_DESCRIPTION_HASH=false
OAKGATE_PAYMENTS_ENABLED=true
```

The bootstrap mint becomes the home mint for newly created Acorns. Incoming invoices also use that configured mint, including for an existing Acorn. Connecting an existing Acorn does not rewrite its saved home mint or move its existing funds. Each payment saves its selected mint, so changing the default does not redirect pending payments.

`OAKGATE_ZAP_RELAYS` is independent of the private bootstrap/home relay allowlist. It controls public receipt publication. Zap requests can supply additional public `wss://` relay destinations. OakGate limits their number, validates resolved public addresses at connection time, and rejects redirects and private-network destinations.

The worker runs in the FastAPI app container; no new container or Redis queue is needed. Deploy with `./refresh-app.sh` after updating the checkout and settings. Keycloak does not restart. For an isolated restore or receiving maintenance, `OAKGATE_PAYMENTS_ENABLED=false` disables new invoices and the background worker. Paid invoices will wait until processing is re-enabled.

## Invoice compatibility

The default matches Safebox Web's compatibility approach: request an ordinary mint invoice and accept a plain BOLT11 description. OakGate still validates its amount, mainnet currency and expiry. It stores the payment context and signed zap request separately. Compatibility mode does not reject missing or mismatched description hashes; binding is recorded for information only.

A plain BOLT11 invoice is valid without a description hash. The current LUD-06 LNURL-pay specification also no longer requires a metadata hash check. NIP-57 still describes hash-bound zap invoices, however, so some Nostr clients or older LNURL wallets may reject invoices or receipts without that binding. Compatibility mode does not claim universal client support or strict NIP-57 compliance.

Set `OAKGATE_REQUIRE_DESCRIPTION_HASH=true` for strict operation. OakGate then asks the mint for an invoice committing to the exact metadata (ordinary address payment) or exact raw signed zap request (zap). It refuses to return an invoice whose description hash does not match. The request includes `description` and a `description_hash` extension; a mint must actually implement suitable invoice generation, not merely accept or ignore those fields.

On 2026-10-18, a public capability check showed that `mint.safebox.dev` advertises NUT-09 recovery. One unpaid 1-sat compatibility probe returned a plain-description invoice, without a description hash. No payment was made. That mint works with OakGate's default compatibility path; strict mode requires a mint-side change. Actual end-to-end client compatibility and paid settlement still need a deployment test.

## Receiving flow

1. A payer resolves `/.well-known/lnurlp/{handle}`. OakGate requires an active Acorn, returns limits and metadata, and advertises that Acorn's public key as the zap receipt signer.
2. The callback contains an encrypted, 15-minute snapshot of the recipient and metadata. A handle change cannot redirect that callback to another owner. Once a handle belongs to an active Acorn, it remains reserved to that owner; clearing or renaming the handle disables discovery at the old address.
3. OakGate validates the amount and any signed kind-9734 request, including its recipient-key format, optional amount, event tags and LNURL. The signed social recipient may be any public key; the encrypted callback determines which Acorn is credited. Amounts must be whole sats within the configured limits. Callback comments of up to 255 characters are advertised and accepted. They are stored inside the encrypted payment journal and never appended to invoice metadata or the signed zap request. A zap's signed content is retained unchanged.
4. It reserves a payment row, requests the mint quote, and saves the invoice, quote, mint keys and generated blinding secrets encrypted in SQLite **before returning the invoice**. Repeated identical zap requests reuse the unpaid invoice. A changed serialization of the same zap event is rejected so the description binding cannot silently change.
5. The background worker polls the mint, normally every five seconds for unexpired invoices. Once payment is confirmed, it requests Cashu signatures for the saved outputs and unblinds them using Acorn's primitives.
6. OakGate calls Acorn’s `add_proofs_obj()` to prepare a native encrypted proof write, saves the opaque prepared result, then calls the same Acorn method to deliver and verify it on the home relay. Funds are credited directly to the user's Acorn.
7. After credit, OakGate calls Acorn’s `add_tx_history()` to prepare and deliver an encrypted credit entry with verified home-relay readback. The entry contains the amount, invoice, payment time, and comment (or signed zap content). The exact signed event is saved before publication and reused on retries. Historical balance is left unknown rather than inferred from a later balance.
8. For a zap, OakGate signs a receipt with its operator-owned service identity through Stroma, saves the exact event for retries, and uses Stroma to publish it to the configured relays and usable relay hints from the payer. Receipts retain the original signed request and invoice, recipient/event tags, and sender attribution. Only confirmed, credited payments reach this stage.

Users do not need an active browser or Google session. The balance page reads the Acorn again when refreshed. “Immediate” means automatic settlement shortly after confirmation, subject to worker load and mint/relay availability; it is not a synchronous credit guarantee.

## Restarts and retries

SQLite is the payment journal. Its `incoming_payments` table binds each payment to its immutable OakGate owner. Sensitive contents—including quote identifiers, blinding secrets, proofs, invoice and zap context—are Fernet-encrypted with `OAKGATE_CUSTODY_KEY`. The owner, opaque payment ID, optional zap request ID, timestamps, state and processing lease are indexes outside the encrypted payload.

A short database lease and bounded processing time prevent two app processes from settling the same journal entry concurrently. Atomic quote-creation limits allow at most 30 requests per owner per hour and 120 per instance per minute. Configure Nginx rate limiting too for public deployment; those database limits are not a general denial-of-service defence. Avoid recording callback query strings in proxy logs because they contain payment and zap context.

Before mint issuance, blinding material is already durable. If the mint issues signatures but the response is lost, OakGate uses NUT-09 `/v1/restore` for those same outputs. It does not mint fresh outputs for the same payment. NUT-09 support is required even in compatibility mode.

The encrypted proof event, encrypted transaction-history event, and public receipt are also stored before publication. A lost acknowledgment causes the same event ID to be retried. Zap relay acknowledgments are tracked independently; a failed public relay does not remint or recredit a payment. There is no receipt until the funds have been delivered to the Acorn. Delivery errors log only an opaque journal ID and exception type, never exception bodies that may contain secrets.

Expired unpaid quotes remain in the journal and are checked hourly, so later confirmation is not silently discarded. A paid quote remains recoverable even after its invoice expires, subject to the mint's issuance policy. Partial signature restoration or malformed mint replies leave the payment pending for retry/operator investigation; OakGate does not declare success or create replacement funds. A crash before an invoice is returned may leave an unused creation row or mint quote, but no payer has been told to pay it.

## Backup implications

Back up the entire consistent `custody.sqlite3`, including `incoming_payments` and `lightning_handles`, and preserve the matching custody key separately. Redis contains no receiving state. The payment journal is especially important between Lightning settlement and verified Acorn delivery: a recovery phrase alone cannot reconstruct OakGate's random pending blinding secrets.

Do not restore an old database into a second running worker against the same live infrastructure. Start an isolated restore with `OAKGATE_PAYMENTS_ENABLED=false`. Reconcile payment progress against the current mint and relay state before resuming; an old backup may predate an accepted invoice or a completed delivery. Back up the mint and relay infrastructure you operate as well. OakGate's journal is not a replacement for their persistence or an Acorn-wide proof archive.

See [Identity, storage and backups](008-identity-storage-backups.md) for the Google/Keycloak mapping and complete backup inventory.

## Deployment checks

- Keep the configured HTTPS origin and Nginx routing for both `/.well-known/lnurlp/` and `/lnurl/callback/` pointed at the app. These are public endpoints, not sign-in pages. Large zap requests may need appropriate Nginx request-header limits.
- Confirm the advertised address, recipient public key, whole-satoshi limits and mint configuration.
- With a disposable Acorn, test a small ordinary payment and a zap from the clients you intend to support. Confirm the balance increase and public receipt; repeat after an app restart. These are real-payment checks and were not performed by the offline test suite.
- In strict mode, first verify the mint produces the expected description-hash invoice. In compatibility mode, verify each intended client accepts the invoice and receipt.

References: [BOLT11 invoice encoding](https://github.com/lightning/bolts/blob/master/11-payment-encoding.md), [LNURL-pay](https://github.com/lnurl/luds/blob/luds/06.md), [NIP-57](https://github.com/nostr-protocol/nips/blob/master/57.md), [Cashu NUT-09 recovery](https://github.com/cashubtc/nuts/blob/main/09.md).


### History backfill on upgrade

Previously completed OakGate payments are scheduled for history-only delivery when they do not have a confirmed history write. This uses their original saved payment time and invoice and does not mint funds or republish cash proofs. Zaps issued under the previous user-key signer need to finish before this upgrade. Old pending receipts are not silently re-signed by the service key; funds and history can still be credited, but receipt delivery needs operator reconciliation. Completed zaps are not republished during history backfill. The transaction page still reads only Acorn history; local journal rows are never substituted into the display. Backfill requires the retained payment journal, custody key, and reachable home relay. `OAKGATE_PAYMENTS_ENABLED=false` pauses this work as well.


### Acorn owns user Nostr writes

OakGate does not construct, encrypt, sign or publish the user's proof events or transaction-history events. Both go through Acorn methods. Public zap receipts use the separate OakGate service identity through Stroma. OakGate handles the payment journal and passes Acorn's prepared result back unchanged when a write needs retrying. It never substitutes a local journal entry into the user-facing transaction list.

This integration requires the Acorn prepared-write API (`prepare_only`, `prepared_events`/`prepared_event`, and public-identity methods). Publish that Acorn revision and update OakGate's Poetry Git pin and lockfile before deploying this change. The existing pinned revision does not provide those arguments. Local verification can use the updated sibling source via `PYTHONPATH=/Users/trbouma/projects/safebox-acorn`; that override is for development only, not container deployment.


### Mandatory user-key boundary

Every operation using the user's private key belongs in an Acorn method, including public-identity derivation, recovery-key generation and derivation, encryption/decryption, signing and user event publication. OakGate is a custodian and orchestrator; possession of the key does not make it a second implementation of Acorn. The adapter may supply opaque custody material to Acorn and store opaque prepared delivery results, but may not perform the key operation itself.

If an API is missing, extend Acorn. Any exception needs a specific documented rationale and the project owner's approval; none is currently approved. Public-only request validation and encryption of custody records with the separate operator key do not cross this boundary. Cashu blinding factors are independently generated ephemeral secrets, not the user's Acorn private key.

The repository's `AGENTS.md` records this rule and `tests/test_acorn_boundary.py` checks for direct Nostr key operations and access to nsec outside the adapter. This is a regression guard, not a proof against every possible bypass; code review must preserve the data-flow boundary as well.

### Nostr library boundary

Stroma (`stroma-nostr`) is an explicit OakGate dependency and the Nostr protocol
implementation. OakGate validates public zap requests with Stroma. User-key
operations go through Acorn, which uses Stroma for events, encryption, signatures
and relay transport. Acorn supplies public DNS and redirect policy to Stroma's
relay client; it does not implement relay frames itself. Prepared event retries
retain the same event ID and private writes are checked by reading them back.

The new Acorn and Stroma APIs must be published and the resolved dependencies
updated together before deploying these changes.

### OakGate instance identity

Like Clear, Spurline, Safebox Web and Mainstay, OakGate uses a stable operator
Nostr identity configured separately from user identities. Set
`OAKGATE_SERVICE_NSEC` in `.env` to a fresh private key (hex or nsec). Generate
once with `openssl rand -hex 32`; never reuse a user Acorn or custody key.
Compose passes this value to the app. The local development server must load
`.env`, as with the other application settings.

The public npub is bound transactionally to `custody.sqlite3` in
`service_identity`, following Clear's database-binding pattern. Startup refuses
a missing or changed key after binding. Stroma derives the npub and matching
FIPS address, as in Spurline and Safebox Web. No private service key is stored
in that table. Back up the service secret securely alongside the custody key
and retain the database binding. Do not delete the binding to rotate identity.

LNURL discovery advertises this service's hex key as `nostrPubkey`; the zap
request's `p` tag identifies the social recipient, which need not be the Acorn key. An optional request `P`
tag must match the service signer. Receipt author is the service; receipt `p`
is the recipient and receipt `P` is the payer. This follows
[NIP-57](https://github.com/nostr-protocol/nips/blob/master/57.md).
The signer is saved with each invoice and callback so an old request cannot
silently switch signer. Fresh instances without a key allow ordinary payments
but advertise `allowsNostr: false` and reject zap requests.


## Acorn-owned durable issuance

Cashu quote validation, blinding, restoration and proof construction now live in
`acorn.minting.DurableCashuMint`. OakGate's `app/payment_mint.py` only re-exports
that API and its compatibility exception. OakGate still saves encrypted
checkpoints, claims leases and coordinates settlement. Proof and transaction
history publication still go through Acorn with persisted event identities.

Existing checkpoints retain exactly the same `outputs`, `secrets`, and `keys`
format. Do not clear pending jobs or generate new prepared outputs during this
upgrade. Restoration runs before issuance and reuses the original outputs after
a lost response. Mint acceptance and optional description-hash policy are
unchanged. Safebox Web's existing Acorn methods remain unchanged.

Deploy in this order:

1. Commit and publish the safebox-acorn change to `main`.
2. In OakGate, run `poetry update safebox-acorn` and verify the resolved revision
   includes `acorn.minting`. Commit the resulting lockfile with this change.
3. Run the tests against that installed dependency, then push and deploy OakGate
   with `./refresh-app.sh`.

A local source override is useful for cross-repository tests but does not update
the container dependency. The old locked Acorn revision does not contain this
API; do not deploy OakGate with that lockfile. No database migration is needed.


### Background contention and retry scheduling

Incoming invoice status checks hold only the payment journal lease, not the
wallet lease. An unpaid invoice or unreachable mint therefore does not lock the
recipient's Acorn. Confirmed payment status is checkpointed before acquiring the
wallet lease for issuance and Acorn proof/history delivery. Those mutations remain
serialized; stored blinding material and exact prepared events are reused after
a crash. Public zap publication runs after releasing the wallet lease, while
retaining the payment lease and durable relay acknowledgments.

A busy wallet defers settlement for five seconds without treating ordinary
contention as a warning. Other payment failures back off from 30 seconds to five
minutes, with the retry count persisted in the encrypted payment journal. A
successful quote lookup resets that count. Expired unpaid quotes remain eligible
for the existing hourly recovery check. Failure logs include the phase and elapsed
time, but omit provider error text and wallet secrets.

Inbox polling starts its cooldown after processing finishes, so a slow run cannot
immediately reacquire the wallet just because its original interval elapsed.
Consecutive failed runs back off to five minutes (or the configured interval if
longer). Schedule and failure count survive restart; an explicit inbox wake during
a run is preserved. Worker timeouts and lease durations are unchanged, and no
pending payment is deleted or declared failed merely to free a wallet lock.


Cash and Clear inbox phases now use separate wallet leases, with a one-second
foreground opportunity between them. If a foreground operation claims the wallet,
the next phase is deferred; ordinary contention retries after five seconds without
increasing the failure count. Each network phase retains its existing timeout.
The scheduler keeps at most four owners in flight and replaces completed work
without waiting for the slowest owner. Shutdown cancels and awaits those workers
so their lease cleanup completes. The persisted schedule reservation covers the
whole pass; after a crash it becomes eligible again automatically.

Acorn must include the cancellation cleanup fix in `acquire_lock`: a cancelled
acquisition releases its process-local lock, but leaves any unverified published
relay lease to expire normally. This can still cause a temporary busy response,
but avoids a permanent local lock leak without bypassing distributed protection.
No pending receipt, prepared proof, outgoing hold, or transaction history is
removed by this change. Receipt redemption and recovery still go through Acorn.

Deploy the Acorn fix first to its Git main branch, then run
`poetry update safebox-acorn` in OakGate and commit the resulting lockfile before
rebuilding the app. Local source-override tests alone do not update the container.
