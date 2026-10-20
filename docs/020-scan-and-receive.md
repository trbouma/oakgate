# Scan and Receive

Scan and Receive sit directly below account navigation as two equal, full-row
buttons with 56-pixel touch targets. Both pages require a signed-in account;
processing codes and requesting funds also require a connected Acorn.

## Scan

The camera implementation and GS1 acquisition/discovery logic are adapted from
Safebox Web. QR scanning has a bundled local decoder; EAN, UPC and DataMatrix
support additionally depends on the browser BarcodeDetector API. Manual entry
works without camera access. Remote camera access requires HTTPS.

Acquisition preserves the original UTF-8 payload, including ASCII group
separators. GTIN check digits, UPC-E expansion, Digital Links, lots, serials and
expiry fields use the same bounded GS1 rules. Ambiguous inputs offer an explicit
interpretation choice. Product discovery shows signed candidates and OpenETR
notices without treating a matching signature as manufacturer recognition or
physical authenticity. Only configured relay and Blossom sources are queried;
the printed product website is never fetched. Artifact downloads verify SHA-256.
Ordinary HTTPS links require an explicit click before external navigation.

Lightning addresses and standard address LNURLs open the existing payment form.
Cash invoices must be unexpired, mainnet, fixed whole-satoshi amounts within the
existing sending limit. Clear NUT-18 requests (including supported bitcoin:creq
wrappers) are inspected by Acorn and reviewed with friendly asset labels and
receiver fees. Payment requires a separate confirmation. Clear request public
keys are explicit wallet destinations; no social NIP-05 resolution occurs.
Address payments retain safebox.json discovery and Lightning fallback.

Outgoing invoices and single-use Clear request IDs are deduplicated per owner in
the durable payment journal, including across rescans. Atomic claims and the
existing unknown-outcome state prevent automatic retries after uncertain sends.
Acorn reinspection checks the reviewed Clear mint, keyset, amount, fee and route
before sending. Instance-only mint requests are not routed using guessed
recipient locality: use the local receipt-address flow instead. Mint acceptance
remains based on successful Acorn redemption, without a new issuer allowlist.

Record presentation and transfer codes are inspected through Acorn against the
operator's configured storage. Presentations include existing record previews
and OpenETR evidence. Transfers and pasted Clear tokens require explicit import
confirmation. Encrypted, owner-bound tickets keep bearer codes out of URLs and
prevent repeated submissions of the same import confirmation. An interrupted
import is left for review; Clear receipts remain recoverable through Acorn.

## Receive

Cash requests use the same encrypted incoming-payment journal, prepared mint
material, worker and Acorn proof/history methods as Lightning address payments.
They work without a custom address handle and survive browser closure or app
restart. Clear requests advertise the connected Acorn's bootstrap inbox, exactly
where OakGate's existing Clear receiver polls while the user is signed out.
That receiver also supports NUT-18 payment envelopes. Only Acorn receipt and
transaction history evidence can mark a Clear request received; request matching
includes ID, mint and unit. No second user transaction entry is written by OakGate.

The centered request display includes the amount, QR and selectable request code.
It starts a status lookup after one second, then checks every five seconds after
completion of the previous lookup, for at most 60 seconds. Requests do not overlap.
Confirmed Cash or Clear credit shows **Received**, hides the code and offers
**View funds**. Failed lookups show **Checking payment status**; they never imply
successful receipt. Expired requests and receipts needing review stop polling.

After 60 seconds, automatic checking stops and any in-flight browser lookup is
cancelled. The request itself remains valid and background receipt processing
continues. **Check receipt** reloads the request and starts a fresh checking window.
Leaving the page also stops polling. Recent requests remain available. Receipt
checking does not initiate a payment or write another transaction.

## Deployment and backups

New Clear requests use uppercase NUT-26 `CREQB1…`; legacy `creqA` requests
remain readable. Recognized payment prefixes bypass GS1 interpretation even when
camera metadata reports DataMatrix or the last selected interpretation was GS1.
A payment-preparation failure stays in payment review instead of asking users to
reinterpret the code.

CREQB creation requires Acorn's optional `encoding="B"` creation API. Its default
remains `A` for existing callers such as Safebox Web. After pushing the Acorn
change, run `poetry update safebox-acorn` in OakGate and commit `poetry.lock`
before rebuilding. An older locked dependency displays an explicit update-required
message rather than silently generating creqA. Existing receiving-worker
settings must remain enabled; public HTTPS enables mobile camera access.
`OAKGATE_OPENETR_RELAYS`, `OAKGATE_BLOSSOM_SERVER` and
`OAKGATE_TRANSFER_SERVER` select record infrastructure.

Back up the custody SQLite database and its operator encryption key together,
following the existing backup procedure. New `wallet_requests` records contain
encrypted bearer codes and request references; outgoing payments add a nullable
request-deduplication key and index. Both migrations are additive. Redis remains
session storage and is not the durable request journal.


## Reviewing interrupted outgoing payments

Funds, Send and scanned-payment errors link to **Payment review**. This is an
application activity log, separate from the user's Acorn transaction history.
Checking history calls the existing Acorn read methods; it never sends, redeems,
refunds or retries a payment. The recent history view is bounded and may be
incomplete. A missing entry or matching amount is not proof of payment failure or
receipt. History lookup failures remain explicitly uncertain.

After attempting a history check, the user can record a recipient report or an
uncertain outcome and acknowledge that the original payment must not be resent.
**Set aside and allow other payments** changes the local journal to `reviewed`;
it does not claim independently verified success or failure. A timestamp, the
user's report and history-check availability are retained in encrypted SQLite.
The original confirmation is permanently non-sendable, and its request identity
remains reserved. Matching reviewed payment intents (wallet/address, amount and
Clear mint/unit, or invoice identity) are also rejected, including previously
prepared confirmations and requests with regenerated IDs. This conservative
policy may block a legitimate later payment of the same amount to that recipient;
operator investigation is required rather than bypassing it in the UI. It cannot
identify a deliberately different replacement invoice or recipient alias as the
same real-world purchase: the user must not arrange a replacement for an
uncertain payment without establishing its outcome.

A currently held Acorn lease prevents review and resolution. Interrupted `sending`
rows additionally require a 120-second grace period from attempt start; legacy
rows get this timestamp at migration. A conditional final write prevents a late
sender from overwriting a reviewed state. Clearing one hold does not clear any
other unresolved payments. No operation changes the Acorn's history or deletes
payment records. The custody SQLite backup includes these recovery records.
