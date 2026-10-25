# OakGate

OpenID Access Gate — part of the Mainstay family.

## Develop locally (no Docker build)

Use Python 3.12 and Poetry 1.8.2 or newer. Dependencies are pinned in `poetry.lock`.

```sh
poetry env use python3.12
poetry install
./dev.sh
```

Open <http://127.0.0.1:8801>. Source changes reload automatically. Run tests with `poetry run pytest`. No local Docker service is required. To test sign-in, configure `.env.dev` with the Keycloak client credentials using the [sign-in setup guide](docs/005-keycloak-sign-in.md).

The app includes the OakGate landing page and logo, `/health`, and interactive API documentation at `/docs`. Keycloak sign-in, a protected account page, `/api/me`, and sign-out are implemented. The realm supplies Google sign-in. An unconfigured app still serves the landing page and explains that sign-in setup is needed.

## Run on Beelink

Requires Docker with Docker Compose and available ports 8800 (Keycloak) and 8801 (FastAPI).

```sh
git clone https://github.com/trbouma/oakgate.git
cd oakgate
cp .env.example .env
chmod 600 .env
openssl rand -hex 24
```

Set `KC_BOOTSTRAP_ADMIN_PASSWORD` in `.env` to the generated password. Set the required `KEYCLOAK_DATA_DIR` in `.env` to the existing Keycloak data directory (Beelink: `/mnt/lexar/keycloak`).

Before the first start, confirm the external drive is mounted and prepare the existing directory for Keycloak's container user:

```sh
mountpoint /mnt/lexar
# Continue only if the mount check succeeds.
sudo chown 1000:0 /mnt/lexar/keycloak
sudo chmod 700 /mnt/lexar/keycloak
```

Then run:

```sh
docker compose up -d --build
```

Keycloak runs in development mode with persistent storage and publishes `0.0.0.0:8800` on Beelink (container port 8080). From another machine, open `https://keycloak.safebox.dev/admin/master/console/`. See the [Beelink setup guide](docs/002-keycloak-beelink.md).

For subsequent updates, use the same workflow as Mainstay:

```sh
./refresh-containers.sh
```

This refuses tracked working-tree changes, pulls fast-forward updates, and calls `start-oakgate.sh --force-recreate`. The startup script validates Compose configuration, builds the FastAPI image on Beelink from the Poetry lockfile, and starts containers. It preserves the existing `.env` and storage directory. It waits for app, Redis and Keycloak health checks, with a 300-second startup timeout. Use `./refresh-containers.sh --timeout 600` (or `./start-oakgate.sh --timeout 600`) for a longer wait. Build time is separate from the health wait. Failure exits nonzero and prints service status, health-check output and recent logs; containers are left available for diagnosis, without rollback. Requires Docker Compose with `--wait` and `--wait-timeout` support. Keycloak readiness is checked internally on port 9000, which is not published to the host. Public HTTPS, login and payment checks remain separate acceptance steps.

You can also use `./start-oakgate.sh` for routine startup, or continue to run `docker compose up -d --build` directly.

Set `KC_HOSTNAME` in `.env` to the public HTTPS origin (default: `https://keycloak.safebox.dev`). Recreate the container after changing it.

The intended app address is `https://oakgate.safebox.dev`, served by Nginx. Its upstream is `http://<beelink-address>:8801/`. Set `OAKGATE_PUBLIC_URL`, `OAKGATE_PORT`, and `OAKGATE_BIND_ADDRESS` in `.env`. Keycloak has separate `KC_HOSTNAME`, `KEYCLOAK_PORT`, and `KEYCLOAK_BIND_ADDRESS` settings. Existing `.env` files can omit these settings and use the defaults. The app uses private Redis for temporary sessions and encrypted SQLite custody storage at the host path selected by `OAKGATE_DATA_DIR`. There is no Compose storage default; Beelink now uses `/mnt/lexar/oakgate`. See the [storage latency incident](docs/022-storage-latency-incident.md) for measurements and migration precautions. Follow [Connect an Acorn](docs/007-acorn-custody.md) to prepare that directory and configure the custody encryption key before starting the updated containers.

For routine app-only updates on Beelink, use:

```sh
./refresh-app.sh
docker compose logs --tail=100 app
```

