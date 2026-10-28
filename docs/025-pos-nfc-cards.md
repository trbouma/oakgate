# POS NFC card issuance

See [Everyday NFC cards: trust and security](029-nfc-card-trust.md) for the NTAG215 trade-offs, loss response and holder/terminal trust boundaries.

OakGate POS can pair with a signed-in OakGate wallet, prepare an encrypted card
credential, write an NDEF card and verify it by reading it back. This implements
issuance and a confirmed, read-only Cash and Clear balance lookup. Issuance alone
does not authorize login, spending, NWC calls or access to records. Optional
[Keycloak NFC login](027-keycloak-nfc-login.md) requires separate activation and, by default, a PIN; card-only login is an explicit per-card exception. New cards receive a private server-side PIN during issuance;
current payments and balance lookup do not prompt for it.

## Operator flow

1. On a compatible NFC-enabled POS device, choose **Issue NFC card**.
2. The wallet holder uses OakGate's Scan page to scan the pairing QR. A normal
   camera can also open its HTTPS link. Signed-out users sign in in another tab,
   return and continue; the pairing secret is never passed through OIDC.
3. The wallet holder compares the terminal name and six-character pairing code,
   then explicitly chooses **Approve card issuance**. Their wallet displays a
   randomly generated four-digit PIN. They memorize it or store it separately,
   then choose **I have saved my PIN** before the POS can prepare the card.
4. The POS polls OakGate's state and shows the approving wallet's handle. Check
   this label, then choose **Prepare card for this wallet**.
5. Confirm replacement of the intended card's existing contents, choose **Write
   card**, and present the writable card. Existing NDEF contents are overwritten.
6. Remove it, choose **Read back and verify**, and tap it again. OakGate marks it
   issued only after matching the exact prepared credential. A successful write
   alone is not reported as verified issuance.
7. The wallet holder can view and revoke cards through **Preferences → Your NFC
   cards**. Revocation remains available when POS is disabled.

