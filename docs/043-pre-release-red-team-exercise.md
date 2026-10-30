# Pre-release red-team exercise

Date: 29 October 2026  
Status: Planned; no scenario below is recorded as passed

This runbook implements the [red-teaming policy](red-teaming-policy-brief.md).
It is a release exercise, not permission to test public infrastructure. Functional
success must be demonstrated alongside rejection of unauthorized operations.

## 1. Authorize and freeze the exercise

Record the following before testing:

| Item | Required record |
| --- | --- |
| Scope owner and release owner | Named people who authorize testing and decide release |
| Testers and independent reviewer | Named people; reviewer is not the sole implementer |
| Targets | Exact hosts, domains, containers, networks and third-party permissions |
| Release candidate | OakGate, Acorn, Stroma and NFC Keycloak provider commits; lockfile; image digests; schema revisions |
| Configuration | Redacted deployment configuration; enabled features; PIN/bypass policies; issuer identities; relay/mint/storage endpoints |
| Safety envelope | Test window, request/concurrency ceilings, total funds budget, permitted failure injection and stop contact |
| Evidence location | Restricted storage, access list, retention deadline and responsible owner |
| Recovery baseline | Verified isolated backup, restart procedure and known initial balances |

Map actual routes and workers from the frozen code to the scenarios below. Do not
invent endpoints or assume older docs describe the deployed build. Inventory
browser-to-home, POS-to-app, home-to-home and service-to-infrastructure boundaries.
Exercise direct requests as well as visible buttons.

Stop immediately for out-of-scope traffic, real credentials or personal records,
unexpected real-fund movement, uncontrolled retries, unexplained balance changes,
or resource use beyond the agreed ceiling. Preserve evidence and contact the
coordinator. Do not repeatedly resend an uncertain payment or clear its journal.

## 2. Build the test environment

Use two homes, A and B, with separate databases, service identities, origins and
controlled relay/storage endpoints. Use PostgreSQL and the actual reverse-proxy,
Keycloak and Redis configuration intended for release. Mock or locally host
external dependencies where authorization does not cover active testing.

Create Alice and Bob on A, Carol on B, and a merchant on each home. Give each a
known Acorn npub and record the user/issuer/subject mapping. Use different browser
profiles, including two users on a shared device. Configure the enabled sign-in
methods with test accounts. Add:

- One receive-only merchant terminal per home, plus a revoked terminal.
- Cards with payment/record/login permissions as supported; PIN-required and
  explicitly permitted no-PIN configurations; an enrolled login card, a revoked
  card, and a copy of a disposable card credential.
- Known small cash and Clear balances, two distinct Clear units, and a ledger of
  test operation IDs. No production funds or customer cards.
- Synthetic text, image and PDF records; `whoami`, `member`, `pass`, `health` and
  nested `Benefits` records; one original file with controlled OpenETR evidence.
- More than 40 user records spread across relay pages, with internal records,
  timestamp ties, mixed-case paths and fingerprint labels. Include another user's
  records and same-label records on a different relay as negative controls.

Never place secrets in command-line arguments, screenshots, shared reports or
source control. Use local hidden prompts and private fixture storage. Captured
requests may contain bearer capabilities even if they contain no nsec.

## 3. Execution method and evidence

For every test, first perform an authorized control operation. Then change one
boundary condition at a time. Preserve the request shape, status, relevant
redacted log correlation IDs and before/after state. A 403 alone is insufficient:
verify there was no publication, debit, disclosure, credential activation or
background side effect. Retest in a fresh session to avoid cached success.

Use **Pass**, **Fail**, **Blocked**, or **Not applicable**. Not applicable requires
a documented reason and proof the feature is disabled or absent. No result is
inferred from a unit test alone. Use automated regression tests to support, not
replace, the deployed exercise.

## 4. Mandatory scenarios

### RT-01 — Isolation between users

As Alice, obtain valid references for a record, attachment, receipt, payment
status, pagination token and record presentation. Attempt those requests as Bob
and unauthenticated. Swap path, query and body identifiers separately. Replay a
cursor under another wallet, relay or folder and after expiry. Log out and sign
in as another user on the same device; test browser back and shared caching.

**Pass:** no other user's data or actionable capability is returned, cached or
rendered. Ownership is checked server-side, including attachment URLs and status
endpoints. Internal Acorn records remain inaccessible by guessed labels or IDs.

### RT-02 — Sign-in, recovery and custody disclosure

Test enabled Google/email/NFC sign-in paths and legitimate recovery. Attempt
account linking using a matching email without established account control,
wrong realm/client tokens, expired sessions, replayed recovery disclosure, CSRF,
unapproved callback destinations and login after revocation. Verify issuer/subject
mapping is stable and a fresh disclosure check cannot reveal another Acorn.
Exercise configured PIN bypass separately from mandatory PIN paths.

