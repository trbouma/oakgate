# NFC cards and payment execution

**Current capability:** in addition to pay-to-card, POS terminals now support
card-authorized debit, balances and records across independent OakGate homes.
The receiving-only discussion below describes the original recipient-resolution
protocol, not a restriction on the newer POS bearer-card capabilities. See
[Federated POS card operations](#federated-pos-card-operations).

See [Everyday NFC cards: trust and security](029-nfc-card-trust.md) for the NTAG215 trade-offs, loss response and holder/terminal trust boundaries.

The wallet Send page supports a payment address or **Read NFC payment card**.
This pays **to** the card holder. It does not debit the card, log in as its holder,
or give the acquiring instance access to its balance, records or keys.
No PIN is needed to receive a payment.

## Purpose and participants

An NFC card is a portable reference to a custodial Acorn, with a random credential
that its issuing OakGate instance can authenticate. It is not a wallet stored on
plastic. The issuer keeps the account mapping and encrypted custody material;
the card never carries the user's nsec or recovery phrase.

| Participant | Responsibility |
| --- | --- |
| Card holder | Approves issuance to their wallet; receives payments; can revoke the card. |
| Issuing POS | Pairs with the holder, writes the prepared credential and reads it back. |
| Issuing OakGate instance | Encrypts/authenticates the card, maintains its wallet binding, and signs recipient-resolution replies. |
| Acquiring wallet instance | Reads the card through the payer's browser, signs the payment-resolution instruction and prepares the payer's transfer. |
| Payer | Selects funds and amount, reviews the resolved recipient, and confirms payment from their own wallet. |
| Safebox Acorn and Stroma | Acorn performs wallet/private-key operations; Stroma supplies Nostr signing and transport beneath the appropriate service or wallet boundary. |

The POS that originally issued a card does not need to be present when someone
pays to it. The payer and card holder can use different OakGate instances.

## Issuance and the credential

Issuance starts with a terminal pairing QR. The logged-in holder scans it and
explicitly approves the terminal’s pairing code and privately saves a generated
four-digit PIN on their wallet page. The POS never receives that PIN. OakGate binds the request to
that holder's current Acorn. The terminal then prepares the credential, asks for
permission to replace the physical card's contents, writes one NDEF MIME record
(`application/vnd.oakgate.card`), and performs a separate read-back verification.
An acknowledged write alone does not activate the card.

The current `OGC2` payload exposes only routing and verification material: its
version, issuer HTTPS origin and issuer service npub. AES-256-GCM encrypts the
random card ID, random 256-bit secret, issue time and expiry. The complete public
header is authenticated as additional data, so changing its URL or public key
invalidates the encrypted credential. The issuer stores the wallet mapping and
secret/payload verifiers; its card encryption key is separate from user keys.
See [POS NFC card issuance](025-pos-nfc-cards.md) for the binary layout, lifecycle
and backups.

A normal NDEF card is copyable. Encryption conceals the credential's plaintext;
it does not establish physical-card uniqueness. The payment protocol
is limited to receiving payments and confirmed local POS balance disclosure.
Optional [Keycloak NFC login](027-keycloak-nfc-login.md) adds account authentication
only after explicit enrollment and fresh authentication; login requires PIN verification by default, with an explicit per-card exception. A card
is not NWC authorization or permission to debit the holder's funds.

## User flow

1. In Send payment, select Cash or a Clear balance and choose **Read NFC payment card**.
2. Tap the recipient's card using a compatible Web NFC browser over HTTPS.
3. Enter an amount and choose **Review payment**. OakGate contacts the card issuer
   and verifies the recipient. Nothing is sent merely by reading a card.
4. Review the receipt address, asset, amount and applicable fees, then confirm.

The ordinary address path remains available. Card bytes stay in the page's
memory/form until review, cancellation or page backgrounding; they are not saved
in local storage or in the prepared payment. Preparation errors require another
tap. NFC reads time out after 30 seconds. Physical browser/card compatibility still
requires testing on deployment hardware.

## Signed cross-instance contract

The `OGC2` card format includes the canonical HTTPS issuer origin and the issuer
service npub outside the encrypted credential, authenticated together by AEAD.
Legacy `OGC1` cards must be reissued before use for payments. The
acquirer POSTs to the fixed `https://<issuer>/api/cards/v1/recipient` path. This is
a **recipient-resolution instruction**, not a remote debit or settlement API.

The envelope contains `origin` and `event`. Both sides use the operator identity
configured by `OAKGATE_SERVICE_NSEC`, through Stroma in `app/identity.py`.
The signed event uses kind 27235 and exactly these tags:

```json
[["t","oakgate-card-v1"],["purpose","pay-to-card"]]
```

Its JSON content contains:

- `issuer`: exact target HTTPS origin;
- `nonce`: fresh 128-bit random hexadecimal request identifier;
- `card`: base64 of the bounded encrypted binary card payload;
- `amount`: positive whole-unit decimal string;
- `asset`: `{ "mint": "", "unit": "sat" }` for Cash, or the selected Clear mint and unit.

The issuer reads the acquirer's `/info` over HTTPS and verifies the event against
that service's published npub. A claimed origin or a self-signed arbitrary key
alone is insufficient. Events must be within 90 seconds of the server clock.
The issuer validates the card's authenticated encryption, activation, expiry,
revocation and current Acorn binding. It resolves the holder's receipt address
and Acorn public key; it never returns a social npub.

The issuer signs a reply with purpose `card-recipient`. Content contains
`address`, `pubkey` and `request` (SHA-256 of the sorted, compact JSON request
content). The acquirer first requires the issuer's `/info` identity to equal the public key
pinned on the card, then verifies the reply against that pin itself and checks
the request digest, including nonce, amount and asset. It then uses
normal wallet discovery and refuses preparation if `safebox.json` does not match
the signed Acorn key. Card payments fail closed rather than falling back to an
unbound Lightning invoice. Direct Cash and Clear transfer policies remain intact.

Same-instance resolution uses the same signed protocol without a network round
trip. Cross-instance HTTP pins public DNS addresses to TLS, preserves hostname
verification, rejects redirects and nonstandard ports, and bounds time and
response size. The callback never accepts an arbitrary endpoint path.

## Executing the payment

The card instruction identifies **where a payment should go**. Actual movement
of funds happens only after the payer confirms the prepared transfer:

1. The browser submits the encrypted card bytes, selected asset and amount to
   the acquiring instance through the authenticated, CSRF-protected Send form.
2. The acquiring instance resolves the issuer and pinned key, signs the request,
   and verifies the issuer's signed recipient reply as described above.
3. The acquiring instance checks the returned receipt address against
   `safebox.json` (or its own wallet directory for a local recipient). The Acorn
   public key must equal the signed reply. NIP-05 social identity is not used.
4. OakGate saves a prepared outgoing payment with its recipient key, relay,
   amount, asset and applicable fee quote. The card bytes are not needed in this
   journal. The user sees the resolved receipt address and terms for review.
5. On confirmation, OakGate authorizes the payment ID against the payer, acquires
   the payer's wallet lease, checks expiry and unresolved prior payments, and
   atomically changes the journal state from `prepared` to `sending`. Cash fee
   quotes are checked again; changed fees require a new review. Existing Clear
   mint/instance restrictions still apply.
6. The central Acorn adapter calls `Acorn.send_ecash_transfer` for Cash or
   `Acorn.send_clear_transfer` for Clear. Cash passes the payment ID as its nonce
   and the reviewed fee quote. Clear passes the exact mint and unit. Both use the
   reviewed recipient Acorn key and relay. OakGate never signs a user event or
   constructs a user transfer outside Acorn.
7. Acorn carries out the transfer using its existing wallet logic and Stroma
   transport. OakGate records `sent` on success; a timeout, cancellation or other
   uncertain outcome after claiming the payment leaves it `unknown` for review.
8. The recipient's inbox worker discovers and settles the incoming transfer
   through Acorn, including its normal transaction history. A local recipient is
   also woken immediately after sending; other instances use their own workers.

A successful issuer reply means the destination was verified. A sender's `sent`
state means its send operation completed. Neither alone proves that the recipient
has finished redemption and credited the funds. These stages must remain distinct
in status wording.

Repeated confirmation of the same payment ID returns its existing state rather
than submitting another transfer. Uncertain outcomes are never automatically
resent or converted to Lightning. Starting an entirely new reviewed payment is
a separate instruction; the signed resolution nonce is a request/reply binding,
not a global payment deduplication ID.

Card validity and revocation are checked during recipient resolution. Once a
payment has been prepared, confirmation uses the reviewed destination and ordinary
payment expiry; it does not tap the card again or re-run card resolution. Revoking
a card is therefore not a recall of an already-prepared or sent transfer.

## Confirmed balance lookup

The POS **Available Balance** action is separate from the cross-instance payment
endpoint. An activated terminal reads a card and the user confirms disclosure.
OakGate validates the card, reads Cash and Clear balances through Acorn, and checks
revocation again before returning the result. A compact dropdown selects Cash
(local currency with sats underneath) or a Clear asset (friendly name and units).
Clear lookup failure leaves Cash visible with a warning.

This lookup uses the existing signed terminal API on the issuing instance. It
does not expose a public cross-instance balance service. The display is cleared
on Done, backgrounding, logout or after one minute. Browsers without secure Web
NFC support hide NFC action buttons; runtime hardware and permission failures
remain possible on otherwise supported browsers.

## Recovery and trust

Resolution is read-only and may be retried or replayed within its validity window;
it cannot create a second payment. After review, the existing encrypted outgoing
payment journal, one-shot confirmation, uncertain-outcome hold and Acorn settlement
methods remain responsible for funds movement. No new minting, sending or
user-key primitives are introduced. The signed request is not proof of settlement.

By default, any HTTPS-verified signing instance may resolve a presented valid
card. This discloses the receipt address and wallet public key to that instance.
To restrict accepted acquiring instances, set the issuer's optional setting:

```dotenv
# Empty = open to verified signing instances.
OAKGATE_CARD_TRUSTED_INSTANCES=
# Or a comma-separated list of permitted instance service npubs.
```

The list contains **service** identities, not social or wallet keys. Even with an
empty list, unsigned, stale, forged or wrong-issuer requests are rejected. Incoming
requests are bounded and rate-limited. No public card balance endpoint is added.

## Comparison with virtual cards and payment tokenization

OakGate's NFC card is closest to a **tokenized wallet reference**: a separately
revocable random credential maps to an Acorn without exposing its private key.
The current payment capability identifies where funds should be sent. It does
not authorize debiting the holder's wallet.

Virtualization, tokenization and NFC describe different layers and can coexist:

| Approach | What it represents | Typical capability |
| --- | --- | --- |
| Virtual payment card | A digitally issued card credential, without requiring physical plastic | Purchases against an associated account, potentially subject to spending, merchant and expiry controls |
| Payment tokenization | A substitute for an underlying payment-card number | Payments over existing card infrastructure, with token-specific restrictions |
| OakGate NFC card | An encrypted random credential mapped to an Acorn, accompanied by an issuer URL and pinned service key | Receiving Cash and Clear payments and confirmed balance lookup |

A virtual card can itself use tokenization. NFC is a way to present credentials;
it does not determine the account model or authorization policy.
[Visa's virtual card description](https://www.visa.com/en-us/business/cards/virtual-card)
explains configurable spending controls, while
[EMVCo's payment tokenization overview](https://www.emvco.com/emv-technologies/payment-tokenisation/)
describes replacing the underlying primary account number with a restricted-use
substitute. OakGate is not implementing an EMV payment token or claiming card-network
interoperability.

### Shared design principles

OakGate shares the separation between an underlying account and the credential
presented to another party. Each card has its own identity, expiry and revocation
state. Revoking one card does not replace the Acorn or its recovery material.
The issuer resolves the credential to the wallet and enforces its permitted use.

The implementation combines **indirection and encryption**. The random card
credential references a server-side wallet mapping; encryption protects its
plaintext and authenticates the public issuer header. It is not an encrypted
copy of the user's nsec. The current permission boundary remains independent of
whether the credential is carried on a physical card or another presentation medium.

### Different security mechanisms

An ordinary NDEF card stores static bytes and can be copied. Encryption conceals
the credential's plaintext but does not prevent copying the complete encrypted
payload. The pinned issuer key authenticates the responding issuer; the signed
instance request authenticates the acquiring instance and binds the request's
terms. Neither establishes possession of the original physical card or consent
by the card holder to a debit.

EMV payment tokens use dynamic cryptograms and/or enforced domain restrictions
that constrain where a token is usable. OakGate's instance-signed message is not
a transaction cryptogram generated by a secure payment chip.
[PCI SSC describes these token controls](https://www.pcisecuritystandards.org/faqs/1326/).
No equivalent hardware assurance or EMV compliance is claimed here.

Copying an OakGate card grants no spending authority. For explicitly enrolled
cards, the separate [Keycloak NFC login](027-keycloak-nfc-login.md) flow also
requires the PIN and enforces durable attempt limits; possession of both can
allow account access.
It can nevertheless expose the capabilities already permitted: resolving the
recipient through an accepted instance and requesting balance disclosure through
an activated issuing-instance POS. That privacy consequence remains relevant
even though the card cannot debit its holder.

### Implications for future spending

Allowing spending from the holder's wallet would introduce a delegated payment
credential and requires a separate authorization design. That design must cover
explicit holder consent, transaction-bound authorization, spending limits,
expiry, replay protection, revocation, uncertain outcomes and recovery. A PIN
could contribute to that design, but would not by itself make static card data
unclonable. NWC authorization must likewise be explicitly granted; existing cards
must not silently acquire spending privileges.

For the implemented scope, a suitable description is **“an issuer-verified wallet
card for receiving funds and checking balances.”**

## Deployment

Deploy the OakGate app on both acquiring and issuing instances with
`./refresh-app.sh`. Existing `OAKGATE_SERVICE_NSEC` values must be configured and
published by `/info` on both. Preserve the existing bound service identities;
do not rotate keys just to enable this feature. No POS service update is needed. Reissue old `OGC1` cards to put the issuer key
on the card. A changed issuer key fails verification; it is never silently accepted. The issuer must retain its NFC issuer encryption key/database,
and the card holder must have a receipt handle and active wallet.

Tests exercise two distinct instance keys, signed request/reply binding, allowlist
rejection, revoked cards, mismatched wallet discovery, NFC cancellation and existing
one-shot send behavior. Live cross-instance payment and NFC hardware tests remain
deployment acceptance checks.

## Federated POS card operations

An activated POS remains connected to its own home. That home reads the `OGC2`
issuer HTTPS origin and pinned service npub, checks `/info` against the pin **before
forwarding the card**, then calls the fixed `/api/cards/v1/pos` endpoint. No new
card format, shared database, shared encryption key or shared Keycloak is required.
Each home retains its own users, private keys and payment journals.

Requests use the existing Stroma-signed service event format with purpose
`pos-card-request`. Content binds `issuer`, random `nonce`, `operation`, encrypted
`card`, `request_id`, `terminal`, terminal `name`, and operation `data`. The issuer
verifies the acquiring origin's `/info`, signature, 90-second freshness and
`OAKGATE_CARD_TRUSTED_INSTANCES` (empty permits verified signing homes). It checks
its own pinned identity, card activation, expiry, revocation and active wallet.
Replies have purpose `pos-card-result`, with `request` containing the canonical
request digest and `result` containing only the operation result. The acquiring
home checks the reply against the card's pinned key and original digest.

Supported operations:

- `balance`: existing Everyday Funds, local-currency estimate and Community Credits.
  The POS still asks the operator to confirm disclosure.
- `debit`: pay the exact invoice or Clear request from the merchant's durable
  receipt. Browser-supplied destinations and amounts are not accepted by the POS
  route. Explicit Lightning invoices remain Lightning; Clear policy remains unchanged.
- `debit-status`: read the original attempt, never prepare or send a payment.
- `record-open`, `record-status`, `record-present`, `record-cancel`: the existing
  seven categories, case-insensitive exact/slash matching, up to 20 choices,
  single-record simplicity, attachment/PDF preview and OpenETR display.

The issuer performs all user-key operations through Acorn. It returns rendered
record data, not private keys or a general-purpose wallet session. Remote access
receipts are generated in the holder's wallet and identify the authenticated
acquiring domain and its claimed terminal name. Emergency contact messaging stays
at the issuer. Issuing new cards, wallet QR approval and NFC login are not federated.

### Payment retries and recovery

Before network submission, the acquiring home reserves the same durable per-receipt
hold used for local NFC payments, binding it to the card and exact terms. After an
uncertain result, it asks only for status; it never silently submits a fresh debit.
Changing the card or issuer cannot bypass that receipt hold.

The issuer separately claims an attempt keyed by acquiring service npub, terminal
and receipt ID before preparing anything. It binds the card, wallet and exact
invoice/request, saves the outgoing payment ID before sending, and lets the existing
SendService/Acorn journal handle settlement. Duplicate/concurrent requests inspect
the first attempt. Cancellation, crash, missing status or an uncertain send leaves
review required, never an automatic second payment. A missing attempt is not proof
that it is safe to create a new payment. Preparation and transmission may continue
when the HTTP caller disconnects. `submitted` means the sending operation completed;
ordinary receipt polling confirms detection/credit on the merchant side.

A fresh debit must arrive within the receipt's two-minute window. Record sessions
retain the original two-minute lifetime on both homes and are encrypted in the
issuer's ephemeral store. Switching records does not extend the lifetime. Closing
locally succeeds if the issuer is offline; the remote copy expires on its original
deadline. A cancellation tombstone blocks a concurrent preview from reopening it.

### Deployment and acceptance

1. Deploy/rebuild **app and pos on both homes**. No schema migration or Acorn
   dependency change is required.
2. Preserve each home's existing `OAKGATE_SERVICE_NSEC` and NFC issuer data. Both
   `/info` URLs and `/api/cards/v1/pos` must be reachable over public HTTPS with
   valid certificates. Redirects, private DNS targets and nonstandard ports are
   refused. POS must be enabled at both homes.
3. If either issuer has `OAKGATE_CARD_TRUSTED_INSTANCES` configured, include the
   acquiring home's service npub. No new environment variable is required.
4. Use an existing `OGC2` card from home A at home B's terminal. Test balance,
   a small Lightning invoice, a small Clear request of a compatible mint/unit,
   one record and a multi-record category with a PDF attachment.
5. Confirm one debit/credit in the Acorn histories and an issuer-generated record
   access receipt. Repeat a request/status lookup without a second debit. Revoke
   a disposable test card and confirm subsequent disclosure/payment is rejected.

Automated tests use two independent custody databases and service keys, with an
in-process replacement for network transport. They do not establish live DNS,
TLS, reverse proxy, mint/relay or physical NFC interoperability; complete the
above acceptance checks before describing a deployment as verified.

### Trust implications

This extends the existing **no-PIN bearer-card POS debit** policy across homes.
A lost/copied card can be used for these operations by an accepted acquiring home.
Service signatures authenticate the home, not the original physical card or
independent holder consent. Use the issuer allowlist when access should be limited
to known homes. The receiving-only card protocol remains distinct from debit.
