# Everyday NFC cards: trust and security

## Design decision

OakGate targets **NTAG215**, an inexpensive, replaceable card used with an ordinary
NFC-capable Android phone. The aim is accessible daily use without requiring
specialist smart cards or dedicated secure readers. The project's purchasing
assumption is approximately **25 cents per card**, supplied by the operator;
this is not a verified market quotation or a promise about currency, quantity,
shipping or reader cost.

We deliberately place most controls in the online custodial service rather than
in tamper-resistant card hardware. A user can revoke a lost card from their wallet
and issue a replacement. Where login is enabled, they can retain the default PIN
requirement or explicitly accept the greater risk of card-only login.

This is a trade-off between cost, convenience, trust and exposure, not a claim
that a cheap memory tag provides the same protection as a cryptographic smart
card, FIDO2 authenticator or certified payment terminal. The service still needs
secure operation, backups, protected keys and a trustworthy user interface.

## What the card represents

The card is an encrypted, revocable reference to a custodial Acorn. Funds and
records are not stored on the plastic. The card contains neither the user's nsec
nor their recovery phrase. Losing the physical card therefore does not itself
lose the wallet's underlying recovery material.

The current OGC2 record contains the issuer HTTPS origin, pinned service npub,
and an authenticated encrypted credential: random card ID and secret, issue time
and expiry. The service maintains its account binding and status. The PIN and
PIN policy are server-side and are not written to the card.

