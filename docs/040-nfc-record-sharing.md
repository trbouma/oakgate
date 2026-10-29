# Share a record to a scanned NFC card

A wallet user can open a record, choose **Share**, then **Share to NFC Card**.
The NFC action appears only in a secure browser that supports Web NFC (for
example, Chrome on a compatible Android phone). The QR option remains available.

1. Create the usual temporary sharing copy.
2. Tap the recipient's paired OakGate card.
3. Review the recipient handle, issuing home and record label.
4. Confirm sharing. The recipient's home imports the copy through Acorn.

The recipient does not need their phone. The record is stored in their Acorn,
not on the NFC card. New shares append the sender–content–recipient sharing fingerprint to the category path, matching QR sharing. For example,
`benefits/dental/<digest>` displays as a compact fingerprint while retaining its
filing path. See [Record paths and fingerprints](041-record-fingerprint-labels.md)
for duplicate detection, updates and explicit custom labels. An existing label, compared case-insensitively,
is never overwritten by this flow. The recipient can subsequently manage the
record in their wallet. This is record receipt, not proof of the sender's claims;
OpenETR verification remains a separate operation.

## Across independent homes

The browser talks to its own OakGate app. That app reads the issuer URL and
pinned service public key from the card, verifies `/info`, and sends signed
requests to the fixed `/api/cards/v1/records` endpoint at the issuer. The issuer
verifies the sending home's service identity, optional
`OAKGATE_CARD_TRUSTED_INSTANCES` allowlist, card validity and current wallet
binding. A changed issuer public key fails verification.

Requests and replies are authenticated through the existing Stroma-backed
operator service identity. The card selects the Acorn wallet directly; social
NIP-05 identity is not involved. All user-key operations, transfer inspection,
decryption and record import remain in Acorn. The receiving home's
`OAKGATE_RECORD_ALLOWED_SERVERS` policy still applies: a foreign home's sharing
storage server is not automatically trusted. Public HTTPS address validation and
redirect restrictions remain in force.

## Consent and the card trust model

The sending user explicitly confirms delivery after scanning the card. This
initial flow uses the existing paired card credential without a PIN. A copied
card credential can therefore be used to direct unwanted records to its wallet;
a tap is not cryptographic evidence of the holder's consent or identity. Card
revocation prevents subsequent authorized operations. Receiving records does
not authorize spending funds, reading other records or signing in.

## Delivery status and recovery

Both homes persist encrypted, owner-bound delivery journals in the existing
`wallet_requests` table. Sender, card, record terms and recipient wallet are
bound to one attempt. Concurrent confirmations and repeated submissions cannot
start another import for that attempt. A recipient-wallet lease protects the
label check and import, and is renewed during the operation.

An accepted import is shielded from a disconnected caller. A successful Acorn
result plus record-list readback produces **Record received**. If a process
crashes or an import outcome is uncertain, **Check delivery status** only queries
the original attempt. It never repeats the import, even if the sharing code has
expired. There is deliberately no automatic reconciliation based solely on a
matching label: that would not prove which write created it.

Ask the recipient to check Records before creating a new share after an
uncertain outcome. Existing attempts remain available through **Active shares →
Review NFC delivery** while that sharing entry exists, or the saved delivery
page URL. A new share must not be used to bypass an unresolved delivery.

The existing two-minute sharing expiry still applies before import. Acorn
attempts cleanup of the temporary sharing copy after receipt; cleanup failure
does not undo receipt. Copies already received cannot be recalled. Manual Stop
sharing remains available through Active shares.

## Deployment and validation

Rebuild and deploy **app** at each participating home. This change needs no POS
rebuild, new environment variable, card re-pairing, database migration. Fingerprint naming requires the additive Acorn transfer
metadata and deployment order described in the linked record-label note. Keep service identities stable and configure permitted
sharing storage servers where homes use different infrastructure.

Automated tests cover local and cross-home delivery with independent stores and
service keys, duplicate/concurrent submissions, uncertain writes, expiry,
existing labels, browser confirmation, CSRF, account isolation and NFC reader
cleanup. Live device and cross-home acceptance testing remains necessary after
deployment; automated transport and Acorn stubs are not a live deployment test.
