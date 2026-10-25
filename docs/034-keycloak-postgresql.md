# Keycloak PostgreSQL preparation and migration checklist

## Current scope

`compose.keycloak-postgres.yaml` is an explicit opt-in. The base deployment keeps
H2 and `start-dev`; adding environment values does not activate the override.
No service, database or user has been migrated by committing this configuration.
The configuration has been rendered/checked locally, but the actual Keycloak
26.8.0 export/import and authentication flows require a rehearsal on Beelink or
an isolated staging host. Do not treat configuration checks as migration proof.

Reuse the existing private PostgreSQL 17 container, with a **separate database**
and dedicated login for Keycloak. Its tables and schema migrations are managed
by Keycloak, not OakGate's Alembic/import tooling. This role needs ownership of
its own schema so Keycloak can maintain it; do not use `oakgate_runtime`,
`oakgate_migrator` or the PostgreSQL bootstrap administrator as its runtime role.
Never point Keycloak at the `oakgate` database.

The override uses production `start`, keeps HTTPS termination at Nginx and inherits
the hostname, proxy headers, health check and NFC provider from the existing
Compose files. Keep Keycloak **26.8.0**, its matching custom provider image and
all client/backchannel secrets unchanged during this migration. `start` may
perform configuration augmentation; this is not a prebuilt `--optimized` image.

## Storage and secrets

| Setting | Purpose |
| --- | --- |
| `KEYCLOAK_DATA_DIR` | Existing H2 source; retained intact for recovery |
| `KEYCLOAK_POSTGRES_WORK_DIR` | New work/export directory, e.g. `/mnt/lexar/keycloak-postgres-work` |
| `OAKGATE_POSTGRES_DATA_DIR` | Existing PostgreSQL cluster, holding both separate databases |
| `KEYCLOAK_POSTGRES_DB` | Dedicated database, suggested `keycloak` |
| `KEYCLOAK_POSTGRES_USER` | Dedicated role, suggested `keycloak` |
| `KEYCLOAK_POSTGRES_PASSWORD` | Independent secret, generated with `openssl rand -hex 32` |

The work directory must differ from the H2 directory, OakGate data directory and
PostgreSQL cluster directory. Compose replaces the mount at `/opt/keycloak/data`
when the override is selected. It refuses a missing host directory. Do not edit
the tracked Compose file for host-specific paths or put passwords in JDBC URLs.
Keep `.env` private and backed up separately; never print rendered Compose output
containing credentials. Use `docker compose config --quiet` for validation.

## Rehearsal and identity acceptance criteria

Before a live cutover, rehearse from a consistent H2 copy into an isolated empty
PostgreSQL database using the same image. Block public access, SMTP delivery and
unintended external callbacks in staging. Never run two public Keycloak instances
against the same H2 data or expose a rehearsal as the production issuer.

- [ ] Export includes `master`, `oakgate` and every other existing realm, plus users.
- [ ] User IDs are identical before/after. OakGate binds custody by OIDC issuer and
  subject, not email. Do not recreate users manually or repair mapping by email.
- [ ] Realm names and the public issuer remain exactly unchanged:
  `https://keycloak.safebox.dev/realms/oakgate` for the existing deployment.
- [ ] Password credentials, enabled/verified state, roles/groups and Google
  federated-identity links survive. Existing Google login resolves to the same user.
- [ ] Clients, client secrets, redirects, scopes and authentication-flow overrides
  match, including `oakgate-web` and the NFC client.
- [ ] Realm signing keys/key providers, SMTP, registration/password recovery,
  required actions, browser flows and the custom NFC execution are reviewed.
- [ ] Admin login, Google login, email/password login and enrolled NFC/PIN login
  work. Revoked/non-enrolled cards remain refused.
- [ ] Each login opens the existing Acorn and correct preferences/cards, rather
  than a fresh account or wallet-connect screen.

Keep full offline exports and compare them privately, including IDs, credentials,
client secrets and key-provider components. Export JSON contains secrets. Do not
paste it into chat, commit it, put it in a public directory or use the admin UI's
partial export as a substitute. The before/after export is an acceptance aid,
not proof of complete runtime-state preservation.

## Operator procedure (only after rehearsal)

### 1. Prepare without switching

Pull the prepared code, preserve `.env` and the current `COMPOSE_FILE` selection,
and confirm all services are healthy. Do not append the new override yet.
Build the custom image on Beelink if needed, without starting/recreating Keycloak:

```sh
docker compose config --quiet
docker compose build keycloak
docker compose ps --all
```

The build command assumes `compose.nfc.yaml` is selected. Preserve the previous
working image/version for recovery. Create the new work directory with ownership
matching the Keycloak container user. Inspect the image user first:

```sh
docker compose run --rm --no-deps --entrypoint id keycloak
```

For the standard image UID 1000/GID 0 (adjust if your output differs):

```sh
sudo install -d -m 700 -o 1000 -g 0 /mnt/lexar/keycloak-postgres-work
```

Set the four `KEYCLOAK_POSTGRES_*` variables in `.env`, but retain the old Compose
selection until after H2 backup/export. Do not change `KC_HOSTNAME`, issuer URLs,
client secrets, custody keys or NFC secrets.

### 2. Create the separate empty database

In the existing PostgreSQL administrator console (substitute configured names):

```sh
docker compose exec postgres psql -U oakgate_admin -d postgres
```

Inspect `\du` and `\l` first. For a new role/database, run:

```sql
CREATE ROLE keycloak LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
\password keycloak
CREATE DATABASE keycloak OWNER keycloak ENCODING 'UTF8' TEMPLATE template0;
\connect keycloak
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO keycloak;
\q
```