The Web NFC adapter follows Safebox Web's gesture-triggered writes, bounded
payloads, 30-second timeout, cancellation, page-background abort and separate
read-back. A writable NDEF card with at least 496 usable bytes is the target.
Browser writing requires Web NFC support; use a compatible NFC-enabled Android
device with Chrome over HTTPS. Unsupported browsers hide NFC action buttons and do not start pairing. Physical device/card interoperability must be tested on the
actual terminal. See [Chrome's Web NFC documentation](https://developer.chrome.com/docs/capabilities/nfc).

## Pairing and authority

The QR is a fixed same-instance URL:

```text
https://oakgate.example/account/cards/pair#ogpair1.<random-id>.<random-secret>
```

The fragment is not sent in HTTP URLs/access logs. The signed-in page removes it
from browser history and submits it by same-origin POST with session CSRF
protection. This is the callback: OakGate records approval, and the POS obtains
it by signed polling. No caller-supplied callback URL is fetched or redirected to.
The in-app scanner recognizes this exact local route before generic URL handling.

Pairing lasts ten minutes. A terminal-bound idempotency key preserves the same
pairing after retries/reloads. Approval atomically binds it to the authenticated
holder's current Acorn wallet ID, which may belong to a different user from the
terminal owner. Other wallets cannot replace that approval. The POS cannot send
an owner ID, email, address or npub to select the recipient. It receives only a
display label, pairing status and the encrypted bytes needed to write the card.
Every operation retains the existing browser key proof and terminal revocation
checks. Wallet replacement invalidates pending issuance.

This adds a narrow, owner-approved card-issuance operation to the POS. Its funds
permissions remain receive-only. It grants no authority to manage the paired
wallet, access its custody material, or revoke another user's issued cards.

## Private PIN provisioning

Approval generates a cryptographically random four-digit decimal PIN, including
leading zeros. It is disclosed only through the signed-in holder's same-origin,
CSRF-protected pairing page. The POS receives `pin_pending` status, never the PIN,
and cannot prepare a card until the holder acknowledges saving it. The PIN is
not encoded on the NFC card, sent to another instance, or included in card status.

The `nfc_card_pins` table stores a salted scrypt verifier (N=16384, r=8, p=1,
16-byte salt, 32-byte result), bound to the pairing ID and encrypted with the
existing custody key. The row is linked to the card ID on preparation. During
pairing only, a separately encrypted disclosure copy permits the same holder to
retry a lost approval response without changing the PIN. Acknowledgement deletes
that copy; cancellation deletes it too, and expired copies are removed lazily on
subsequent issuance/status calls. The browser clears the PIN when hidden or left.
If the holder loses the page before saving the PIN, cancel issuance at the POS
and start a new pairing. No PIN retrieval or reset UI is implemented yet.

Existing cards and already-approved legacy pairings are not silently assigned a
PIN. Reissue for PIN provisioning. Back up the database and custody encryption
key together. A database-only theft does not reveal the verifier or temporary
PIN; compromise of both database and key still exposes a four-digit PIN to a
small offline search. This is not equivalent to FIDO2 or an unclonable smart card.

PIN provisioning does not enable spending or payment PIN prompts. Optional
[Keycloak NFC login](027-keycloak-nfc-login.md) now verifies this PIN only after
explicit enrollment and fresh authentication. A card without a PIN verifier
cannot become eligible for card login.

## Optional login enrollment request

The private wallet approval screen offers an unchecked **Request card-and-PIN
sign-in enrollment** option. Its explanatory text requires activation after
issuance by verifying the normal Google/email sign-in. Approval stores the holder's initial choice; retrying approval
cannot add, remove or silently change it. The POS cannot submit this choice.

An opted-in request is saved in `nfc_login_requests`, linked first to the pairing
and then to the prepared card. The existing authenticated OIDC issuer and subject
are encrypted with custody storage and bound to the same account owner. No email
matching or client-supplied account identity is used. The request timestamp is
retained. Card read-back verification leaves the request in `requested` state;
it never activates authentication. Cards issued without opt-in remain unchanged.

**Your NFC cards** shows pending requests as not active and allows the holder to
withdraw one without revoking the card's other capabilities. The request is not
included in terminal status or card bytes. The optional Keycloak integration
requires fresh authentication before activation, verifies the stable identity and
current wallet/card binding, requires PIN acknowledgement and verified issuance,
and checks expiry, revocation and withdrawal. This record is consent to enroll,
not a login credential or proof of recent reauthentication.

## Card format, version 2

One MIME NDEF record uses `application/vnd.oakgate.card`. Its binary payload is
bounded to 400 bytes and is deliberately distinct from Safebox Web's private-key
card format.

| Field | Encoding |
| --- | --- |
| Magic/version | Four bytes, ASCII `OGC2` |
| Issuer length | Unsigned 16-bit big-endian |
| Issuer | Canonical UTF-8 OakGate HTTPS origin, at most 200 bytes |
| Issuer service public key | 63 ASCII bytes, canonical `npub` from the instance identity |
| Nonce | 12 random bytes |
| Ciphertext and authentication tag | AES-256-GCM, with the header and `oakgate/nfc/credential/v2` domain bound as additional authenticated data |

The encrypted plaintext is exactly 64 bytes: a random 16-byte card ID, a random
32-byte secret, an unsigned 64-bit issued timestamp and an unsigned 64-bit expiry
timestamp, both big-endian. Lifetime is 365 days. The server maps the card ID to
the approved wallet and stores a SHA-256 secret verifier. There is **no nsec,
recovery phrase, PIN, user npub, account session or POS activation key** on the card.

The public header includes both the issuer origin and its service npub. Both are
bound into AES-GCM additional authenticated data. New issuance requires the
existing configured `OAKGATE_SERVICE_NSEC` identity; no new key is generated for
this pin. The complete payload remains bounded to 400 bytes (at most 361 bytes
with a 200-byte origin).

Changing the issuer's service key invalidates v2 card verification. Acquirers must
match the key advertised by `/info` to the card pin and verify replies against the
pin itself. There is no automatic key rotation or trust-on-first-use fallback.
Reissue cards after a deliberate identity change. Operator service identity
binding already prevents accidental changes during normal startup.

Legacy `OGC1` cards remain readable for local balance lookup, read-back verification
and revocation, but cannot be used for card payments. Reissue them as `OGC2`.
Pending v1 preparations remain byte-for-byte unchanged on retry; cancel and start
new issuance to obtain v2. Never rewrite an already-prepared credential silently.

Encryption prevents reading the secret from the card without the issuer key;
it does not make an ordinary NDEF card unclonable. Read-back proves that the
browser submitted the expected prepared bytes, not hardware possession or
hardware-backed attestation: the issuer browser already held those bytes.

The random secret is not itself a NIP-47 signing key. Future NWC or payment use
must define an explicit permission grant, authentication/PIN policy, limits and
revocation checks. Existing issuance-only cards must not silently acquire spending
or login permissions. Any future Nostr work must use Stroma, and all Acorn
private-key operations must remain in Acorn.

## Persistence and recovery

`nfc_issuer`, `nfc_pairings`, `nfc_cards`, `nfc_card_pins` and `nfc_login_requests` live in the existing custody SQLite
database. A dedicated random issuer encryption key is created once and encrypted
at rest with the operator's custody encryption key. No new `.env` secret is
required. Back up the custody database and its existing encryption key together;
losing the issuer key/mapping makes these cards unusable, not the underlying Acorn.

Prepared card bytes are encrypted at rest only while awaiting verification. They
are returned unchanged after a preparation retry. Verification is idempotent;
a lost success response can be recovered by checking issuance status. After
verification, stored prepared bytes are cleared, retaining the card/secret
verifiers and owner mapping. Expired pending bytes are cleaned lazily on subsequent
issuance/status calls. Cancellation revokes a pending card; it does not revoke a
previously verified card. Owner revocation clears any remaining prepared bytes.

An interrupted write may already have changed the physical card. Read it before
retrying. After expiry/cancellation, a partially written card cannot be verified;
start a new pairing and explicitly overwrite it. Terminal logout or revocation
blocks further terminal operations. Already-issued cards remain owned and
revocable by the holder.

## Deployment and validation

After pushing, run `./refresh-app.sh` and then `./refresh-pos.sh` on Beelink.
Keep the existing POS settings and cookie key; the existing OAKGATE_SERVICE_NSEC
identity must be configured for new card issuance. No new secret is required.
Both public origins must use HTTPS. The POS permits NFC only for its own origin.

Tests cover two-user approval, signed proxy calls, CSRF and origin rejection,
terminal isolation, races, retries, expiry, tampered/wrong cards, wallet replacement,
revocation and encrypted payload size. Mock hardware tests cover explicit consent,
write-only versus verification, MIME/byte matching, timeouts and late callbacks.
Real NFC hardware and card spending are outside those test claims. See the separate
Keycloak login note for login tests and deployment acceptance.

## Available Balance

On an activated POS choose **Available Balance**, tap an issued OakGate card,
then choose **Show available balance**. A compact dropdown selects Cash or a Clear
balance; Cash initially shows local currency with sats underneath, and Clear shows
the friendly asset name and balance in its friendly units. Scanning alone does not send the card or
query its balance. Confirmation sends the encrypted card through the terminal's
existing signed API. This adds balance disclosure only, not payment authority.
Any active terminal on this instance can read a valid presented card; it need not
be the issuing terminal. A copied card can also authorize this read-only lookup.

OakGate validates issuer, authenticated ciphertext, activation, expiry, revocation
and the original wallet binding, then reads Cash and Clear through the Acorn adapter.
The response contains sats, a local-currency estimate using the card holder’s
preference, and Clear asset amounts with public asset labels. Clear keysets are
grouped by exact mint and unit; friendly names never merge different assets. A
Clear lookup failure leaves Cash available with an explicit warning. Missing or stale rates show sats with a currency-unavailable
message. Revocation is checked again after the wallet read. No transaction
history, account identifier or private key is returned to the terminal.

The browser retains card bytes only in memory, requires confirmation, prevents
double submission and clears the display on Done, logout, page backgrounding or
after 60 seconds. NFC scanning stops after 30 seconds. No new configuration or
card rewrite is needed; existing verified cards support this read-only action.

## Receive a payment via card

The wallet Send page can now resolve these cards as recipients, including across
OakGate instances. See [Pay to an NFC card](026-nfc-card-payments.md) for the signed
instance protocol and optional trust policy. This never authorizes spending from
the card holder’s wallet.

## Pay a POS request by NFC

On a secure browser exposing Web NFC (typically Chrome on an NFC-capable Android
device), the POS shows **Pay by NFC** beneath a pending request's QR code. Browser
API availability is only a capability hint; permissions or missing hardware can
still prevent scanning. Unsupported browsers keep the QR flow and hide the action.

The terminal operator selects Pay by NFC and the customer taps their card to pay
the displayed amount. This first version requests no PIN. Possession of a valid,
activated, unexpired, unrevoked card is the bearer authority for this debit; it is
not cryptographic proof of physical presence. Existing valid cards are eligible.
A terminal that captures a card credential could misuse it while it remains valid;
revoke a lost or compromised card. Separate login PIN requirements are unchanged.

Cards may be issued by the local home or another deployed OakGate home, with a
pinned issuer key. Cross-home debit uses the separate signed POS protocol; the
original pay-to-card recipient lookup remains a read-only operation.

The device-signed request supplies only the original receipt key and presented
card credential. The home looks up the terminal-owned receipt and its immutable
code; the terminal cannot supply a new amount, destination or arbitrary invoice
in this operation. The terminal owner's wallet cannot pay itself. Cash invoices
remain Lightning invoices, while Clear requests use the existing Acorn Clear
payment path. Mint fees and backend Lightning restrictions still apply.

The home stores an encrypted receipt-wide debit reservation in `wallet_requests`
before preparing a payment and links it to the existing outgoing-payment journal.
Repeated requests, including another card on the same receipt, cannot initiate
another debit. Existing SendService locks and uncertainty holds remain in force;
user-key operations stay in Acorn. Browser disconnects do not cancel the payment
task. Interrupted preparation or an uncertain send requires review, never an
automatic second payment. No schema migration is needed for these tickets.

A successful send says **Payment sent — confirming receipt**. Existing receipt
polling alone determines **Payment detected** or **Received**. The QR is hidden
after a card is submitted, but an already copied invoice/request can still be paid
externally: never pay the same request by QR and card simultaneously. Cancelling
a screen does not undo a submitted payment. A timeout is not proof of nonpayment.

Deploy both the app and POS images. Test Cash and Clear with small amounts on a
physical supported device; automated tests cannot establish hardware compatibility.

## Cross-home terminals

Existing `OGC2` cards can now be used at another home's POS for debit, confirmed balance lookup, and scoped record presentation. Both homes must deploy the [federated POS protocol](026-nfc-card-payments.md#federated-pos-card-operations). Card issuance and login enrollment remain on the issuing home.