For `https://oakgate.safebox.dev`, the payload is 188 bytes and the NDEF record is
approximately 219 bytes, or about 222 bytes including typical Type 2 wrapping.
NTAG215 has 504 bytes of user memory, leaving comfortable capacity for this format.
Future changes must account for encoding and tag-format overhead and be tested
on NTAG215. See [NXP's memory specification](https://www.nxp.com/docs/en/data-sheet/NTAG213_215_216.pdf).

## Possession is an assumption, not proof of an original card

Keeping the card in the holder's possession is the basic practical protection.
However, the service authenticates the **credential read from the card**, not a
unique physical object. A compatible reader or compromised terminal can copy the
NDEF bytes. A copy may work while the legitimate card remains in its owner's pocket.

Authenticated encryption conceals the private credential fields and detects
modification. It does not prevent copying or replaying the complete encrypted
blob into a fresh request. The tag UID, proximity of a tap and a successful
read-back are not treated as unclonable possession proofs.

A reader sees the public issuer identity and opaque card bytes. Repeated reads
can correlate the same credential, even without decrypting it. A legitimate
recipient-resolution operation also discloses the receipt address and Acorn
public key to the acquiring instance. The card is not an anonymous identifier.

The issuer validates activation, expiry, revocation and current wallet binding.
These controls constrain a copied card, but depend on the service being online
and its durable state being current. There is no offline authorization guarantee.

## Capabilities and their actual protections

The following describes the implementation today, not future NWC or debit powers.

| Capability | Current authority and checks | Exposure if copied |
| --- | --- | --- |
| Receive Cash or Clear through pay-to-card | Payer is signed in, reviews recipient/asset/amount and confirms spending from their own Acorn; issuer validates the card and signs destination resolution | Copy can identify the same recipient; it does not directly authorize debiting that recipient |
| Available Balance | Activated issuing-instance POS and confirmed disclosure; card validity checked, including revocation before returning balances | An attacker with a copy and access to an authorized terminal could see balances; UI confirmation is not independent holder authentication |
| POS record presentation | Activated same-home terminal, valid card and a request limited to `whoami` or `myinfo`; card and wallet rechecked before retrieval | A lost or copied card can disclose those records without a PIN; clearing the screen cannot erase information already seen |
| Keycloak login with PIN | Explicit holder enrollment, fresh normal authentication to activate, valid card, server-verified PIN and existing enabled Keycloak user | Copy alone is insufficient while PIN checking is enabled; copy plus PIN can authenticate |
| Keycloak card-only login | Explicit per-card policy choice, risk acknowledgement and fresh normal authentication | Copy alone can authenticate; this is a substantially stronger capability than receiving payments |
| Direct debit/NWC from card | Not currently granted by this card protocol | Must receive a separate capability and risk design before implementation |

**Payment, balance and POS record-presentation operations do not currently prompt for the PIN.** Generating
a PIN during issuance does not automatically protect every card capability.
Conversely, successful card login creates a normal OakGate session, with the
wallet actions that session permits, including sending payments. Describing the
card as receive-only would therefore be misleading for a card enrolled for login.
Sensitive recovery disclosure and card-policy changes still require fresh normal
Google/email authentication.

The implemented signed payment instruction is recipient resolution for
**paying to** a card, not authorization to debit the holder. See
[NFC payment execution](026-nfc-card-payments.md).

## PIN: useful online protection, with clear limits

Issuance generates a random four-digit PIN, including leading zeros. The holder
sees it privately in their signed-in wallet, saves it separately and acknowledges
it. The POS receives neither the PIN nor the user's normal login credentials.
An encrypted, salted scrypt verifier is stored server-side; the temporary encrypted
PIN disclosure copy is deleted on acknowledgement. The PIN is not retrievable
later through a PIN-recovery screen; reissue if it is forgotten.

For PIN-required login, five wrong PIN attempts durably lock that card's login.
The count survives restart and is not reset by a successful login. Fresh normal
account authentication is needed to unlock it. The authenticated Keycloak
backchannel and one-use challenge bind verification to the login attempt; they do
not make the card itself cryptographically unclonable.

A randomly generated four-digit PIN has 10,000 possible values. Five distinct
random guesses against one card have a 0.05% chance of success, **assuming** the
PIN remains unknown and the online limit cannot be bypassed. This is a narrow
illustration, not an overall security rating. Observed PIN entry, phishing,
compromised devices or a leaked PIN defeat that assumption. Someone with a copied
card can also deliberately exhaust attempts to inconvenience its owner.

Protecting the encrypted verifier and custody key matters: compromise of both
allows offline guessing of a small PIN space, outside the online lockout. A PIN
is reasonable additional protection against casual misuse of a lost card under
these assumptions; it is not equivalent to a hardware-backed signing key.

The holder may disable PIN checking for login only through the explicit per-card
policy flow. This convenience choice should remain visible and deliberate. It
does not create an equivalent alternative security factor.

## Revocation and a lost-card response

A holder with normal wallet access can use **Preferences → Your NFC cards** to
revoke the lost card without possessing it. Revocation applies to all copies of
that credential because they share the same server record. Reissue creates a new
credential; changing the writing on the physical card is not the revocation step.

For a lost or suspected copied card:

1. Sign in through the normal Google/email route on a trusted device.
2. Revoke the card in Your NFC cards. If desired, withdrawing login enrollment
   alone stops new card logins but leaves the other card capabilities available.
3. If the card had login enabled, review recent wallet activity and consider
   sessions already established before revocation. Contact the operator if access
   may have been abused; Keycloak and OakGate sessions require separate attention.
4. Issue a replacement and keep its PIN separately. Do not reuse the old card's
   credential or restore its active state from an old backup.

Revocation stops subsequent checks; it does not undo completed actions. In
particular, it neither cancels a previously prepared payment to the holder nor
terminates an already-issued OakGate or Keycloak session. OakGate does not yet
implement Keycloak backchannel logout for its Redis sessions. The ordinary default
OakGate session lasts a fixed week. The UI does not currently offer a complete
card-linked session revocation system.

Revocation also needs network access and access to the normal account. Recovery
through the identity provider remains part of the custodial trust model. If the
issuer is unavailable, neither immediate revocation nor online card use is assured.

## Android issuance for an iPhone holder

The design separates **holder authorization** from **physical NFC writing**:

1. A provisioned Android POS displays the issuance pairing QR.
2. The holder scans it with their iPhone, signs in to their own OakGate wallet,
   checks the terminal name/pairing code and approves issuance.
3. Their own wallet displays the PIN and optional login-enrollment choice.
   They save the PIN and acknowledge it on that device.
4. The Android terminal receives only the prepared encrypted card data, writes it
   and reads it back. OakGate activates the card only after matching read-back.
5. If login was requested, the holder separately completes fresh normal
   authentication to activate that enrollment.

The Android phone is the writer, **not the authority selecting someone else's
wallet**. The logged-in holder authorizes issuance, even when their own browser
cannot write NFC. This avoids handing a shared terminal the holder's password,
PIN or recovery phrase. A compatible Chrome/Android device can perform the NDEF
operations; see [Web NFC's scope and browser requirements](https://developer.chrome.com/docs/capabilities/nfc).

This workaround enables issuance for an iPhone owner; it does not add Web NFC to
Safari or make NFC login available on their iPhone. The terminal also remains a
trust boundary: it necessarily handles copyable card bytes and a malicious writer
could retain them. Separate holder authorization prevents arbitrary account
selection, not credential copying. Use trusted, maintained terminals, especially
when cards will also enable login. PIN entry on a later compromised reader is a
separate risk.

## Mainstay identity and service boundaries

The issuer service public key is the stable identity. The encoded domain is the
current route to that service, not a substitute for verifying its key. The
acquirer checks the service identity against the card's pin and verifies the
signed response bound to its request. A different key at the same domain fails.
The public header is also authenticated by the issuer's credential encryption.

The current implementation still requires the encoded issuer origin. Automatic
domain relocation and service-key rotation are not implemented: they require an
authenticated migration/discovery design or card reissuance. Never silently trust
a replacement key merely because it is served from the old domain.

The issuer service key, holder's Acorn key and optional social npub are different
identities. Wallet routing uses Acorn identity and `safebox.json`, not social
NIP-05. User-private-key operations remain inside Acorn; service signing uses
Stroma with the operator's separate identity.

The optional `OAKGATE_CARD_TRUSTED_INSTANCES` list restricts recipient resolution
by acquiring **service npub**. Its default empty value allows verified signing
instances, not anonymous or unsigned instructions. An allowlist is not a secure
reader guarantee or a substitute for holder authorization.

## What is trusted, and what remains future work

The holder trusts the custodial operator with wallet material and correct
execution, the identity provider for account authentication/recovery, and the
service's current card and payment state. The operator must protect custody and
service keys, restrict administrative access, avoid logging card/PIN payloads,
and preserve backups without resurrecting revoked credentials or stale payments.
TLS and signed service messages protect particular links; they do not remove
custodial trust or make a compromised issuer honest.

No offline payments, direct card-debit authorization, NWC spending capability,
daily card spending caps or merchant-specific spending permissions are claimed
here. Any future debit capability needs explicit enrollment, transaction-bound
authorization, amount/asset limits, durable retry/deduplication, revocation and
PIN policy designed for that capability. Do not silently expand an existing
receive/balance credential into spending authority.

The card is replaceable convenience infrastructure, not the user's recovery
root. The shared Acorn architecture and Go Independent commitment remain in place;
full departure/deletion automation is still separate work. Cheap hardware is a
useful accessibility choice when the copyability, online dependency, scope of
permissions and loss response are made understandable to the holder.

See also [issuance](025-pos-nfc-cards.md), [payment protocol](026-nfc-card-payments.md),
[Keycloak NFC login](027-keycloak-nfc-login.md) and
[Keycloak operations](028-keycloak-operations.md).
