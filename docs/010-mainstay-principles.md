# Mainstay principles and the OakGate trust model

Date: 2026-10-18  
Status: Architectural commitment and implementation review

OakGate belongs to the Mainstay family while offering a different trust model:
a user chooses a provider to hold and operate their Acorn keys. This changes
who has custody, not the underlying Acorn architecture or the commitment to
user independence. OakGate must remain a replaceable convenience around a
portable Acorn, supported by infrastructure that communities can operate.

## Custody is a choice

A user must be able to choose independence at any time. OakGate must not make
continued custody, a Google account, or an ongoing relationship with one
operator a prerequisite for using an independently recovered Acorn. This is a
product requirement, not a claim that the departure workflow is available
today: recovery disclosure and **Go Independent** remain unimplemented.

The provider can use the keys it holds and can see information required to
operate the account. Encryption at rest protects stored data but does not
remove that provider trust. Users must understand this distinction before
connecting or creating an Acorn. Provider access and identity-provider recovery
make everyday use easier, but neither substitutes for a tested recovery path.

## Independence must survive the provider

The [Go Independent design](004-go-independent.md) governs the handover:
provide the complete recovery material, help the user verify independent
access, then end custody after explicit confirmation. Revealing recovery
information alone does not end the relationship.

The user's choice should be available at any time; completing it safely may
require resolving in-flight payments and other work first. The app must show
what is pending and why, rather than silently withholding recovery or deleting
keys while funds are unsettled. It must stop accepting new work when departure
begins and make interrupted handovers resumable.

An independent recovery path must not require a live OakGate login or Google
session. Users need a deliberate way to obtain and retain their own recovery
copy before an operator or identity-provider outage. This is especially
important for newly created Acorns, whose users currently have no recovery
reveal interface. A provider-held copy alone does not meet this requirement.

Recovery must be tested against Acorn's actual requirements: keys, phrase and
derivation mode, bootstrap relay, and any additional state needed for the
supported capabilities. Relays, blob services and mints have their own
availability and backup responsibilities. Independence from OakGate does not
mean independence from all infrastructure or automatic recovery of missing
relay data and mint state.

Ending custody must revoke application access and stop background work without
destroying the user's external Acorn. Backup retention and deletion limits must
be disclosed. Restoring an old backup must not reactivate a departed account.
OakGate cannot prove that every historical copy of a private key was destroyed
or promise exclusive user control merely because it reports deletion.

## Community infrastructure comes first

OakGate should be deployable by a community, cooperative, organization or
individual using infrastructure they control. The present Beelink, external
storage, VPN and Nginx deployment is one example, not a required topology.
Mainstay integration should supply useful local context without making
Mainstay itself mandatory for standalone operation.

Operators can configure the bootstrap relay, mint, public zap relays, public
origin and Keycloak realm. The current `safebox.dev` endpoints and public zap
relays are deployment defaults, not permanent authorities or prerequisites to
owning an Acorn. Changing a default does not migrate existing balances, relay
records or pending payments; those retain their original destinations and need
an explicit continuity plan.

Community operation also means responsibility for matching backups and keys,
restore drills, service availability, account recovery, and an understandable
exit process. Self-hosting alone does not establish user sovereignty. A
community operator must preserve the same custody, privacy and departure
boundaries as any other provider.

Local infrastructure support is incomplete: current URL policies require
HTTPS/WSS and constrain ports; Clear label lookup only contacts public
addresses. Mainstay's scoped local routes and identity-based service discovery
need deliberate integration. Do not bypass those protections globally to add a
local endpoint; introduce an explicit trusted deployment context.

## Google is replaceable

Google is the current upstream sign-in provider. OakGate authenticates against
Keycloak using OIDC and identifies the account by the Keycloak issuer and
subject (`iss`, `sub`). Neither Google identity nor email is the Acorn's
cryptographic identity, and OakGate does not use Google credentials to derive
Acorn keys.

The intended low-disruption replacement is another sign-in method in the same
Keycloak realm, linked securely to the **existing Keycloak user**. Preserving
that user's issuer and subject preserves the OakGate custody association.
Google can then be removed without moving Acorn assets or changing user keys.
This makes Google replaceable at the authentication layer; it is not a promise
of an automatic, one-click migration.

