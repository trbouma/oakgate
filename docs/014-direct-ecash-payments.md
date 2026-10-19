# Direct Safebox payments

OakGate can receive encrypted Acorn ecash transfers without an active browser or
Redis session. A Send payment page also lets a user review an address and amount,
then confirm a direct ecash or Lightning payment.

## Address discovery and routing

`/.well-known/nostr.json?name=handle` maps the current, active OakGate handle to the
user's Acorn public key and approved bootstrap relay. It also advertises the
`acorn-ecash-transfer` protocol without restricting mint issuers. This is separate from
LNURL discovery: the `nostrPubkey` used for zap receipts remains OakGate's service
identity, not the user's Acorn identity.

Safebox Web already resolves NIP-05 names and relay hints before choosing its
Acorn direct-transfer path. It can use OakGate's directory response without
needing the recipient to open OakGate. NIP-05 alone is a public-key directory,
not proof of wallet capabilities. For outgoing payments OakGate requires an
Acorn capability descriptor or an operator-recognized legacy Safebox Web domain.
The default legacy domain is `safebox.dev`; configure the actual Safebox Web
hostname if different.

Direct delivery uses a relay in `OAKGATE_ALLOWED_RELAYS`. New receiving relays
must be approved by the operator. Mint selection and redemption use Acorn's
existing policy: any mint from which Acorn can successfully receive is accepted.
OakGate does not add a mint allowlist or restrict direct sends to the bootstrap
mint. The bootstrap mint is the default for creating Lightning receiving
invoices, not a list of trusted issuers.

When no usable direct route is found, OakGate resolves LNURL and obtains a
Lightning invoice before showing confirmation. It checks the amount, expiry,
and description hash when present. Discovery and callback requests require
HTTPS, pin a public DNS result to the TLS connection, limit response size, and
never follow redirects. No payment is sent during review.

## Receiving and settlement

The background worker scans active Acorns, including users who are signed out or
have no current handle. It defaults to a 30-second interval per wallet, processes
up to four wallets concurrently, and takes the same owner lease as outgoing and
Lightning credit operations. This is prompt background settlement, not a
promise of instantaneous settlement: relay/mint availability and queue load
still matter.

The adapter first calls `sweep_ecash_transfers(finalize=False)` to persist incoming
receipts through Acorn. It then calls
`reconcile_continuity_receipts()` to redeem tokens through their issuing mints.
A receipt is not spendable merely because it arrived: Acorn must successfully
redeem it and persist the resulting proofs. Transient failures remain pending
for retry, using Acorn's existing receipt handling. Only Acorn writes proofs,
receipts, checkpoints, and transaction history. OakGate adds no duplicate credit
entry and no separate mint trust policy.

Acorn uses Stroma for gift wrapping and relay transport. Stroma disables timestamp
jitter and uses current timestamps for seals and wrappers. The receiver uses
Acorn's existing checkpoint and receipt deduplication behavior; it does not
introduce a two-day rescan or an alternative Nostr implementation.


## Sending, retries, and uncertainty

The Send payment page is available from Balances and Cash transactions. Review
shows the address, exact satoshi amount, and selected payment route. Provider
fees can apply. Confirmation requires the user's session and CSRF token.

An encrypted SQLite outgoing journal binds a one-shot confirmation to its owner.
Confirmation expires after five minutes or invoice expiry, whichever is sooner.
A claimed attempt cannot be submitted again by refreshing the page or repeating
the request. An uncertain result or a process interruption after claiming blocks
new sends for that owner pending operator review. There is deliberately no
automatic retry or fallback after an Acorn send starts.

A direct-send result means Acorn returned delivery success; it does not prove
recipient redemption. OakGate recipients can settle in the background, while a
non-custodial recipient may still need to open their wallet. These direct ecash
payments do not create Lightning invoices or NIP-57 zap receipts. Existing
Lightning address payments and zaps retain their existing path.

For unresolved payments, retain the journal and inspect native Acorn transaction
history, pending mint operations, and recipient receipt evidence. Do not simply
delete the local attempt or pay again. Automated operator reconciliation and a
user-facing pending-receipts page are not included in this change.

## Configuration

```dotenv
OAKGATE_ECASH_RECEIVE_ENABLED=true
OAKGATE_ECASH_POLL_SECONDS=30
OAKGATE_SAFEBOX_DOMAINS=safebox.dev
```

The receiver is independent of user login sessions. Disabling it stops background
redemption and NIP-05 payment discovery but does not delete received tokens.

## Dependencies and deployment

This feature uses Acorn's existing `sweep_ecash_transfers`,
`reconcile_continuity_receipts`, `send_ecash_transfer`, and `pay_multi_invoice`
methods. It requires no new Acorn mint-policy API or lockfile update. Stroma
already has the required no-jitter behavior and needs no source change.

After committing and pushing OakGate, deploy with `./refresh-app.sh`. Verify the
NIP-05 response for a connected handle, then test a small payment while the
recipient is signed out. A real mint/relay payment is an operator acceptance
check; unit tests do not transfer money.

## Backups

Back up `custody.sqlite3` and the separate custody encryption key as already
documented. The database now also contains the encrypted outgoing journal and
inbox scheduling state. Incoming receipts and native transaction history remain
in the Acorn's relay-backed state. Redis is not the durable payment journal.
