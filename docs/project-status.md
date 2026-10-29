# Project status

OakGate is in active development. This page distinguishes implemented features,
operator-reported results on the existing deployment, and checks still required
for a new home instance. Deployment reports are not a certification or a guarantee
that every integration and failure mode has been tested.

## Implementation and verification status

| Area | Current state |
| --- | --- |
| Wallet app | Funds, Records, Receipts and Preferences; Everyday Funds and Community Credits with friendly units and local-currency display |
| Local development | Python 3.12, Poetry, automatic reload and automated tests; containers built on the deployment host |
| Sign-in | Keycloak with Google, email registration and recovery, and enrolled NFC card authentication; operator reported successful login flows and logout |
| Acorn custody | Create/connect, encrypted custody storage and balance readback; operator confirmed an existing Acorn's displayed balance matched |
| Payments | Cash and Clear sending/receiving, direct ecash, Lightning and recovery journals implemented; operator reported successful external-wallet Lightning payments and Clear requests with history on both sides |
| Zaps | Receipt handling implemented; independent end-to-end verification remains a deployment check rather than inferred from a successful ordinary Lightning payment |
| Records | Creation, attachment preview, update, deletion, sharing and presentation through Acorn; operator reported attachment display and accepted sharing working |
| POS | Browser-bound activation, receiving, NFC issuance, balance lookup and card payment flows implemented; operator reported activation, card issuance and balance lookup working |
| POS record presentation | Seven categories (`whoami`, `myinfo`, `emergency`, `health`, `benefits`, `member`, `pass`) with case-insensitive slash descendants, selection and PDF/OpenETR previews; local NFC reported working; remote flows have automated coverage |
| Cross-home POS | Signed issuer-pinned NFC debit, balance lookup and record presentation implemented with two-home automated tests; live two-home acceptance remains required |
| Presentation notices | Emergency contact-wallet notifications and holder presentation receipts implemented with duplicate protection and local tests; live delivery verification pending |
| Receipts | Compact newest-first received-message list, expandable details, compose hidden; reads Acorn messages, including available presentation receipts |
| Application storage | PostgreSQL runtime and Alembic migration tooling implemented; operator reported verified data migration and healthy application startup |
| Keycloak storage | Separate PostgreSQL database and role; operator reported import verification preserving realm user IDs and identity links, then healthy startup and working sign-in |
| Deployment | Environment-based storage paths, health checks and refresh scripts; operator reported healthy services on SSD-backed storage |
| Documentation | MkDocs site and illustrated User Experiences; new changes still require publication |

**Everyday Funds** is the user-facing name for Cash; **Community Credits** is the
user-facing name for Clear balances. Technical names and some payment controls
retain Cash/Clear. See [user-facing language](product-direction.md#user-facing-language).

## Incomplete or requiring further verification

- Recovery disclosure is implemented. Independent Acorn restoration and a complete
  disaster-recovery rehearsal still need verification; a backup plan is not a
  demonstrated restore.
- The complete **Go Independent** departure and deletion workflow remains planned.
  Displaying recovery information does not end custody or prove erasure.
- Cross-home NFC operations and wallet QR presentations require live acceptance with independent homes,
  devices, TLS/proxies, mints and relays. Automated coverage is not a live
  interoperability result. See [the checklist](039-cross-home-pos.md#acceptance-checks-before-relying-on-a-deployment).
- NWC-based cross-home coordination is planned. The implemented transport is signed
  HTTPS between app servers; stabilize it first. See [the roadmap](039-cross-home-pos.md#transport-roadmap-stabilize-https-then-evaluate-nwc).
- Custody-key rotation tooling is planned, not implemented. It must re-encrypt all
  affected state, preserve payment recovery and verify rollback/restoration before
  switching keys. See [the rotation roadmap](product-direction.md#custody-key-rotation-roadmap).
- Home/satellite deployment is a documented architecture, not deployed satellite
  support.
- Presentation receipts and emergency notifications are best-effort messages,
  not a complete audit archive or guaranteed emergency alert service.
- Municipal credit programs in User Experiences are illustrative. Their funding,
  participation and reimbursement processes require separate operational setup.

## Acceptance checks for every new home

1. Plan the identity, database, storage, domain and backup choices using
   [Planning for OakGate](planning-for-oakgate.md). Confirm the configured mounts
   and service health before enabling use.
2. Configure the Keycloak realm and application client, then test the enabled
   sign-in, registration, recovery and logout flows. Use the
   [sign-in guide](005-keycloak-sign-in.md); an existing home's successful test
   does not configure another home.
3. Create or connect a test Acorn and verify balances and friendly units against
   its relay and mints. Test small incoming and outgoing payments, receipts and
   transaction history, including recovery from an uncertain outcome without
   resending blindly.
4. If enabled, test POS activation and revocation, NFC issuance and payments,
   QR/NFC record presentation, expiry and message delivery to the correct wallets.
   Check supported devices and issuer/relay boundaries.
5. Protect and back up configuration and secrets separately from public docs.
   Rehearse restoration before relying on the service for production custody.

These checks remain necessary after relevant configuration or infrastructure
changes. See the [Mainstay principles review](010-mainstay-principles.md#review-findings-and-follow-up-work)
for architectural boundaries and outstanding acceptance requirements.

## Deferred record scaling

Record management is adequate for the anticipated near-term use of dozens of
records. Remaining POS discovery, folder indexing and larger-wallet performance
work is parked in the [Record management roadmap](042-record-management-roadmap.md),
with triggers and acceptance checks for revisiting it.
