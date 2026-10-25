# PostgreSQL backup and recovery plan

## Scope and implementation status

This plan covers OakGate after both the application and Keycloak have moved to
separate PostgreSQL databases. PostgreSQL is authoritative; the old SQLite and H2
copies are migration snapshots, not ongoing backups. The Keycloak work directory
is not its active database.

This is an operational plan, not an installed backup service. Scheduling,
encrypted off-host storage, alerting and a full restore rehearsal remain to be
implemented. The operator owns these tasks and records successful runs and drills.
No secret values belong in this document, Git, issue reports or backup logs.

## Recovery targets and retention

Proposed initial targets, subject to a measured restore drill:

| Item | Proposed policy |
| --- | --- |
| Database backups | Hourly logical dumps of both databases; an additional coordinated set before migrations |
| Configuration | Protected versioned backup after every configuration, credential or deployment change |
| Retention | Keep hourly sets for 48 hours, daily sets for 30 days, and monthly sets for 6 months |
| Recovery point target | At most one hour of database changes lost, only while hourly off-host backups succeed |
| Recovery time target | Restore service within four hours; not a guarantee until rehearsed |
| Restore drills | Monthly and after changes to storage, database major version, custody keys or authentication |

One hour of lost payment journal data can be unacceptable even if the service
returns quickly. A backup cannot guarantee recovery of payments whose durable
blinding secrets or checkpoints were created after it. Before depending on the
service for higher-volume use, introduce PostgreSQL physical base backups plus
continuous WAL archiving for point-in-time recovery, and measure archive lag.
WAL archiving is not currently established by this plan. Retention must preserve
all base backups and WAL needed for each advertised recovery point.

Maintain three copies across two independent storage systems, with one off-site.
A second directory on Lexar is not an independent copy. Another drive attached
to Beelink can be a local backup tier, but does not cover host compromise, theft
or fire. Prefer an off-site repository with deletion protection and credentials
that cannot erase its entire history from the application host.

## Backup inventory

| Component | Required material |
| --- | --- |
| OakGate database | All tables, sequences, schema revisions, custody envelopes, payment journals, inboxes, POS and NFC state, preferences and revocations |
| Keycloak database | Users and their IDs, credentials, federated identity links, clients, flows, signing material and persisted identity state |
| PostgreSQL globals | Roles, memberships, ownership and grants needed to restore both databases; treat any password verifiers as secrets |
| Operator configuration | Encrypted copy of the actual deployment `.env`, selected Compose files, overrides and storage paths |
| Software | Git revision, lockfile, image digests or recoverable image artifacts, database major version and the matching custom Keycloak NFC provider |
| Network and administration | Nginx configuration, DNS/TLS recovery procedure and independent access to email, Google and backup-provider administration |
| Acorn infrastructure | Separate consistent backups for operated Spurline relays, Grove metadata and blobs, and mint services |

Keep the exact `OAKGATE_CUSTODY_KEY` needed by each retained database generation.
Preserve `OAKGATE_SERVICE_NSEC`, `OAKGATE_POS_COOKIE_KEY`, OIDC/NFC client secrets,
NFC backchannel credentials, database credentials and other required settings in
a protected configuration backup. Use setting names in manifests, never values.
Do not rotate custody keys by merely editing configuration; historical backups
still need their matching key material and a supported rotation procedure.

Store configuration and decryption keys separately from database archives, with
restricted operator access. Keep the backup-decryption recovery key outside
Beelink and outside the backup repository it unlocks. Test access from a clean
machine without relying on the failed OakGate login service.

Redis sessions are deliberately excluded: restore with fresh sessions and require
sign-in again. Live PostgreSQL directory copies, Keycloak realm exports, and
historical SQLite/H2 files are not substitutes for current PostgreSQL backups.
Mint and LND state need their own supported recovery procedures; never roll them
back casually to match an OakGate snapshot.

## Backup procedure to implement

1. Verify the intended deployment, active database names, storage mount and
   off-host destination. Use explicit database names and a protected credential
   mechanism, not passwords in command arguments. Do not dump `.env` or rendered
   Compose configuration into job logs.
2. Use PostgreSQL-native logical backups, such as custom-format `pg_dump`, for
   each database, plus protected role/global configuration recovery material.
   Use tools compatible with the server version. Preserve ownership and grants.
   Each dump has its own consistent database snapshot; two sequential dumps are
   not a single atomic snapshot across databases.