This refuses tracked working-tree changes, pulls fast-forward updates, and rebuilds/recreates only `app` using `--no-deps`. Keycloak and Redis stay running, so the session service must already be started. For first startup or changes to other services, use `./start-oakgate.sh` or `./refresh-containers.sh`. The script waits up to 120 seconds for the app’s Docker health check, exits nonzero on failure, and prints app status, health-check output and the last 100 app log lines. Use `./refresh-app.sh --timeout 300` for a longer startup window. The timeout starts after build/recreation; it does not limit image build time. A healthy result confirms app liveness, not a full login or payment test. To serve `oakgate.safebox.dev` over HTTPS, configure its Nginx server block to proxy to Beelink's app port. See the [deployment settings](docs/003-fastapi-app.md#deployment-settings). Set `client_max_body_size 110M;` on both the OakGate and Grove Nginx hosts to avoid HTTP 413 during record uploads; see [upload limits](docs/011-record-workflows.md#nginx-upload-limits). Authentication redirects use the configured public origin rather than forwarded headers. Follow the [sign-in setup guide](docs/005-keycloak-sign-in.md) to register exact callback URLs and set the client secret.

## Documentation site

The Material for MkDocs site follows the Mainstay product-family style, with OakGate's olive and oak-brown palette.

```sh
poetry install --with docs
poetry run mkdocs serve --dev-addr 127.0.0.1:8802
```

Preview at <http://127.0.0.1:8802/oakgate/>. Build with `poetry run mkdocs build --strict`.

The included GitHub Pages workflow publishes on pushes to `main` once **Settings → Pages → Source → GitHub Actions** is enabled. The configured site address is <https://trbouma.github.io/oakgate/>; publication has not been verified.

## Design

- [Receive-only POS terminals and browser-bound keys](docs/023-receive-only-pos.md)
- [POS NFC card issuance](docs/025-pos-nfc-cards.md)
- [Everyday NFC card trust and security](docs/029-nfc-card-trust.md)
- [NFC cards and payment execution](docs/026-nfc-card-payments.md)
- [Keycloak operations and sign-in flows](docs/028-keycloak-operations.md)
- [Keycloak NFC card and PIN login](docs/027-keycloak-nfc-login.md)

- [Safebox discovery contract and migration](docs/018-safebox-address-discovery.md)

- [Connect Keycloak sign-in](docs/005-keycloak-sign-in.md)
- [Authentication design](docs/001-authentication-design.md)
- [Keycloak deployment and first login](docs/002-keycloak-beelink.md)
- [FastAPI development and deployment](docs/003-fastapi-app.md)
- [Go Independent: custody and leaving OakGate](docs/004-go-independent.md)

- [OakGate and safebox-web custody models](docs/006-custody-models.md)

- [Connect an Acorn and configure custody storage](docs/007-acorn-custody.md)

- [Identity mapping, storage, and backups](docs/008-identity-storage-backups.md)
- [PostgreSQL backup and recovery plan](docs/036-backup-and-recovery-plan.md)

### Receiving payments

Choose a handle in Preferences to receive Lightning payments and zaps directly into your connected Acorn. The app processes payments while you are signed out and resumes pending work after a restart. The default mint is `https://mint.safebox.dev`; public zap relays and receiving limits are configurable. Invoice compatibility mode matches Safebox Web, with optional strict description-hash validation. See [Lightning payments and zaps](docs/009-lightning-receiving.md) for configuration, client compatibility and backup requirements.

### Social identity

