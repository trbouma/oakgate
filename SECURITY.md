# OakGate Security and Custodial Trust

## Purpose and current status

OakGate is the custodial Mainstay client built around safebox-acorn. It holds
recovery material and can operate an Acorn on a user's behalf. A security failure
can expose private records, compromise authentication, interrupt recovery, or
cause loss of funds. This policy describes both the technical boundaries and the
trust users place in their chosen operator.

OakGate is in active development. Successful demonstrations, automated tests and
healthy containers are not evidence of a comprehensive independent security audit
or enterprise certification. This repository makes neither claim. Use small test
balances and non-critical records until the deployment and its dependencies have
been reviewed for the intended use. There is no published long-term security
support schedule; reports should identify the exact revision and dependencies.
See [Project status](docs/project-status.md) for implemented features and remaining
acceptance work.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository under
**Security → Report a vulnerability**, when available. If unavailable, open an
issue asking the maintainer for a private reporting channel, without exploit
details or sensitive data. Do not publish an unpatched vulnerability in a public
issue or discussion.

Include the affected revision, relevant service or endpoint, a minimal
reproduction using disposable identities and test funds, expected and observed
behavior, and the likely impact. State whether exploitation is suspected. Do not
send production keys, recovery phrases, card payloads, PINs, bearer tokens,
Cashu proofs, private records, full database dumps or deployment `.env` files.
Redact logs and configuration while preserving enough context to reproduce the
problem. Do not test against someone else's wallet or deployment without consent.

No response-time SLA or bug bounty is promised. Security-sensitive fixes should
be reviewed and tested, with coordinated disclosure after a fix or mitigation is
available. A suspected compromise of a deployed service also needs immediate
attention from that service's operator; the repository maintainer does not
necessarily administer it.

## Custody is a choice, not a change in ownership

**The guiding principle is user agency over their own data. Choosing a custodian
is an exercise of that agency, not a surrender of it.** Some people want to
manage keys and infrastructure themselves. Others want familiar sign-in,
recoverable access, background payment receipt and an everyday interface that
keeps technical machinery out of the way. OakGate deliberately serves the latter
choice.

The user delegates operation to a provider they trust. That provider may be a
community, cooperative, organization or independently operated home instance.
Everyday Funds, Community Credits and records still use the shared Acorn
architecture. OakGate adds custody, authentication and coordination around it;
it does not create a separate OakGate-only cryptographic wallet identity or make
Google the owner of an Acorn.

Agency is a product and operator commitment, not a claim that the software can
prevent a dishonest custodian from acting. A custodial user cannot enforce
exclusive possession of a private key that the service also holds. Operators
must explain that fact plainly, offer understandable access and revocation
controls, disclose retention and recovery policies, and preserve a practical
path out of the relationship. Convenience must not become hidden lock-in.

### What the operator is trusted to do

OakGate stores encrypted custody material and decrypts it when required to
initialize Acorn. Encryption at rest helps protect a database stolen without its
matching key. It does **not** prevent a sufficiently privileged operator, a
compromised application, or an attacker with both data and decryption keys from
accessing secrets and exercising wallet authority.

Users therefore trust the operator to:

- protect keys, private records, account associations and backups;
- execute only authorized operations and handle uncertain payments safely;
- maintain accurate identity bindings and trustworthy account recovery;
- operate reliable infrastructure and explain outages or loss of availability;
- avoid undisclosed profiling, secondary use or sharing of private information;
- provide recovery material and support departure without destroying the Acorn.

Custody makes unattended receipt and settlement possible, but also concentrates
risk. Compromise can affect multiple users. OakGate is not zero-knowledge storage,
trustless custody, or end-to-end secrecy from its own custodial operator.

## Responsibilities and identity boundaries

