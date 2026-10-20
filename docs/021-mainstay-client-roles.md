# Mainstay client roles and the path to independence

Date: 2026-10-20  
Status: Agreed product direction; full Go Independent workflow remains planned

OakGate is positioned as the primary Mainstay client for everyday use.
Safebox Web is positioned as the experimental non-custodial client. Both build
on the same safebox-acorn architecture. Their roles differ in who holds the
user's secrets and takes responsibility for recovery and ongoing operation.

## OakGate as the primary client

OakGate should be the welcoming entry point for people who want to hold funds
and records, send payments, and communicate with other wallets without managing
keys in everyday use. Familiar registration, sign-in and account recovery make
that experience accessible. Custody also allows authorized services to continue
while the user is offline.

Primary-client status sets a development priority, not a claim that every
workflow is complete or every deployment is production-ready. Reliability,
clear payment status, safe retries, tested backups, recovery and a compact
mobile interface take priority over exposing protocol details. Uncertain
payments must remain recoverable without risking a second payment.

OakGate holds sensitive Acorn recovery material on the user's behalf. This is
substantial provider trust: encryption at rest does not remove the operator's
ability to use the keys. Account recovery through Keycloak restores access to
the existing account; it must preserve the exact issuer/subject mapping rather
than transfer custody based on matching email addresses. Google remains an
optional upstream sign-in provider, replaceable without changing Acorn identity.

## Safebox Web as the experimental non-custodial client

Safebox Web provides a place to explore new Acorn capabilities and serves users
who prefer responsibility for their own keys. Experimental describes its product
role; it does not relax payment safety, compatibility or private-key boundaries.

Public preferences and discovery information may be stored by the application.
Private keys are used only during an authenticated session and are never
persisted server-side. Users therefore carry the recovery responsibility, and
unattended operations requiring their keys need an available signer or an
explicit delegation arrangement. Non-custody still requires trust in the
software handling secrets during a session.

Useful experiments can inform OakGate's everyday experience once their behavior
and recovery paths are understood. Neither client must implement every feature
at the same time, and shared-library changes must preserve existing callers.

## One Acorn architecture

The clients share the Acorn foundation for funds, records, wallet messages and
recovery semantics. OakGate provides a custodial layer around those capabilities;
it does not introduce a separate wallet identity or proprietary funds format.

User private-key operations in OakGate must go through Acorn methods. Stroma
provides Nostr protocol and transport support. NIP-05 resolves social identity;
`safebox.json` resolves the Acorn key and relays for wallet routing. A social npub
must never replace the destination Acorn key for funds or wallet messages.

Client choice must remain compatible with community-operated infrastructure.
Mainstay integration should add value while preserving standalone deployment
and the ability to choose providers. Shared architecture supports continuity,
but independent recovery still depends on available relay data, blob storage,
mints and the complete recovery material required by the supported features.

## Go Independent remains a commitment

A user must be able to choose to end OakGate custody and continue using their
Acorn independently. This is more than exporting information or signing out.
The intended flow provides complete recovery material, verifies independent
access, safely handles in-flight work, and then ends the provider relationship
through explicit confirmation and coordinated deletion.

Departure must stop background activity and revoke OakGate access. It must
respect shared identity-provider accounts, disclose backup retention, and
prevent an old backup from silently restoring custody. OakGate cannot prove
that no historical key copy remains or promise exclusive control merely by
reporting deletion.

Recovery disclosure with fresh authentication is available today. It does not
end custody. The full handover, independent-access verification and coordinated
deletion workflow remain planned. Every new custodial feature must account for
how it will stop or transfer responsibility when the user goes independent.

## Related designs

- [Custody models](006-custody-models.md)
- [Mainstay principles](010-mainstay-principles.md)
- [Go Independent](004-go-independent.md)
- [Recovery disclosure](016-recovery-disclosure.md)
- [Safebox address discovery](018-safebox-address-discovery.md)