A provider transition must:

1. Establish an alternative login and recovery method before disabling Google.
2. Link it to the existing Keycloak identity with proof of account control;
   never use matching email alone as authority to transfer custody.
3. Verify that the alternative login reaches the same Acorn, preferences and
   payment associations, including after a fresh sign-in.
4. Update Google-specific interface wording and support instructions, then
   retire the old login path once continuity is verified.

Replacing Keycloak itself, changing its issuer URL, or recreating users is a
separate identity migration. OakGate currently has no supported ownership
migration tool for those changes. The owner hash is also bound into encrypted
custody and payment envelopes; changing an issuer setting or editing one row
is not a safe migration. See [identity mapping and backups](008-identity-storage-backups.md).

## One responsibility per layer

| Layer | Responsibility |
| --- | --- |
| OakGate | Custody consent, authenticated workflows, protected persistence, durable job coordination, presentation and departure |
| Acorn | User keys, proofs, records, recovery semantics and portable wallet protocol operations |
| Stroma | Nostr events, signatures, encryption and relay transport |
| Keycloak and its providers | Authentication and identity-provider recovery; not Acorn ownership or wallet recovery |
| Mainstay | Deployment context, infrastructure coordination and installation authority |
| Relays, storage and mints | Their respective delivery, persistence and asset protocol responsibilities |

Every operation using a user private key must go through Acorn methods.
OakGate's separate `OAKGATE_SERVICE_NSEC` signs public zap receipts through
Stroma; it does not replace the recipient's Acorn identity. Service identity is
bound to SQLite, and removing or changing the key after binding prevents
startup. Public identity, operational health and operator commissioning must
remain separate claims.

## Review findings and follow-up work

The 2026-10-18 review confirmed Acorn-owned user-key operations, Stroma use,
separate service identity, encrypted custody, issuer/subject ownership,
ephemeral Redis sessions, Acorn-native transaction history and separation of
Clear balances from cash.

The following gaps remain open:

| Gap | Required outcome |
| --- | --- |
| Cashu protocol execution in `app/payment_mint.py` | Move durable prepare/restore/issue operations behind an Acorn API. OakGate retains coordination and encrypted checkpoints. The current implementation does not use the user's private key directly, but exceeds the desired portable-protocol boundary. |
| Public service information | Add the family information envelope: version, public identity, FIPS address, capabilities, management mode and honest commissioning state; include version in health. |
| Deployment verification | Make the app refresh script wait for health with a bounded timeout and useful failure diagnostics. |
| Recovery and status wording | Do not advertise recovery disclosure as currently available. Keep implemented custody distinct from planned independent recovery and departure. |
| Independent recovery and departure | Implement and test recovery disclosure, independent restoration, settlement-aware departure, deletion retries and protection against resurrection after restore. |
| Provider replacement | Rehearse alternative authentication against the same Keycloak user and update provider-specific presentation. |
| Operational continuity | Rehearse isolated restoration of custody, identity, keys and pending payments before claiming recoverability. |

All 100 application tests passed using the clean Acorn source revision matching
the lockfile during this review. The local installed environment still had an
older Acorn revision and failed 31 tests without that source override. This is
an environment synchronization issue to resolve with `poetry install`, not
proof that the deployed container is broken. These checks did not establish a
successful disaster recovery, provider migration or independent handover.

## Acceptance rule for future changes

Before extending OakGate, ask whether the change preserves independent Acorn
recovery, replaceable authentication, community operation, distinct service
and user identities, and one owner for each protocol responsibility. Test
failures and transitions as well as successful use. If a capability is still
planned, say so where users and operators make decisions.

Family references:

- [Mainstay responsibility boundaries](https://github.com/trbouma/mainstay/blob/main/docs/ECOSYSTEM-RESPONSIBILITY-BOUNDARIES-AND-ITERATION.md)
- [Mainstay house style and service contracts](https://github.com/trbouma/mainstay/blob/main/docs/MAINSTAY-HOUSE-STYLE.md)
- [Service identity and operator attestation](https://github.com/trbouma/mainstay/blob/main/docs/SERVICE-IDENTITY-AND-OPERATOR-ATTESTATION-DESIGN-NOTE.md)