| Component | Responsibility and trust boundary |
| --- | --- |
| OakGate | Custody consent, account authorization, protected persistence, payment coordination, scoped delegation and user-facing workflows |
| safebox-acorn | Every operation using a user's Acorn private key, including signing, decryption, records, proofs and recovery semantics |
| Stroma | Nostr protocol handling, validation, encryption and relay transport; OakGate must not invent an alternate protocol implementation |
| Keycloak and upstream providers | Authentication and account recovery; an identity-provider login is not the Acorn's cryptographic identity |
| PostgreSQL and Redis | Durable application/identity state and session state respectively; neither substitutes for the keys and infrastructure needed for recovery |
| Mints, relays and Blossom services | Their own settlement, delivery, retention and availability responsibilities |
| Operator, host and reverse proxy | Trusted runtime, secrets, updates, TLS, routing, backups and administrative access |

Account ownership is bound to the configured Keycloak issuer and subject, not
merely an email address. Google can be replaced by another properly linked login
method without changing the underlying Acorn. Preserve the existing identity
binding and verify continuity; matching email addresses alone must never transfer
custody. Changing realms, issuer URLs or user IDs requires a deliberate migration.
Account recovery is consequently part of the funds-security boundary, including
email security, provider recovery policies and administrator privileges.

NIP-05 is for social identity. Wallet payments, messages and record-sharing
address discovery use `safebox.json` to resolve the Acorn key and relays, without
falling back to a social npub. A service public key identifies the service; a
domain is a route to it. Signatures establish control of a key, not the honesty
or authority of its owner.

The separately configured operator service identity is not a user's key. Its
permitted protocol operations do not authorize bypassing Acorn for user-key
operations. These boundaries are mandatory in [AGENTS.md](AGENTS.md).

## Independence and ending custody

The shared Acorn foundation preserves options for independent clients and
replaceable community infrastructure. It does not automatically make departure
safe or prove that a provider has relinquished access.

**Available today:** authenticated recovery disclosure presents the recovery
phrase, bootstrap relay and recovery mode after a fresh authentication ceremony
and a short-lived, one-use authorization. Users should keep a secure independent
copy before an operator or login-provider outage. Displaying those values does
not close the account, stop background work or revoke the provider's copy.
See [Recovery disclosure](docs/016-recovery-disclosure.md).

**Still planned:** the complete **Go Independent** workflow. Its requirements
include independently testing restoration, handling pending payments without
loss or duplication, revoking sessions and delegated capabilities, stopping
background activity, and removing retained custody material and account
associations. Departure must preserve the external Acorn and its records and
assets. A shared Keycloak identity must not be deleted in a way that disrupts
unrelated services.

Independent recovery also depends on relay records, blob availability, mint
state and the actual Acorn recovery requirements. A phrase by itself is not a
promise that all data and funds can be restored. A recovery demonstration must
verify the supported capabilities, not just reproduce a public key.

The operator must disclose backup and log retention, any justified retention
exceptions, and what remains pending after departure. Restoring an old backup
must not silently reactivate departed accounts or revoked authority. Deletion
cannot prove that an operator or historical recipient kept no copy. Exclusive
control after custody would require an appropriate, supported migration of
keys/assets and access, not simply an assertion of deletion. Do not assume such
a migration is implemented.

This distinction is central to the [Go Independent design](docs/004-go-independent.md)
and [Mainstay principles](docs/010-mainstay-principles.md): users should remain
free to choose independence, while the service must be honest about the current
means of achieving it.

## Everyday convenience and delegated access

POS terminals have a separate, limited interface and revocable activation rather
than the merchant's full account login. Browser-bound credentials reduce some
replay opportunities but do not make a compromised browser or terminal trusted.
As terminal capabilities expand, their scopes must be reviewed explicitly;
receiving, card issuance, balance disclosure, record presentation and card debit
have different consequences.

Inexpensive NFC cards contain a revocable credential, not the Acorn private key
or recovery phrase. They are copyable memory tags, not cryptographic smart cards
or FIDO2 authenticators. Encrypting their payload does not prevent copying the
whole payload. The current POS card-payment flow can debit a valid same-home
card without a PIN; card-based record presentation and balance lookup likewise
have disclosure implications. Do not describe these cards as receive-only.

