# SQLite to PostgreSQL: controlled import and cutover

## Status and safety boundary

The offline import and verification tools are implemented. They do not deploy,
start workers, change Keycloak, or automatically switch the app. SQLite remains
the default until an operator completes this procedure. Rehearse on isolated
PostgreSQL 17 staging before using the production database. Development tests
used native PostgreSQL 14.20; no local Docker container was started.

The importer copies **all 28 application tables**, including opaque encrypted
custody material, identities, preferences, cards/PIN state, deduplication keys,
leases and payment recovery records. It does not decrypt user secrets or invoke
Acorn, a mint or a relay. It does not reset holds, expire leases, clear failures,
mark payments complete or resend anything. Preserve the existing custody key,
service identity and Keycloak issuer/subject configuration separately.

All SQLite and PostgreSQL writers must be stopped, including other deployments,
manual workers and tools sharing these databases. A `--writers-stopped` flag is
an operator acknowledgement, not proof that an external payment has finished.
Suspend user/POS traffic and let in-flight operations finish before stopping.
If shutdown was forced or a payment is uncertain, investigate its durable recovery
state; do not clear the hold or repeat the payment to facilitate migration.

## How the import works

1. Validate the adopted SQLite baseline and all values. Reject missing tables,
   wrong revisions, null primary keys, invalid types and non-finite timestamps.
2. Hold SQLite `BEGIN IMMEDIATE`; acquire the PostgreSQL application advisory lock
   and table write locks. Require a migrated target with **zero application rows**.
3. Create an exclusive mode-0600 SQLite-native backup, including committed WAL
   contents, validate it and compare its contents with the locked source.
4. Write and fsync a mode-0600 `custody.sqlite3.postgres-cutover` marker beside the
   source. This version of OakGate refuses SQLite startup or new connections while
   the marker exists. Existing older binaries do not know about this protection.
5. Insert and compare every table in one PostgreSQL transaction. Counts and SHA-256
   fingerprints include every column and encrypted byte; row ordering is irrelevant.
   TEXT, BIGINT, DOUBLE PRECISION and BYTEA are validated explicitly. The audit
   identity sequence is restarted past the largest imported ID transactionally.
6. Commit once. Leave SQLite and its marker unchanged. Run a separate verification
   before allowing any PostgreSQL application writes.

The marker is retained even if import fails. A lost commit acknowledgement is an
unknown outcome: **verify, do not reimport or restart SQLite**. Target rows are
never overwritten. There is no automatic data rollback. Fingerprints are integrity
checks, not an authentication mechanism; protect reports and backups.

## Preparation on Beelink

Use the OakGate repository. Deploy/build this code while keeping SQLite active
first, and verify normal behavior. Keep the currently working storage paths and
secrets; no tracked Compose edits or data-directory moves are needed.

```sh
mountpoint /mnt/lexar
docker compose config --quiet
docker compose build app
```

Confirm the source is `/app/data/custody.sqlite3` inside app and the host bind
mount points to the current OakGate data. Confirm SQLite baseline adoption:

```sh
docker compose run --rm --no-deps --entrypoint python app \
  -m app.db_migrations check --database /app/data/custody.sqlite3
```

Require `0001_sqlite_baseline` and no missing objects. If unadopted, follow the
[baseline procedure](031-sqlite-alembic-baseline.md) first. Preserve protected
backups of `.env`, custody/service keys, Keycloak data and the current SQLite data.
A copy on the same SSD is not a disaster-recovery backup.

### One-time PostgreSQL roles

Use the already running private PostgreSQL service. The following assumes the
existing default database `oakgate` and administrator `oakgate_admin`; substitute
configured names if different. Do not recreate existing roles or change passwords
without reviewing their use. In staging, use a separate disposable database.

```sh
docker compose exec postgres psql -U oakgate_admin -d oakgate
```

In the interactive PostgreSQL console, for new roles:

```sql
CREATE ROLE oakgate_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE oakgate_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
\password oakgate_migrator
\password oakgate_runtime
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE oakgate TO oakgate_migrator, oakgate_runtime;
GRANT USAGE, CREATE ON SCHEMA public TO oakgate_migrator;
GRANT USAGE ON SCHEMA public TO oakgate_runtime;
\q
```

Use independent generated passwords, retained in protected storage. The migrator
owns the tables it creates; runtime must not inherit its role. Neither is the
container bootstrap administrator. Passwords in URLs need percent encoding;
hex-generated passwords avoid URL punctuation.

### Begin the maintenance window

Suspend account/POS use and stop app and POS, plus every other writer. Keycloak,
Redis and PostgreSQL remain running. Do not rebuild/recreate those services.

```sh
docker compose stop pos app
docker compose ps --all app pos
```

Wait for clean shutdown and review any interrupted work. Keep traffic suspended.
In `.env`, set the restricted runtime URL and persist the Compose selection so
future refreshes use the same database:

```dotenv
OAKGATE_DATABASE_URL=postgresql+psycopg://oakgate_runtime:REPLACE_WITH_RUNTIME_PASSWORD@postgres:5432/oakgate
COMPOSE_FILE=compose.yaml:compose.nfc.yaml:compose.postgres.yaml
```

