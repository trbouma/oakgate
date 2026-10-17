# OakGate

OpenID Access Gate — part of the Mainstay family.

## Run on Beelink

Requires Docker with Docker Compose and an available port 8800.

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
docker compose up -d
```

Keycloak runs in development mode with persistent storage and publishes `0.0.0.0:8800` on Beelink (container port 8080). From another machine, open `http://<beelink-vpn-ip-or-hostname>:8800/admin/`. See the [Beelink setup guide](docs/002-keycloak-beelink.md).

For subsequent updates, use the same workflow as Mainstay:

```sh
./refresh-containers.sh
```

This refuses tracked working-tree changes, pulls fast-forward updates, and calls `start-oakgate.sh --force-recreate`. The startup script validates the Compose configuration before starting containers. It preserves the existing `.env` and storage directory. It reports container status; use the setup guide to verify readiness.

You can also use `./start-oakgate.sh` for routine startup, or continue to run `docker compose up -d` directly.

## Design

- [Authentication design](docs/001-authentication-design.md)
- [Keycloak deployment and first login](docs/002-keycloak-beelink.md)