**Pass:** authentication reaches the intended existing account only. Recovery
requires its documented fresh authorization. No recovery material appears in
URLs, logs, analytics, browser caches or unauthorized responses. Record any
relying-party session that deliberately survives identity-provider logout and
verify its documented revocation/expiry policy.

### RT-03 — POS least privilege and browser binding

Activate a terminal, then try its credentials against wallet send, preference,
recovery and arbitrary record endpoints. Copy a session to another test browser;
try the activation code twice, stale challenges, missing device proof and altered
challenge contents. Revoke the terminal while a request is active. Test all
legitimately enabled NFC and record functions as well as receiving.

**Pass:** a terminal cannot spend the merchant's funds or disclose merchant keys.
Cardholder actions require their separate scoped authorization; POS activation
alone is insufficient. Replays and unsupported capabilities fail. Browser binding
provides the documented protection, without claiming it defeats same-origin
script compromise. Revoked terminals cannot start new authorized operations.

### RT-04 — Card pairing, possession, PINs and revocation

Pair a card through the wallet approval flow. Attempt to substitute the wallet,
terminal, issuer or enrollment choice between approval and writing. Cancel,
expire and replay the pairing. Present a copied test credential. Exercise incorrect
PINs up to the configured limit, attempts from multiple terminals and restart
persistence. Check card revocation on the issuer and through another home.

**Pass:** pairing binds the approved wallet and capabilities. Login enrollment is
explicit; PIN requirements cannot be downgraded by a caller. Attempt limits apply
server-side across terminals. A copied bearer credential may exercise explicitly
allowed no-PIN operations—document this expected risk rather than declaring clone
resistance. Revocation prevents new actions by both copies, including cached
foreign-home requests. Define and test what happens to already-authorized work.

### RT-05 — Cross-home request integrity

Run valid A-to-B and B-to-A payment and record flows. Modify amount, unit,
recipient, requested category, callback, request ID and expiry independently.
Try incorrect issuer keys, changed domain/key bindings, signatures from another
home, duplicate requests and delayed replies. Test the configured open federation
policy; if an allowlist is supported/enabled, test rejection outside it separately.

**Pass:** signatures cover the security-relevant instruction, its destination and
freshness. Card issuer pins are enforced. A valid foreign signature is not blanket
authority over a wallet. Replay cannot cause a second mutation. Returned results
are bound to the initiating request and validated before being shown as success.

### RT-06 — Payment retries and crash recovery

Run cash invoice, direct ecash and Clear payments, including NFC/POS and
cross-home paths enabled for release. Test double taps, simultaneous submissions,
replayed request IDs, insufficient funds, invalid amounts, mismatched mint/unit,
fee changes, mint unavailability and a locked test Lightning backend.

For each applicable durable payment path, inject failure at these boundaries:

| Interruption point | Recovery evidence required |
| --- | --- |
| Before durable intent | No unauthorized external mutation |
| After intent, before delivery | Retry uses the recorded operation safely |
| After remote acceptance, before local acknowledgement | Outcome is reconciled; no blind second payment |
| After credit, before history/status update | No duplicate credit; history and UI converge |
| During lease renewal or receipt persistence | Lease ownership remains safe; no lost recovery checkpoint |

Use both controlled graceful restarts and an authorized abrupt process kill.
Allow background recovery to finish before retrying an uncertain operation.

**Pass:** one intended payment produces at most one spend and one corresponding
credit. Reconcile fees and both wallets' Acorn history against mint/protocol state.
Uncertainty remains explicit and recoverable. “Detected” never becomes “Received”
without the required confirmation. No unresolved balance discrepancy is accepted.

### RT-07 — Record consent, sharing and discovery

Exercise QR and NFC sharing/presentation locally and across homes. Substitute a
category, recipient or capability; request unrelated categories, expire a share,
replay acceptance, and stop a request after it has been accepted. Try simultaneous
same-label imports. Update a record between discovery and retrieval. Traverse
all fixture pages and folders, including parent records and empty filtered pages.

**Pass:** only the intended authorized records are disclosed. Recipient binding
and expiry are enforced; existing labels are not silently overwritten. Any
cross-client collision limitation is reproduced and explicitly assessed. No
internal records leak. Ordinary fixtures remain discoverable without loss across
pagination; unavailable reads do not masquerade as deletion. Stopping a share
must not claim it erases copies already legitimately received.

### RT-08 — Attachments, scanners and untrusted destinations