Keep your other existing overrides. Omit `compose.nfc.yaml` only if NFC Keycloak
is not used. Keep `OAKGATE_DATA_DIR` pointing at the original OakGate directory:
it retains the source, backup and safety marker. Do not run refresh/start yet.

Supply the migration URL only to the maintenance shell, without echoing it or
putting it in shell history. On Beelink's Bash:

```sh
read -r -s -p 'Migration database URL: ' OAKGATE_MIGRATION_DATABASE_URL
printf '\n'
export OAKGATE_MIGRATION_DATABASE_URL
docker compose config --quiet
```

Enter `postgresql+psycopg://oakgate_migrator:PASSWORD@postgres:5432/oakgate`, using
the migration password, not the runtime password. Do not paste the URL into chat.

### Initialize the empty target and grant runtime access

For a new empty target, run:

```sh
docker compose run --rm --no-deps -e OAKGATE_MIGRATION_DATABASE_URL \
  --entrypoint python app -m app.postgres_migrations init
```

If already initialized, use `check` instead. Do not drop tables to get around a
refusal. A target with unexpected data requires investigation.

Back in the administrator's interactive PostgreSQL console, grant application
DML, revision read access and audit-sequence usage:

```sql
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO oakgate_runtime;', tablename)
FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'
\gexec
GRANT SELECT ON TABLE public.alembic_version TO oakgate_runtime;
GRANT USAGE ON SEQUENCE public.pos_audit_id_seq TO oakgate_runtime;
\q
```

Check runtime schema/permissions without starting the app or workers:

```sh
docker compose run --rm --no-deps --entrypoint python app \
  -m app.postgres_migrations check-runtime
```

### Import, then independently verify

Choose a fresh backup filename; the tool refuses existing files. Keep writers
stopped throughout both commands. These commands run maintenance Python only:

```sh
docker compose run --rm --no-deps -e OAKGATE_MIGRATION_DATABASE_URL \
  --entrypoint python app -m app.postgres_import import \
  --database /app/data/custody.sqlite3 \
  --backup /app/data/custody.before-postgres.sqlite3 --writers-stopped

docker compose run --rm --no-deps -e OAKGATE_MIGRATION_DATABASE_URL \
  --entrypoint python app -m app.postgres_import verify \
  --database /app/data/custody.sqlite3 --writers-stopped
```

Require `imported`, then `verified`, with matching counts and fingerprints for all
28 tables. Retain the reports privately. If either fails, **do not continue**.
Verification is meaningful before app startup: the app may update maintenance
state immediately when started, even without a user payment.

### Cut over once

After successful verification, recheck runtime permissions, clear the maintenance
credential and start only app:

```sh
docker compose run --rm --no-deps --entrypoint python app \
  -m app.postgres_migrations check-runtime
unset OAKGATE_MIGRATION_DATABASE_URL
docker compose up -d --no-deps --force-recreate --wait --wait-timeout 120 app
docker compose ps app
docker compose logs --since=2m --tail=80 app
```

Confirm account continuity, handles/language/currency preferences, expected Cash
and Clear balances, cards and PIN policies, records, and unchanged payment review
holds. Use a small new payment to check receipt/recovery behavior; never repeat
an uncertain old payment. Then start POS if enabled and restore traffic:

```sh
docker compose up -d --no-deps --wait --wait-timeout 120 pos
```

Keep the marker, SQLite source and backup. Normal refresh scripts honor
`COMPOSE_FILE` from `.env`; omitting the PostgreSQL override would now fail closed
on the fenced SQLite database. Do not switch the mount to an old unfenced copy.
Add PostgreSQL-native backups and a tested restore, including roles and all
operator keys, before relying on the new database operationally.

## Failure and rollback rules

- Before the marker exists, import has not copied application rows. Keep writers
  stopped, inspect errors, and verify which configuration/database is authoritative.
- After the marker exists, assume a possible committed import. Run `verify` against
  the intended target. A matching result can resolve a lost commit acknowledgement.
- If import definitely rolled back and the target is still empty, retry/revert is
  an explicit maintenance decision: retain backups, prove no PostgreSQL app or
  external operation ran, and only then review removal of the marker. The tool
  deliberately provides no automatic unfence/reset option.
- Once the PostgreSQL app has started or accepted writes, do not remove the marker,
  restore the old SQLite copy or start both versions. Reconcile state and restore
  forward from a suitable PostgreSQL backup if necessary. An old snapshot can lose
  spent-proof, lease, nonce, revocation and idempotency information.
- The marker only protects this code version and the same source path. It is not
  distributed fencing against an old binary, copied database or manual SQL. The
  stopped-writer procedure is essential.

## Tests

`tests/test_postgres_import.py` exercises all-table exact copy, WAL-aware backups,
sequence continuation, invalid values, schema adoption, a nonempty destination,
transaction rollback and commit-acknowledgement loss. It also checks refusal to
reopen fenced SQLite through an already constructed store. Run with the disposable
administrator test URL described in [storage compatibility](032-postgresql-storage.md).
No production wallet, mint, relay or payment is used.
