# OakGate

OpenID Access Gate — part of the Mainstay family.

## Develop locally (no Docker build)

Use Python 3.12 and Poetry 1.8.2 or newer. Dependencies are pinned in `poetry.lock`.

```sh
poetry env use python3.12
poetry install
./dev.sh
```

Open <http://127.0.0.1:8801>. Source changes reload automatically. Run tests with `poetry run pytest`. No local Keycloak, `.env`, or Docker service is required for this first app version.

The app includes the OakGate landing page and logo, `/health`, and interactive API documentation at `/docs`. Sign-in is not implemented yet. The running Keycloak instance will be connected in the next authentication milestone.

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

This refuses tracked working-tree changes, pulls fast-forward updates, and calls `start-oakgate.sh --force-recreate`. The startup script validates Compose configuration, builds the FastAPI image on Beelink from the Poetry lockfile, and starts containers. It preserves the existing `.env` and storage directory. It reports container status; use the setup guide to verify readiness.

You can also use `./start-oakgate.sh` for routine startup, or continue to run `docker compose up -d --build` directly.

Set `KC_HOSTNAME` in `.env` to the public HTTPS origin (default: `https://keycloak.safebox.dev`). Recreate the container after changing it.

The intended app address is `https://oakgate.safebox.dev`, served by Nginx. Its upstream is `http://<beelink-address>:8801/`. Set `OAKGATE_PUBLIC_URL`, `OAKGATE_PORT`, and `OAKGATE_BIND_ADDRESS` in `.env`. Keycloak has separate `KC_HOSTNAME`, `KEYCLOAK_PORT`, and `KEYCLOAK_BIND_ADDRESS` settings. Existing `.env` files can omit these settings and use the defaults. The app has no persistent data yet and needs no storage mount.

To rebuild only the app on Beelink:

```sh
docker compose up -d --build app
docker compose logs --tail=100 app
```

This leaves Keycloak running. Check `/health` after deployment. To serve `oakgate.safebox.dev` over HTTPS, configure its Nginx server block to proxy to Beelink's app port. See the [deployment settings](docs/003-fastapi-app.md#deployment-settings). The first app version does not trust forwarded headers or generate authentication redirects.

## Documentation site

The Material for MkDocs site follows the Mainstay product-family style, with OakGate's olive and oak-brown palette.

```sh
poetry install --with docs
poetry run mkdocs serve --dev-addr 127.0.0.1:8802
```

Preview at <http://127.0.0.1:8802/oakgate/>. Build with `poetry run mkdocs build --strict`.

The included GitHub Pages workflow publishes on pushes to `main` once **Settings → Pages → Source → GitHub Actions** is enabled. The configured site address is <https://trbouma.github.io/oakgate/>; publication has not been verified.

## Design

- [Authentication design](docs/001-authentication-design.md)
- [Keycloak deployment and first login](docs/002-keycloak-beelink.md)
- [FastAPI development and deployment](docs/003-fastapi-app.md)
- [Go Independent: custody and leaving OakGate](docs/004-go-independent.md)