In isolated fixtures, test script-like labels and text, hostile HTML/SVG, misleading
MIME types, malformed PDFs, oversized files, long QR payloads and malformed request
codes. Exercise storage/discovery/callback URLs with disallowed schemes,
redirects and controlled private-network addresses; use test endpoints rather
than real cloud metadata services. Test DNS changes through a controlled resolver.

**Pass:** untrusted input cannot execute in the app's origin, disclose credentials,
escape authorization through a preview route, bypass configured network policy
or trigger uncontrolled resource consumption. Blob digests are checked where
required; failures are explicit. Unsafe redirects are not silently followed.

### RT-09 — Verification and user interpretation

Present an unchanged file with a valid anchor, then change the file, signer,
statement or profile independently. Include a valid signer whose statement does
not grant the requested entitlement, and a lookalike display name. Interrupt
verification infrastructure and inspect the POS result.

**Pass:** verification binds to the correct file and signed statement. Profile
names are presentation metadata, not proof of qualification. Invalid/unavailable
evidence cannot retain a previous success indicator. Ask a reviewer to explain
what the green check means; it must not imply truth or universal entitlement.
Similarly, review payment-detection wording and distinguish it from settlement.

### RT-10 — Deployment, observability and recovery

Inspect container exposure, trusted-proxy headers, secure cookie scope, origin
checks, service-role database privileges and diagnostics. Search generated test
logs and error responses for fixture secrets. Test Redis loss and PostgreSQL
unavailability. Restore a backup in an isolated network with workers initially
stopped; reconcile pending work before enabling external delivery.

**Pass:** database and service interfaces have only intended access; failures do
not reset authorizations or silently switch databases. Restore does not blindly
replay payments or reactivate revoked credentials. Demonstrate the procedure for
reapplying revocations newer than a backup; if unavailable, keep external access
closed and record the gap. Recovery journals are not treated as disposable caches.

### RT-11 — Custodial power and user agency

Document what a runtime/key compromise or malicious custodian could do. Check
privileged access paths and backup protection without using production keys.
Recover a disposable Acorn in an independent compatible client using its disclosed
material and required infrastructure; compare identity and selected records.
Review public claims about migration, departure and optional helper indexes.

**Pass:** operator power is honestly disclosed, access is appropriately restricted
and the supported recovery procedure is evidenced. Planned Go Independent or key
rotation tooling is not represented as complete. Do not destroy custody material
as part of an unimplemented departure workflow. A helper index does not become a
new prerequisite for independent access.

## 5. Findings and release gates

Use these local impact categories; they are triage criteria, not a certification:

| Severity | Examples | Release treatment |
| --- | --- | --- |
| Critical | User-key extraction, broad unauthorized spending, cross-home compromise with uncontrolled impact | Block release; contain, fix and independently retest |
| High | Cross-user private-record access, capability escalation, duplicate payment, revocation bypass | Block affected feature; fix and independently retest |
| Medium | Bounded disruption, misleading verification, limited metadata leakage | Assess actual impact; named mitigation, deadline and release-owner acceptance required |
| Low | Minor hardening or clarity issue without demonstrated material boundary failure | Track with owner and deadline |

Classify by demonstrated consequences; examples do not cap severity. A UI issue
that causes unauthorized payment or disclosure can be high or critical. No
critical/high waiver through wording alone. Disabling a feature is a mitigation
only after its server-side paths and background workers are confirmed disabled.

For each finding record: ID; scenario; revision/configuration; prerequisites;
expected/observed behavior; minimal reproduction; redacted evidence; affected
identities and capabilities; impact/severity rationale; containment; fix commit;
regression test; retest reviewer/date/result; and residual risk. Avoid putting
sensitive evidence in the public repository.

## 6. Closure and release record

- Account for every scenario, including blocked tests and disabled features.
- Reconcile all test funds and pending work. Revoke test cards, terminals and
  tokens; remove or isolate fixtures and protect retained evidence.
- Retest fixes and neighboring flows against the final release candidate. A
  dependency, configuration or schema change after testing requires impact review.
- Record scope, versions, results, open findings, accepted lower risks, backup
  drill evidence and operational monitoring/rollback arrangements.
- Obtain maintainer, independent-reviewer and release-owner sign-off. Publish a
  sanitized summary and truthful limitations, not an unsupported “secure” badge.

Until this record exists, the exercise remains **planned**, regardless of how
many automated tests pass. Use [SECURITY.md](https://github.com/trbouma/oakgate/blob/main/SECURITY.md)
for private reporting and [the backup plan](036-backup-and-recovery-plan.md) for
restoration procedures. Preserve the [Mainstay principles](010-mainstay-principles.md)
throughout remediation.
