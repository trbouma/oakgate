# Policy brief: red teaming OakGate before general release

Date: 29 October 2026  
Status: Pre-release assessment policy; exercise not yet carried out

## The question we must answer

Can someone turn permission to do one thing into permission to do something more
powerful? OakGate makes everyday custody convenient, but convenience must not
silently expand authority. A terminal allowed to receive funds must not gain
control of its merchant's wallet. A card presented for one purpose must not become
blanket permission to disclose records or spend. One home must not impersonate
another simply because both participate in the network.

Red teaming attempts to disprove these promises using authorized adversarial
scenarios. Automated tests, successful demonstrations and container health are
useful evidence, but do not establish that these boundaries withstand abuse.

## Trust model under test

OakGate is custodial: its operator can use the Acorn keys it holds. Encryption at
rest does not protect against an operator or compromised runtime that can access
the decryption key. The assessment must examine how this power is restricted,
observed, disclosed and recovered from; it must not claim the operator is
cryptographically unable to act.

Cheap NFC cards are copyable bearer credentials, not tamper-resistant smartcards.
A PIN can add an online check but does not make a passive tag equivalent to FIDO2
or prevent copying. Explicitly enabled no-PIN operations must be tested as bearer
authority, including revocation, replay and limits. Users must understand the
consequences of losing a card.

**Applications assist; they do not confer authority.** OpenETR verification must
identify the signer, statement and record actually verified. A valid signature
does not establish truth, professional qualification or entitlement. A payment
being detected does not establish final credit. The interface must communicate
these distinctions at the point where people rely on them.

Acorn remains the boundary for user-key operations; Stroma supplies Nostr
operations. Rebuildable helper indexes may assist discovery but cannot authorize
access or replace authoritative checks. Independent recovery must remain possible
within the documented infrastructure requirements. Go Independent and other
planned capabilities must not be presented as already implemented.

## Required coverage

The assessment covers user isolation; authentication and recovery; POS capability
limits; card pairing, PIN policy and revocation; cross-home authentication and
replay resistance; payment interruption and reconciliation; record disclosure and
attachment rendering; verification wording; and deployment, backup and restore.
It includes both misuse by an authenticated participant and unauthenticated
attacks. Operator compromise is examined as a distinct custodial risk.

Use two isolated homes, disposable users and credentials, synthetic records and
a test mint or explicitly capped test funds. Test only systems covered by written
operator authorization. Public relays, hosted identity providers, storage services
and payment providers are not automatically in scope because the app uses them.

## Release decision

Before general release, execute the [detailed exercise](043-pre-release-red-team-exercise.md)
against the intended deployment configuration and frozen application/dependency
revisions. Have a reviewer other than the implementer assess the results; any
external tester needs explicit scope and authorization.

Release requires evidence for every applicable mandatory scenario, closure and
retest of critical and high findings, and no unexplained funds, unauthorized
record disclosure or unresolved authority bypass. A test that could not run is
**blocked**, not passed. Excluding a feature requires actually disabling it and
testing that it cannot be invoked, not merely hiding a button.

Lower-severity residual risks need a named owner, mitigation, due date and written
acceptance by the release owner. Accepted risks must be consistent with public
claims and the custodial trust model. Missing evidence on a material boundary
blocks that feature's release. A clean assessment is scoped evidence, not a
security guarantee or enterprise certification.

## Accountability and disclosure

The exercise coordinator owns scope and stop conditions. Testers record minimal
reproducible evidence. Maintainers remediate findings; an independent reviewer
checks fixes. The release owner records the final decision and deployment scope.
Do not put real credentials or private record contents in reports. Keep detailed
findings restricted until coordinated disclosure is appropriate; public docs
contain the plan and sanitized outcomes, not active exploit credentials.

See [Security Statement](security-statement.md),
[SECURITY.md](https://github.com/trbouma/oakgate/blob/main/SECURITY.md),
[Mainstay principles](010-mainstay-principles.md), and
[the backup and recovery plan](036-backup-and-recovery-plan.md).
