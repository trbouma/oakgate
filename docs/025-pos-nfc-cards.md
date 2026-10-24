# POS NFC card issuance

OakGate POS can pair with a signed-in OakGate wallet, prepare an encrypted card
credential, write an NDEF card and verify it by reading it back. This implements
issuance and a confirmed, read-only cash balance lookup. Cards do not authorize login, spending, NWC calls or
access to records. No PIN is used in this version.

## Operator flow

1. On a compatible NFC-enabled POS device, choose **Issue NFC card**.
2. The wallet holder uses OakGate's Scan page to scan the pairing QR. A normal
   camera can also open its HTTPS link. Signed-out users sign in in another tab,
   return and continue; the pairing secret is never passed through OIDC.
3. The wallet holder compares the terminal name and six-character pairing code,
   then explicitly chooses **Approve card issuance**.
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
device with Chrome over HTTPS. Unsupported browsers show an explanation and do
not start pairing. Physical device/card interoperability must be tested on the
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

## Card format, version 1

One MIME NDEF record uses `application/vnd.oakgate.card`. Its binary payload is
bounded to 400 bytes and is deliberately distinct from Safebox Web's private-key
card format.

| Field | Encoding |
| --- | --- |
| Magic/version | Four bytes, ASCII `OGC1` |
| Issuer length | Unsigned 16-bit big-endian |
| Issuer | Canonical UTF-8 OakGate HTTPS origin, at most 200 bytes |
| Nonce | 12 random bytes |
| Ciphertext and authentication tag | AES-256-GCM, with the header and `oakgate/nfc/credential/v1` domain bound as additional authenticated data |

The encrypted plaintext is exactly 64 bytes: a random 16-byte card ID, a random
32-byte secret, an unsigned 64-bit issued timestamp and an unsigned 64-bit expiry
timestamp, both big-endian. Lifetime is 365 days. The server maps the card ID to
the approved wallet and stores a SHA-256 secret verifier. There is **no nsec,
recovery phrase, PIN, npub, account session or POS activation key** on the card.

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

`nfc_issuer`, `nfc_pairings` and `nfc_cards` live in the existing custody SQLite
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
Keep the existing POS settings and cookie key; no new configuration is required.
Both public origins must use HTTPS. The POS permits NFC only for its own origin.

Tests cover two-user approval, signed proxy calls, CSRF and origin rejection,
terminal isolation, races, retries, expiry, tampered/wrong cards, wallet replacement,
revocation and encrypted payload size. Mock hardware tests cover explicit consent,
write-only versus verification, MIME/byte matching, timeouts and late callbacks.
Real NFC hardware and future card spending/login are outside those test claims.

## Available Balance

On an activated POS choose **Available Balance**, tap an issued OakGate card,
then choose **Show available balance**. Scanning alone does not send the card or
query its balance. Confirmation sends the encrypted card through the terminal's
existing signed API. This adds balance disclosure only, not payment authority.
Any active terminal on this instance can read a valid presented card; it need not
be the issuing terminal. A copied card can also authorize this read-only lookup.

OakGate validates issuer, authenticated ciphertext, activation, expiry, revocation
and the original wallet binding, then reads cash through the Acorn adapter.
The response contains only sats and a local-currency estimate using the card
holder's preference. Missing or stale rates show sats with a currency-unavailable
message. Revocation is checked again after the wallet read. No transaction
history, account identifier or private key is returned to the terminal.

The browser retains card bytes only in memory, requires confirmation, prevents
double submission and clears the display on Done, logout, page backgrounding or
after 60 seconds. NFC scanning stops after 30 seconds. No new configuration or
card rewrite is needed; existing verified cards support this read-only action.
