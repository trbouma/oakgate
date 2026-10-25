# PostgreSQL storage compatibility

## Deployment status

OakGate now has a PostgreSQL storage adapter and a separate Alembic schema for
all 28 application tables. **SQLite remains the default and the deployed source
of truth. This release does not import data or switch a live installation.**
Keycloak continues to use its existing database; Redis continues to hold sessions.

Do not enable the PostgreSQL override against an empty database for a live app.
It would have no users' wallet associations, card permissions or payment-recovery
state. Use the [controlled import and cutover procedure](033-postgresql-cutover.md); it is explicit and never runs on application startup.

## Configuration and credentials

- Leave `OAKGATE_DATABASE_URL` blank for SQLite. Existing `OAKGATE_DATA_DIR`,
  custody encryption keys and mounts remain unchanged.
- PostgreSQL uses an explicit `postgresql+psycopg://USER:PASSWORD@postgres:5432/DATABASE`
  URL. Percent-encode reserved characters in URL credentials.
- The base Compose file deliberately does not pass this URL to app. The explicit
  `compose.postgres.yaml` override connects app to the private database network
  and supplies the runtime URL. Keep `compose.nfc.yaml` too where applicable.
- `OAKGATE_MIGRATION_DATABASE_URL` is a temporary maintenance credential for the
  migration command, not a normal app setting. Never give the app the bootstrap
  administrator password or a schema-owning migration role.
- A configured but unreachable, uninitialized or incompatible PostgreSQL target
  fails startup. There is no silent fallback to SQLite.

Use three separate roles: the existing bootstrap administrator, a controlled
schema-owning migration role, and a runtime login. The runtime login must have no
superuser, role creation, database creation, replication, bypass-RLS, schema CREATE
or table/sequence ownership rights (including inherited ownership).

For an **isolated staging database**, the administrator creates the migration and
runtime roles with independent passwords, makes the migration role the database
owner, revokes public CREATE on the public schema, and grants the migration role
USAGE/CREATE there. Supply passwords through a protected administration session,
not a committed SQL script or shell command containing the secret.

After schema initialization, grant the runtime role CONNECT to that database,
USAGE on schema public, SELECT/INSERT/UPDATE/DELETE on each application table,
SELECT on `alembic_version`, and USAGE on `pos_audit_id_seq`. Do not grant runtime
DDL privileges or membership in the migration role. Startup validates schema and
runtime privileges. Future migrations must deliberately grant any new objects.

## Explicit schema initialization

Only use these commands for a prepared, empty staging target at this stage.
The image must contain this release. Export `OAKGATE_MIGRATION_DATABASE_URL` from
a protected environment using the migration role and the staging database name.
The one-off command uses the private database network without starting workers:

```sh
docker compose -f compose.yaml -f compose.postgres.yaml run --rm --no-deps \
  -e OAKGATE_MIGRATION_DATABASE_URL --entrypoint python app \
  -m app.postgres_migrations init

docker compose -f compose.yaml -f compose.postgres.yaml run --rm --no-deps \
  -e OAKGATE_MIGRATION_DATABASE_URL --entrypoint python app \
  -m app.postgres_migrations check
unset OAKGATE_MIGRATION_DATABASE_URL
```

Compose also requires a nonblank runtime `OAKGATE_DATABASE_URL` to validate this
override, even though this maintenance command uses only the migration URL.
Supply the staging runtime URL for these commands. Do not put an administrative
URL in that field. Database must already be running; `--no-deps` does not start it.

`init` refuses a nonempty public schema and creates revision
`0001_postgres_schema` atomically. `check` checks the revision and schema; runtime
role enforcement happens when the application opens its store. Neither command
imports SQLite rows, decrypts custody data, contacts a mint, or starts a worker.
Downgrade is deliberately disabled. Initialization is not an upgrade command for
future revisions; future schema changes require a reviewed migration and validator.

The PostgreSQL history is separate from `0001_sqlite_baseline`. Never copy the
SQLite `alembic_version` row or use `stamp` to claim a PostgreSQL import succeeded.
`app/postgres_schema.py` is the frozen initial PostgreSQL definition: extend with
new revisions, rather than rewriting it to match a changed live database.

## Transaction and payment guarantees

The adapter uses parameter binding, pooled connections and READ COMMITTED
isolation. Every application write context acquires the same transaction-scoped
PostgreSQL advisory lock **before reading state used to decide a write**. This
conservatively preserves SQLite's serialized write decisions across processes:
lease claims, request deduplication, handle uniqueness, PIN failures and card
revocation continue to share one ordering. This is a compatibility step, not a
claim of unlimited concurrent writes or an optimization to per-wallet locks.

A waiting transaction reads committed state after acquiring the lock. The lock
is released on commit/rollback. Lock and pool waits are bounded to five seconds;
statements and idle transactions have 30-second bounds. Database operations are
not automatically retried. An uncertain commit remains uncertain, and payment
recovery must inspect durable state before repeating any external action.
Existing Acorn ownership, settlement, transaction-history and recovery boundaries
remain in place; this adapter performs no wallet cryptography or Nostr operations.

Encrypted blobs use BYTEA, integer fields BIGINT and timestamps DOUBLE PRECISION.
Primary keys are non-null in PostgreSQL; an importer must reject historical SQLite
rows with null keys. Audit IDs use an identity sequence which must be advanced
past imported IDs. All original unique/check constraints and partial indexes are
preserved. Application startup verifies the expected schema and performs no
PostgreSQL DDL. SQLite legacy bootstrap is centralized for compatibility and still
does not automatically adopt an Alembic revision.

See PostgreSQL's [transaction isolation](https://www.postgresql.org/docs/17/transaction-iso.html)
and [advisory locking](https://www.postgresql.org/docs/17/explicit-locking.html)
documentation for the underlying behavior.

## Verification and remaining cutover work

The default suite exercises SQLite. Opt-in tests use a real disposable PostgreSQL
database with fake mint/relay boundaries; they never pay an external invoice.
They cover concurrent claims, duplicate confirmations, expired leases, interrupted
minting/recovery, history and zap retries, NFC PIN lockout/revocation, schema/role
rejection, encrypted-byte preservation and a lost commit response with no retry.

Set `OAKGATE_TEST_POSTGRES_URL` to a restricted runtime role on a pre-migrated
disposable database ending in `_test`. The fixture **deletes its application rows**.
Optionally set `OAKGATE_TEST_POSTGRES_ADMIN_URL` to the same database for schema
rejection tests. Never use either variable for a production database.

```sh
poetry run pytest -q tests/test_postgres_storage.py
```

Development validation used native PostgreSQL 14.20 without a local Docker
container. The deployment image is PostgreSQL 17; repeat this suite in isolated
PostgreSQL 17 staging before production cutover.

The [import and cutover guide](033-postgresql-cutover.md) now supplies the offline
importer and verification procedure. Production PostgreSQL 17 rehearsal and live
cutover remain operator steps. Do not run SQLite and PostgreSQL settlement workers
at once. Once PostgreSQL accepts new payments, restarting an old SQLite snapshot
requires reconciliation, not simply reversing an environment variable.

See [SQLite baseline](031-sqlite-alembic-baseline.md),
[PostgreSQL foundation](030-postgresql-foundation.md) and
[backup responsibilities](008-identity-storage-backups.md).