Enter the same dedicated password stored in `.env`. Do not recreate an existing
database or overwrite an existing role/password without investigation. No database
role should inherit OakGate's runtime or migration role.

### 3. Stop writers; back up and export H2

Announce a sign-in maintenance window, suspend POS/account use, let in-flight
payments finish and stop these named services only:

```sh
docker compose stop pos app keycloak
docker compose ps --all
```

**PostgreSQL and Redis must remain running. Do not use `docker compose stop`
without service names or `docker compose down`.** Ensure no other Keycloak node
or tool writes to this H2 database. Take a full, protected cold backup of the
actual `KEYCLOAK_DATA_DIR`, plus configuration and the matching provider/image.
For the known Beelink source path, a fresh backup filename:

```sh
sudo sh -c 'umask 077; set -C; tar -C /mnt/lexar -cpf - keycloak > /mnt/lexar/keycloak.before-postgres.tar'
```

First verify that filename does not exist; choose a new one if it does. Check the
archive and copy it to protected independent storage. This backup is outside the
source directory. Never archive PostgreSQL's running data directory this way.

With the original H2 Compose configuration still selected, export all realms:

```sh
docker compose run --rm --no-deps --entrypoint /bin/bash keycloak -ec \
  'umask 077; /opt/keycloak/bin/kc.sh export --db dev-file --dir /opt/keycloak/data/migration-export --users different_files'
```

Use a fresh `migration-export` directory; do not mix old files into this export.
Require successful exit and check realm/user file inventory privately. Do not
add `--realm oakgate`: the administrator/master realm must be included too.
Copy the entire export directory, preserving filenames and restrictive permissions,
into the new work directory as `migration-import`, owned by the Keycloak user.
For the standard paths/user:

```sh
sudo cp -a /mnt/lexar/keycloak/migration-export /mnt/lexar/keycloak-postgres-work/migration-import
sudo chown -R 1000:0 /mnt/lexar/keycloak-postgres-work/migration-import
sudo chmod -R go-rwx /mnt/lexar/keycloak-postgres-work/migration-import
```

Check the destination did not already exist before copying. Keep the H2 source and
backup; do not delete or rename them.

### 4. Select PostgreSQL and import once

Append the new override to `.env`, retaining all existing ones:

```dotenv
COMPOSE_FILE=compose.yaml:compose.nfc.yaml:compose.postgres.yaml:compose.keycloak-postgres.yaml
```

Validate and confirm the new Keycloak database is empty:

```sh
docker compose config --quiet
docker compose exec postgres psql -U oakgate_admin -d keycloak -c \
  "SELECT count(*) AS application_tables FROM pg_tables WHERE schemaname='public';"
```

Require **zero tables** for this first import. Then run the one-off import while
Keycloak stays stopped:

```sh
docker compose run --rm --no-deps keycloak import \
  --dir /opt/keycloak/data/migration-import --override true
```

`--override true` is deliberate for the fresh target, including master realm
initialization. Never reuse this command against an already active/imported target:
it can overwrite realms. If interrupted or failed, inspect the target before
retrying; do not assume import is atomic. No automatic startup import is configured.

Export the PostgreSQL result while still stopped, into a fresh directory:

```sh
docker compose run --rm --no-deps --entrypoint /bin/bash keycloak -ec \
  'umask 077; /opt/keycloak/bin/kc.sh export --dir /opt/keycloak/data/migration-verify --users different_files'
```

Compare with the H2 export using the acceptance criteria above. Investigate
unexpected omissions or identity changes before exposing the service. Never
change OakGate's issuer or reassign wallet owners to make a bad import appear valid.

### 5. Start and test deliberately

After export comparison passes, start only Keycloak, leaving other dependencies up:

```sh
docker compose up -d --no-deps --force-recreate --wait --wait-timeout 300 keycloak
docker compose ps keycloak
docker compose logs --since=2m --tail=80 keycloak
```

Check admin access first. The existing dedicated Redis service stores ephemeral
OakGate sessions; restart **that service only** during maintenance to require fresh
OakGate login instead of retaining old app sessions across the identity migration:

```sh
docker compose restart sessions
docker compose start --wait --wait-timeout 120 sessions
docker compose up -d --no-deps --wait --wait-timeout 120 app
```

Test every login path and wallet association before reopening POS/traffic:

```sh
docker compose up -d --no-deps --wait --wait-timeout 120 pos
```

Existing POS enrollment/card records remain in OakGate PostgreSQL, not Redis.
Do not clear or restore OakGate's application database. Keep the new Compose
selection persistent so later refreshes cannot silently select the old H2 database.

## Export limitations, recovery and backups

Keycloak's CLI export requires stopped nodes for consistency and excludes
persisted sessions, events, workflow state and revoked-token state. Users should
expect to sign in again. Review token/session implications during rehearsal;
export/import is not a complete backup. See the official
[export/import guide](https://www.keycloak.org/server/importExport).

Before reopening traffic, a failed migration can be abandoned only after stopping
the new Keycloak and confirming no identity changes have been accepted. Restore
the prior Compose selection and the verified cold H2 backup if necessary. Do not
run both sources as authoritative. After registrations, password resets, linking
or revocations occur on PostgreSQL, the old H2 snapshot is stale: recovery needs
reconciliation, not just removing the override. Never roll back OakGate payment
data as part of a Keycloak rollback.

Once PostgreSQL is authoritative, back up the separate `keycloak` database with
PostgreSQL-native tooling, its role/configuration, secrets and matching image.
Test restoration to an isolated environment. Retain the cold H2 backup and export
securely for an agreed recovery period. The work directory is **not** the active
identity database. See [Keycloak database configuration](https://www.keycloak.org/server/db)
and [existing Keycloak operations](028-keycloak-operations.md).