Login enrollment is separate. PIN policy applies to the flows that actually
check it; generating a PIN does not protect every card operation. Card-only login
is a weaker option, and successful login grants the permissions of that account
session. A four-digit PIN with online attempt controls is useful but is not
equivalent to hardware-backed phishing-resistant authentication. Lost or copied
cards should be revoked promptly. See [NFC card trust](docs/029-nfc-card-trust.md)
and the current [POS card flows](docs/025-pos-nfc-cards.md).

Record presentations deliberately disclose information to a recipient. Closing
a request or clearing the screen cannot erase screenshots or copies already
made. An OpenETR anchor and its green check indicate anchor evidence was found;
they do not independently certify the holder's identity, the truth of a statement,
or the publisher's institutional authority. Social profile names are
self-published metadata. Presentation receipts and emergency contact messages
are best effort, not complete audit records or emergency-response guarantees.

## Payments, privacy and continuity

Payment attempts must preserve durable recovery state, wallet mutation guards
and duplicate protection. A timeout is not proof of failure. Never clear an
uncertain-payment hold, delete a recovery journal or resend solely to make an
error disappear. Reconcile with Acorn and the relevant mint before retrying a
consequential operation. A detected incoming payment is distinct from confirmed
credit.

Ecash does not eliminate mint trust. Mint availability, solvency, fees and
settlement behavior remain separate risks; Clear program backing and redemption
are commitments of the issuer/program. OakGate does not guarantee them. The
existing acceptance policy of trusting a mint from which Acorn successfully
receives is not a solvency assessment or endorsement.

Custody links login identity, preferences, wallets and activity at the operator.
Relays, mints and storage providers can observe metadata even when payloads are
encrypted. OakGate does not promise anonymity, traffic-analysis resistance,
uncopyable records, censorship resistance against every dependency, or service
availability during an operator outage.

## Operator security and recovery obligations

- Keep secrets out of source control, images, public documentation, command
  output and support logs. Examples name settings but must not contain live
  values. Protect deployment `.env` files and use restricted secret delivery
  appropriate to the environment.
- Separate application, database and identity-service privileges. Keep database,
  Redis and administrative surfaces private; internal reachability is not itself
  authorization. Restrict Keycloak administration and test each enabled login
  and recovery flow.
- Use HTTPS/WSS on external routes. Trust forwarded headers only from designated
  proxies and restrict access to upstream ports. The proxy and served browser
  code are part of the trusted path.
- Review dependency locks, image provenance and upgrades. Apply migrations with
  a verified backup and a recovery procedure that accounts for external payment
  effects; rolling a database back cannot undo a payment.
- Preserve matching encrypted custody data, operator keys, Keycloak identity
  state, service identity, grants, configuration and software versions. Use
  PostgreSQL-native backups rather than copying a live database directory.
  Keep protected off-host copies and rehearse isolated restoration. Restore with
  fresh sessions, and reconcile payment and revocation state before resuming work.
- Back up operated relays, blobs and mints separately under their own supported
  procedures. A healthy app or a database backup alone does not establish
  recoverability. Do not overwrite newer mint state with an old app snapshot.
- Define incident response, user notification, access review, retention and
  departure responsibilities before offering a custodial service.

The [backup and recovery plan](docs/036-backup-and-recovery-plan.md) is a plan to
implement and rehearse, not a claim that automated backups or a successful
restore exist for every deployment.

## Maintaining this policy

Review this policy when authentication, custody, payment recovery, delegated
capabilities, discovery, retention or departure behavior changes. Security
controls must preserve Acorn's recovery semantics and Mainstay's separation of
responsibilities, not merely make a demonstration work. Document limitations
where users make decisions, and distinguish implementation from tested recovery
and independent assurance.

Family policies: [Acorn](https://github.com/trbouma/safebox-acorn/blob/main/SECURITY.md),
[Stroma](https://github.com/trbouma/stroma/blob/main/SECURITY.md),
[Mainstay](https://github.com/trbouma/mainstay/blob/main/SECURITY.md), and
[Grove](https://github.com/trbouma/grove/blob/main/SECURITY.md).
