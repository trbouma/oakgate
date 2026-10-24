# Pay to an NFC card

The wallet Send page supports a payment address or **Read NFC payment card**.
This pays **to** the card holder. It does not debit the card, log in as its holder,
or give the acquiring instance access to its balance, records or keys.
No PIN is needed to receive a payment.

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
pinned on the card, then verifies the reply against that pin itself and checks the request digest, including nonce, amount and asset. It then uses
normal wallet discovery and refuses preparation if `safebox.json` does not match
the signed Acorn key. Card payments fail closed rather than falling back to an
unbound Lightning invoice. Direct Cash and Clear transfer policies remain intact.

Same-instance resolution uses the same signed protocol without a network round
trip. Cross-instance HTTP pins public DNS addresses to TLS, preserves hostname
verification, rejects redirects and nonstandard ports, and bounds time and
response size. The callback never accepts an arbitrary endpoint path.

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
