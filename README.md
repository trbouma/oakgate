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

Set `KC_BOOTSTRAP_ADMIN_PASSWORD` in `.env` to the generated password. Data is stored at `/mnt/bitcoin/keycloak` on Beelink, configurable with `KEYCLOAK_DATA_DIR` in `.env`.

Before the first start, confirm the external drive is mounted and prepare the existing directory for Keycloak's container user:

```sh
mountpoint /mnt/bitcoin
# Continue only if the mount check succeeds.
sudo chown 1000:0 /mnt/bitcoin/keycloak
sudo chmod 700 /mnt/bitcoin/keycloak
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

The intended app address is `https://oakgate.safebox.dev`, served by Nginx. Its upstream is `http://<beelink-address>:8801/`. Set `OAKGATE_PUBLIC_URL`, `OAKGATE_PORT`, and `OAKGATE_BIND_ADDRESS` in `.env`. Keycloak has separate `KC_HOSTNAME`, `KEYCLOAK_PORT`, and `KEYCLOAK_BIND_ADDRESS` settings. Existing `.env` files can omit these settings and use the defaults. The app uses private Redis for temporary sessions and encrypted SQLite custody storage at `/mnt/bitcoin/oakgate`. Follow [Connect an Acorn](docs/007-acorn-custody.md) to prepare that directory and configure the custody encryption key before starting the updated containers.

For routine app-only updates on Beelink, use:

```sh
./refresh-app.sh
docker compose logs --tail=100 app
```

This refuses tracked working-tree changes, pulls fast-forward updates, and rebuilds/recreates only `app` using `--no-deps`. Keycloak and Redis stay running, so the session service must already be started. For first startup or changes to other services, use `./start-oakgate.sh` or `./refresh-containers.sh`. The script waits up to 120 seconds for the app’s Docker health check, exits nonzero on failure, and prints app status, health-check output and the last 100 app log lines. Use `./refresh-app.sh --timeout 300` for a longer startup window. The timeout starts after build/recreation; it does not limit image build time. A healthy result confirms app liveness, not a full login or payment test. To serve `oakgate.safebox.dev` over HTTPS, configure its Nginx server block to proxy to Beelink's app port. See the [deployment settings](docs/003-fastapi-app.md#deployment-settings). Authentication redirects use the configured public origin rather than forwarded headers. Follow the [sign-in setup guide](docs/005-keycloak-sign-in.md) to register exact callback URLs and set the client secret.

## Documentation site

The Material for MkDocs site follows the Mainstay product-family style, with OakGate's olive and oak-brown palette.

```sh
poetry install --with docs
poetry run mkdocs serve --dev-addr 127.0.0.1:8802
```

Preview at <http://127.0.0.1:8802/oakgate/>. Build with `poetry run mkdocs build --strict`.

The included GitHub Pages workflow publishes on pushes to `main` once **Settings → Pages → Source → GitHub Actions** is enabled. The configured site address is <https://trbouma.github.io/oakgate/>; publication has not been verified.

## Design

- [Proposed Safebox discovery contract and migration](docs/018-safebox-address-discovery.md)

- [Connect Keycloak sign-in](docs/005-keycloak-sign-in.md)
- [Authentication design](docs/001-authentication-design.md)
- [Keycloak deployment and first login](docs/002-keycloak-beelink.md)
- [FastAPI development and deployment](docs/003-fastapi-app.md)
- [Go Independent: custody and leaving OakGate](docs/004-go-independent.md)

- [OakGate and safebox-web custody models](docs/006-custody-models.md)

- [Connect an Acorn and configure custody storage](docs/007-acorn-custody.md)

- [Identity mapping, storage, and backups](docs/008-identity-storage-backups.md)

### Receiving payments

Choose a handle in Preferences to receive Lightning payments and zaps directly into your connected Acorn. The app processes payments while you are signed out and resumes pending work after a restart. The default mint is `https://mint.safebox.dev`; public zap relays and receiving limits are configurable. Invoice compatibility mode matches Safebox Web, with optional strict description-hash validation. See [Lightning payments and zaps](docs/009-lightning-receiving.md) for configuration, client compatibility and backup requirements.
