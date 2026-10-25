# Private PostgreSQL foundation

## Scope

This stage provisions PostgreSQL for the upcoming OakGate database migration.
It does **not** move data, add Alembic revisions or change any application database
connection. SQLite remains authoritative for custody, payment recovery and cards;
Keycloak retains its current H2 data, and Redis retains its session role.
There is no dual write, automatic import or new dependency of wallet processing
on PostgreSQL availability.

The `postgres` Compose service uses `postgres:17-bookworm`, pins the major version,
and permits maintenance updates within that image line. Never change the major
image tag against an existing data directory without a planned PostgreSQL upgrade.
The PostgreSQL 17 data mount is `/var/lib/postgresql/data`; later image majors may
use different layouts. See the [official image documentation](https://hub.docker.com/_/postgres).

## Deployment contract

| Setting | Purpose |
| --- | --- |
| `OAKGATE_POSTGRES_DATA_DIR` | Required existing dedicated host directory; Beelink uses `/mnt/lexar/oakgate-postgres` |
| `OAKGATE_POSTGRES_DB` | Initial database name, default `oakgate` |
| `OAKGATE_POSTGRES_USER` | Bootstrap superuser, default `oakgate_admin`; not an application runtime role |
| `OAKGATE_POSTGRES_PASSWORD` | Required independent bootstrap password |

The bind mount has `create_host_path: false`: an absent directory must fail rather
than silently creating a database elsewhere. Confirm the Lexar filesystem is
mounted before startup. Directory existence alone cannot prove the intended disk
is mounted; keep that boot/mount prerequisite in the deployment configuration.

There is no published port or Nginx route. PostgreSQL is attached only to the
Compose `database` network, which is `internal: true`. App, POS and Keycloak are
not attached yet. Host/Docker administrators remain trusted; internal networking
is not a security boundary against an administrator controlling Docker.

Initialization requires a password and uses SCRAM host authentication. The image
starts with the privileges needed to set directory ownership and then runs the
server as its PostgreSQL user. Do not copy OakGate's or Keycloak's numeric UID onto
this directory. The standard entrypoint handles its own ownership. No custom
image build or init SQL is required in this stage.

## Beelink checklist: start only PostgreSQL

These steps assume the new repository changes have been committed, pushed and
pulled into the existing OakGate deployment. Preserve existing `.env` values and
the NFC `COMPOSE_FILE` override. Never print the full rendered Compose config in
shared logs because it includes secrets.

1. Confirm storage and create a new dedicated directory (not a copy of SQLite or
   Keycloak data):

   ```sh
   mountpoint /mnt/lexar
   # Continue only if this reports a mounted filesystem.
   sudo install -d -m 700 /mnt/lexar/oakgate-postgres
   ```

   If this directory already contains a database, inspect its provenance and
   version first; do not erase or reinitialize it.

2. Generate a new secret:

   ```sh
   openssl rand -hex 32
   ```

   Add the following to the deployment `.env`, replacing the placeholder with
   that output. Do not commit it:

   ```dotenv
   OAKGATE_POSTGRES_DATA_DIR=/mnt/lexar/oakgate-postgres
   OAKGATE_POSTGRES_DB=oakgate
   OAKGATE_POSTGRES_USER=oakgate_admin
   OAKGATE_POSTGRES_PASSWORD=<generated hex secret>
   ```

   ```sh
   chmod 600 .env
   docker compose config --quiet
   ```

3. Pull and start only the new service, without rebuilding or restarting app,
   Keycloak, Redis or POS:

   ```sh
   docker compose pull postgres
   docker compose up -d --no-deps --wait --wait-timeout 120 postgres
   ```

4. Verify readiness, mount and a real SQL connection:

   ```sh
   docker compose ps postgres
   docker compose logs --since=2m --tail=60 postgres
   docker inspect "$(docker compose ps -q postgres)" \
     --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
   docker compose exec -T postgres sh -ec \
     'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "SELECT current_database(), current_user, version();"'
   ```

   Expect `/mnt/lexar/oakgate-postgres -> /var/lib/postgresql/data`. Docker may
   display `5432/tcp` from image metadata: that is not a host port publication.
   The health check uses TCP `pg_isready` so the temporary socket-only init server
   is not mistaken for the final server. It checks readiness, not successful
   credential authentication; the SQL command checks those separately.

5. Verify OakGate still signs in and displays the expected wallet. This release
   does not claim that wallet data is in PostgreSQL; the new database is empty of
   application tables.

The full `start-oakgate.sh` / `refresh-containers.sh` lifecycle now waits for
PostgreSQL health and includes its status and recent logs on failure. Startup
failures leave containers available for diagnosis. App-only refresh continues to
rebuild only app. Both required PostgreSQL variables must be set before any
Compose command that validates the full configuration, even an app-only refresh.
No container is run locally as part of developing this change.

## Secrets, upgrades and backups

Image initialization variables apply only to an empty data directory. Changing
`POSTGRES_PASSWORD`, `POSTGRES_USER` or `POSTGRES_DB` in `.env` later does not
rename roles/databases or rotate their credentials. Perform an explicit database
administration change and coordinate configuration updates. Keep the bootstrap
password out of application/POS environments; before connecting OakGate, create
a restricted runtime role and a separately controlled migration role.

PostgreSQL's durability defaults remain enabled. Do not disable fsync or related
safety settings to gain speed. The server has a 60-second shutdown grace period.
SSD storage improves latency but is not a backup.

Once PostgreSQL holds useful state, add tested PostgreSQL-native logical or
physical backups and role/configuration recovery to the operator backup plan.
Do not copy a running PostgreSQL data directory with ordinary file-copy tools.
Use `pg_dump`/`pg_dumpall` for an appropriate logical backup or a PostgreSQL-aware
physical backup process, and verify restoration to an isolated instance. Continue
all existing SQLite, custody-key and Keycloak backups now: they remain essential.
Never delete the SQLite source as part of provisioning this container.

## Next stage: Alembic and application migration

The [SQLite Alembic baseline](031-sqlite-alembic-baseline.md) supplies explicit
schema adoption. The [PostgreSQL storage stage](032-postgresql-storage.md) adds
the adapter, restricted runtime-role checks, empty-target schema initialization
and concurrency/recovery tests. SQLite remains the deployment default.

The remaining stage needs a quiesced, backed-up import and verified cutover,
without concurrent old/new settlement workers. Validate against PostgreSQL 17
staging, preserve all identities and recovery state, and plan for reconciliation
if any writes occur after cutover. A stale SQLite copy cannot simply be restarted
as an authoritative wallet database.

Keycloak's H2-to-PostgreSQL move is a separate identity migration with separate
roles/database and backups. Provisioning this service does not perform it.