Preferences accepts an optional public social npub for your handle's NIP-05
address. Set the same address in your signed Nostr profile so clients can verify
the association. OakGate does not request proof of control or a social private key.
Leave blank to retain the Acorn public key as the default NIP-05 identity.
Payments and wallet discovery remain bound to the Acorn through `safebox.json`.
Older NIP-05-based wallet clients cannot safely use an address with distinct keys;
see the [migration and compatibility notes](docs/018-safebox-address-discovery.md#enabling-a-distinct-social-npub-in-oakgate).

### Wallet messages

The Wallet messages page uses Acorn wallet keys and `safebox.json`, independently
of social NIP-05. See [wallet messaging and dependency rollout](docs/019-wallet-messages.md).

## Explicit Docker storage paths

Storage settings in `.env` are required. Both an absent/empty setting and a
missing host directory fail instead of selecting a fallback or creating a new
empty directory. Set the path to the CURRENT data, not an older backup:

```dotenv
OAKGATE_DATA_DIR=/mnt/lexar/oakgate
KEYCLOAK_DATA_DIR=/mnt/lexar/keycloak
```

These settings are Docker host paths; internal container paths stay unchanged.
Keep `.env` ignored by Git and backed up with the matching instance secrets.
This configuration does not copy or migrate data. Before converting a deployment
from a named volume, stop all services sharing its database, take a consistent
backup and explicitly migrate the current directory with ownership preserved.
Keep the old copy until the new mounts, identities and application data are
verified. For a fresh installation only, pre-create a directory writable by the
container's configured user. Never create an empty replacement for an existing
instance.

Verify the external drive is mounted before startup (for Beelink, `mountpoint /mnt/lexar`). `create_host_path: false` checks directory existence, not drive
identity; it cannot detect an unmounted drive if a directory already exists
underneath the mount point. This applies to Docker restarts at boot too.

Run `docker compose config --quiet` before deployment and inspect the actual
container mounts afterward. Keep storage selection in `.env` rather than local
Compose edits, so refreshes do not require stashing deployment configuration.

### Refresh readiness contract

Use `./refresh-containers.sh --timeout 300` to pull fast-forward updates and
recreate the full deployment with a bounded readiness wait. The timeout is in
seconds (1–3600); it applies to startup readiness, not image build time. All
required services must pass Docker readiness before success is reported.
Docker Compose with `--wait` and `--wait-timeout` support is required. Failures
report service state, recent health-check output and logs; they do not delete
volumes, reset payment records or attempt an automatic data rollback.
Review diagnostic output for secrets before sharing it.

Standalone refresh defaults to 120 seconds; Mainstay and OakGate full-stack
startup default to 300 seconds. OakGate's `./refresh-app.sh --timeout 120`
remains app-only and leaves Keycloak and Redis running. Application checks
(login, public HTTPS, record retrieval and a small payment) remain separate
from container readiness. Never run two refresh operations concurrently.

### Separate POS service

The optional POS service runs on its own port (8804 by default), disabled by
default with `OAKGATE_POS_ENABLED=false`. Use `./refresh-pos.sh` to rebuild only
POS with a bounded health wait. It has no wallet data mount or account access.
Users can provision a terminal in Preferences, activate its browser-bound key,
and revoke it. Terminals receive Cash and Clear using a currency-aware keypad,
QR codes and payment detection, without account or spending access. See the
[POS deployment guide](docs/024-pos-deployment.md) for environment settings and Nginx setup.

### Private PostgreSQL (infrastructure stage)

Before refreshing this version, add the PostgreSQL settings and create its dedicated
SSD directory using [the PostgreSQL setup checklist](docs/030-postgresql-foundation.md).
`OAKGATE_POSTGRES_DATA_DIR` and `OAKGATE_POSTGRES_PASSWORD` are required, including
when Compose validates an app-only refresh. PostgreSQL has no published port.
Full-stack startup waits for its health and includes its logs on failure;
`refresh-app.sh` leaves it running. OakGate still uses SQLite and Keycloak still
uses H2. The [SQLite Alembic baseline](docs/031-sqlite-alembic-baseline.md) is now available as an explicit maintenance step; PostgreSQL data migration remains separate.

### SQLite schema baseline

An explicit, backed-up Alembic adoption command is available; app startup still
uses SQLite and never runs migrations automatically. Follow the
[SQLite baseline maintenance procedure](docs/031-sqlite-alembic-baseline.md),
including stopping every writer, before adopting an existing deployment.

### PostgreSQL storage compatibility (opt-in staging)

A PostgreSQL adapter, restricted runtime-role checks and explicit Alembic target
schema are available. **SQLite remains the default; no live data is imported or
switched by this release.** Do not enable `compose.postgres.yaml` for production
until the controlled import and verification procedure has completed. See the
[PostgreSQL storage guide](docs/032-postgresql-storage.md) for staging configuration,
transaction behavior and real-database tests. Keycloak's database is unchanged.

The [controlled import and cutover guide](docs/033-postgresql-cutover.md) provides
an offline exact-copy importer, independent verification, SQLite restart fencing
and the Beelink checklist. No live cutover happens automatically.

### Optional Keycloak PostgreSQL migration

The base Keycloak configuration remains H2. A separate, explicit
`compose.keycloak-postgres.yaml` override selects production mode and a dedicated
database in the existing PostgreSQL service, preserving the NFC provider override.
Do not activate it until following the [Keycloak migration checklist](docs/034-keycloak-postgresql.md).
No users or realms are imported automatically; rehearsal and identity-continuity
checks are required before live cutover.

### Commission a fresh instance

For a **new deployment only**, use `./init-instance.sh prepare`, then `check` and
`bootstrap` on the deployment host. The wizard generates private configuration,
asks before building/starting, and uses PostgreSQL for both OakGate and Keycloak.
Configure the Keycloak realm/sign-in clients, then run `./init-instance.sh activate`
to enter client secrets and start OakGate/POS. Existing `.env` files, nonempty
storage and existing project containers are refused; this is not a migration tool.
See the [new-instance checklist](docs/035-new-instance.md) for prerequisites,
Keycloak setup, interruption handling and acceptance tests.

### Commissioning a production home

New production homes use PostgreSQL for both OakGate and Keycloak. Start with the
[home readiness checklist](docs/035-new-instance.md#home-instance-readiness), then
use the staged `init-instance.sh` workflow. Keycloak setup, enabled-feature tests
and a tested off-host backup are required commissioning work; container health
alone is not production readiness. Never run fresh initialization on an existing
instance. Satellite support is not required to operate a standalone home.
