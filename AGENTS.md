# OakGate architectural boundaries

## User private keys: mandatory Acorn boundary

Every operation using a user's Acorn private key must go through an Acorn method.
This is a hard architectural requirement, not a preference. It includes key and
recovery-phrase generation/derivation, public-key derivation from a private key,
signing, encryption/decryption, and creation/publication of user Nostr events.

OakGate may store encrypted custody material, recover that opaque material for
Acorn initialization, and pass it through the central adapter in `app/wallets.py`.
Custody encryption uses the separate operator custody key; it does not authorize
using a user's nsec as an application cryptographic primitive.

Use Acorn methods for proof delivery, transaction history, records
and public identity. OakGate may persist opaque prepared results for durable
retry, but must return them unchanged to Acorn for delivery. User-facing cash
history must be read from Acorn, never synthesized from OakGate's local journal.

If the required Acorn method is missing, extend Acorn rather than reproducing its
key operations in OakGate. Do not import Nostr key/signing/encryption helpers or
construct/sign/publish user events in application code. Public-only signature
validation of incoming requests is allowed. Cashu's independently generated
blinding factors are not the user's Acorn private key; never derive them from it.

An exception requires a concrete documented rationale and explicit approval
from the project owner before implementation. Document its scope, alternatives,
risks and removal plan. Convenience or avoiding an Acorn API change is not a
sufficient rationale. No user-key-operation exceptions are currently approved.

The operator-owned service key is distinct from every user key. As explicitly
requested by the owner, `app/identity.py` may use Stroma to derive the service
public identity, sign/publish zap receipts, and sign/verify NFC card payment
recipient-resolution messages. Its only secret source is
OAKGATE_SERVICE_NSEC; it must never accept user custody material. This does not
relax the Acorn boundary for user-key operations.

Run `tests/test_acorn_boundary.py` with relevant functional tests after changes.
Keep Acorn source changes and OakGate's pinned dependency coordinated; local
source-override tests do not establish container deployability.

## Nostr: mandatory Stroma dependency

All Nostr protocol, validation, signing, encryption and relay transport must use
our `stroma-nostr` library. Declare it directly in OakGate's dependencies rather
than relying on Acorn's transitive dependency. Public-only validation can call
Stroma directly; operations using user keys must still go through Acorn methods,
which use Stroma underneath. Do not add alternate Nostr libraries or hand-built
relay frames. Extend Stroma when a required protocol capability is missing.

## Mainstay trust and continuity commitments

Custody must remain a choice. Preserve a path to independent Acorn recovery and
Go Independent without permanent reliance on OakGate or Google. Community-run
infrastructure and standalone deployment remain first-class use cases.
Google is an upstream authentication option, not the user's wallet identity.
Provider transitions must preserve the existing issuer/subject mapping or use
an explicitly designed, verified migration; never transfer custody by email.
Do not advertise recovery, departure, commissioning or restoration capabilities
as implemented until their acceptance checks pass. Consult
`docs/010-mainstay-principles.md` for the review and outstanding boundary work.
