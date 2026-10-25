# SQLite Alembic baseline

## Scope and guarantees

SQLAlchemy and Alembic are now locked runtime dependencies. Revision
`0001_sqlite_baseline` establishes a frozen inventory of the existing SQLite
schema: **28 tables and five explicit indexes**, plus SQLite's implicit primary-key
and unique indexes. This stage does not switch to PostgreSQL, modify wallet
ownership, decrypt data, contact a relay/mint or send/retry a payment.

Application queries still use the existing SQLite stores. Their legacy bootstrap
DDL remains in place for compatibility during this first stage. No automatic
migration runs on app startup and no deployment script silently stamps a database.
The next persistence-layer stage must replace bootstrap DDL with controlled
migrations; merely adding Alembic does not make the application PostgreSQL-ready.

The operator command checks an **explicit existing file**, refuses a missing path
rather than creating an empty database, and requires an initialized `wallets`
table. It validates SQLite integrity and schema definitions before adopting them.
It compares columns, constraints, defaults and index predicates through conservative
SQL token comparison against the frozen definitions (ignoring formatting and
keyword case). Unexpected tables, views, triggers, altered definitions or unknown
revision identifiers stop adoption. Semantically equivalent but differently written
custom schema may also require manual review; do not bypass the check.

## What adoption changes

Existing application rows are left untouched. In particular, adoption does not
reset lease fields, mark an uncertain payment safe, change history flags, generate
issuer keys or clear PIN failures. Missing known tables can occur because some
features initialize lazily. The check lists them; adoption creates only those
missing tables/indexes, then verifies the complete schema and records the baseline
in `alembic_version`. Review the list before proceeding: the tool cannot distinguish
an unused feature from an accidentally removed unversioned table.

Existing tables missing historical columns are **rejected**, not automatically
repaired. Investigate with the matching previous application version; do not stamp
an older schema as current. A database already at the baseline must remain complete;
missing objects on a versioned database are treated as drift.

The upgrade acquires `BEGIN IMMEDIATE`, validates again, takes a SQLite-native
backup (including committed WAL contents), then applies DDL and the Alembic revision
in the same transaction. Failure rolls back DDL and the revision. The backup is
created exclusively with mode 0600 and cannot overwrite another backup or the source.
The source is not opened with immutable mode, and live WAL files are never discarded.

The write lock prevents overlapping writers during the operation; it is not a
substitute for shutting down the app and all other database writers. A worker
could have an external payment underway before the lock. There is deliberately
no automatic restart after a failed migration.

## Beelink maintenance procedure

Commit/push/pull this release and build its app image on Beelink first. Do not use
an app-only refresh in place of this explicit maintenance procedure. Retain the
existing `.env`, custody key, issuer identity and storage mount.

```sh
mountpoint /mnt/lexar
docker compose config --quiet
docker compose build app
```

The new image includes `app/migrations` through the existing app copy. No changes
to the PostgreSQL container or Keycloak provider are needed. A check can be run
against the mounted database without starting the app or its payment workers:

```sh
docker compose run --rm --no-deps --entrypoint python app \
  -m app.db_migrations check --database /app/data/custody.sqlite3
```

Read the reported revision and `missing_objects`. No values from user records
are printed. Before the upgrade, suspend new user/POS work and stop app cleanly;
wait for shutdown and investigate unfinished external activity. Stop any additional
process using this same database, including manually started workers. Keycloak,
Redis and PostgreSQL can remain running. POS does not mount the database, but
should not be used while its app API is offline.

```sh
docker compose stop app
docker compose ps --all app
```

Then run the upgrade with a **new backup filename** each time:

```sh
docker compose run --rm --no-deps --entrypoint python app \
  -m app.db_migrations upgrade \
  --database /app/data/custody.sqlite3 \
  --backup /app/data/custody.before-alembic-0001.sqlite3 \
  --writers-stopped
```

`--writers-stopped` is an operator acknowledgement, not automatic detection. Do not
run a normal app process in this one-off container. The command requires neither
an Acorn nor any custody key and never initializes a wallet service.

Only after success, verify and resume:

```sh
docker compose run --rm --no-deps --entrypoint python app \
  -m app.db_migrations check --database /app/data/custody.sqlite3
docker compose up -d --no-deps --wait --wait-timeout 120 app
```

Expect revision `0001_sqlite_baseline` and no missing objects. Check sign-in,
expected wallet balances and payment review state after resuming. Keep the backup
and copy it to protected independent storage; a backup alongside the database is
only a rollback copy, not protection against loss of the SSD. Keep the custody
key backup separately.

If check/upgrade fails, keep the app stopped for investigation. Do not delete the
version table, run `alembic stamp head`, drop constraints or retry a payment to
work around migration errors. Baseline downgrade is disabled: it must not drop
custody tables. An interrupted, uncommitted upgrade rolls back; if the commit
completed, the command is safely repeatable using another backup filename.
Restoring an older database after new payments have occurred needs reconciliation,
not an ordinary file replacement.

## Development and migration authoring

Install with `poetry install`. Against a disposable initialized development database:

```sh
poetry run python -m app.db_migrations check --database /absolute/path/custody.sqlite3
```

`alembic.ini` exposes revision history for development, but direct online/offline
migration commands are blocked by the environment unless the guarded runner has
provided a verified connection. There is no default URL and no PostgreSQL backend
in this runner. Future migrations must deliberately extend the validator/runner
for the new revision; it currently accepts only the baseline. Autogeneration and
ORM model metadata are not configured yet.

The frozen `app/migrations/baseline_0001.json` is historical evidence: do not regenerate
it from a live deployment or import application stores into a revision. New schema
changes require a new reviewed migration and an intentional update of the schema
compatibility tests. Existing SQLite text primary-key nullability and implicit
constraints are preserved rather than silently normalized by an ORM.

Tests cover current store DDL inventory, existing data preservation, lazy feature
tables, schema drift, unknown revisions, wrong paths, WAL-aware backups, duplicate
index failures and rollback after injected interruption. Sources for the transaction
approach are [Alembic's shared-connection recipe](https://alembic.sqlalchemy.org/en/latest/cookbook.html)
and [SQLAlchemy's SQLite transaction guidance](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html).

## Inventory

The baseline includes:

- `currency_rates` (table)
- `ecash_inboxes` (table)
- `incoming_payments` (table)
- `lightning_handles` (table)
- `nfc_card_pins` (table)
- `nfc_cards` (table)
- `nfc_issuer` (table)
- `nfc_login_attempts` (table)
- `nfc_login_nonces` (table)
- `nfc_login_policy` (table)
- `nfc_login_requests` (table)
- `nfc_pairings` (table)
- `outgoing_payments` (table)
- `pos_audit` (table)
- `pos_challenges` (table)
- `pos_limits` (table)
- `pos_receipts` (table)
- `pos_sessions` (table)
- `pos_terminals` (table)
- `record_capabilities` (table)
- `service_identity` (table)
- `user_currency_preferences` (table)
- `user_display_preferences` (table)
- `user_preferences` (table)
- `user_social_preferences` (table)
- `wallet_message_submissions` (table)
- `wallet_requests` (table)
- `wallets` (table)
- `incoming_due` (index)
- `incoming_owner` (index)
- `nfc_card_owner` (index)
- `outgoing_request` (index)
- `pos_terminal_owner` (index)

See [PostgreSQL foundation](030-postgresql-foundation.md) for the later persistence
and cutover work, and [identity/storage backups](008-identity-storage-backups.md)
for the recovery inventory.