3. For a coordinated pre-migration set, pause public writes, allow in-flight
   operations to finish, and gracefully stop app, POS and Keycloak by service
   name. Confirm all other writers and operator jobs are stopped. Keep PostgreSQL
   running for the dumps. Record the outage and restart only after backup checks.
   Routine online dumps must record the snapshot time range and require identity
   reconciliation during restore; they do not promise cross-database consistency.
4. Write to a private staging area with restrictive permissions and adequate
   space. Encrypt archives before transfer. Handle pipeline failures explicitly,
   retain failed-run diagnostics without secrets, and never mark a partial set
   successful or prune good backups because a replacement attempt started.
5. Create a protected manifest with UTC start/end times, database names, schema
   revisions, software versions, archive sizes and checksums, and a reference to
   the separately protected configuration version. Include both databases and
   globals in the set. Checksums detect corruption, not application correctness.
6. Upload to independent off-host storage, verify transfer integrity and archive
   readability, then mark the set complete. A readable archive is not a tested
   restore. Expire staging plaintext promptly under the chosen encryption tool's
   procedure; SSD deletion must not be represented as guaranteed erasure.
7. Apply retention only to completed backup generations. Protect required key
   generations and any physical-backup/WAL dependencies before pruning.

The scheduled job must prevent overlapping runs, have bounded execution time,
and report failure, missing artifacts, insufficient space or stale off-host
copies. Proposed alert threshold: no complete off-host set for two hours.
An independent monitor must detect a dead host or scheduler; a job cannot reliably
report its own absence. Route alerts outside OakGate and test their delivery.

## Restore and payment safety

1. Declare an incident and stop production writers before any actual cutover.
   Preserve the damaged/current state for investigation. Select a complete backup
   set and its matching secret/configuration generation; record the intended
   recovery time and any known missing changes.
2. Rehearse in a separate PostgreSQL instance with isolated networking. Restore
   roles, ownership, both databases and grants using compatible software. Never
   run a test restore against the live database or start a second live worker.
3. Block outbound access to live mints, relays, email and identity providers for
   the initial drill. Set `OAKGATE_PAYMENTS_ENABLED=false`, but do not treat that
   flag as a universal switch for every inbox, POS or authentication side effect.
   Keep app/POS/background workers stopped until their startup effects have been
   accounted for. Network isolation is the additional safety boundary.
4. Verify schema revisions and runtime permissions, database integrity, user IDs,
   realm/client configuration and the issuer/subject-to-Acorn mapping. Never map
   custody by email or create replacement users to repair a mismatch. Preserve
   the original issuer and service public identity; use controlled routing for
   any later login drill. Check decryption without exposing keys or user secrets
   in test output.
5. Reconcile identity changes, password resets, card/POS revocations, PIN lockouts
   and account departures after the recovery point. An older backup must not
   silently reactivate revoked credentials or restore custody for departed users.
   If current revocation status cannot be established, keep affected capabilities
   disabled pending owner verification.
6. Review incoming and outgoing payment recovery states against authoritative
   mint and relay state before enabling settlement. Preserve prepared outputs,
   idempotency references and uncertainty holds. Do not delete journals, clear
   uncertain payments, reissue payments or generate replacement blinding material
   merely to make the restored service start. Escalate missing recovery material
   for reconciliation rather than guessing whether a payment completed.
7. For production recovery, fence the old deployment, start fresh Redis sessions,
   and account for restored Keycloak sessions/tokens with a supported invalidation
   procedure. Verify Google, email/recovery and NFC flows, existing Acorn identity,
   handles, records and balances. Enable workers and POS deliberately only after
   reconciliation; then perform a small controlled payment and check both sides.
8. Record recovery duration, missing data, checks performed and remaining issues.
   A drill passes only after application-level checks, not just database import.

Restoring one stale database independently can break identity associations or
resurrect old payment state. A Keycloak problem does not authorize rolling back
OakGate's payment database. Plan the smallest recovery and reconcile changes.

## Implementation checklist

- [ ] Select encrypted off-site storage and independent recovery-key custody.
- [ ] Implement paired database/global backups, private staging and manifests.
- [ ] Add hourly scheduling, locking, retention and independent failure alerts.
- [ ] Capture configuration changes without logging or committing secrets.
- [ ] Rehearse an isolated restore and record measured recovery targets.
- [ ] Define separate relay, blob, mint and Lightning-node backup responsibilities.
- [ ] Implement and test WAL-based recovery if the one-hour loss window is too large.
- [ ] Publish the retention policy before promising account deletion or Go Independent.

See [identity and storage](008-identity-storage-backups.md),
[PostgreSQL cutover](033-postgresql-cutover.md), and
[Keycloak PostgreSQL migration](034-keycloak-postgresql.md).
