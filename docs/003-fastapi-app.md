# FastAPI application

Date: 2026-10-17

## Current scope

The first application slice provides a branded landing page, the approved OakGate logo, a liveness endpoint, and FastAPI API documentation. Authentication, temporary server-side sessions, and protected account routes are now implemented; follow [Connect OakGate sign-in](005-keycloak-sign-in.md). The existing Keycloak service remains separate; app startup and liveness do not depend on Keycloak availability.

## Local development

Use Python 3.12 with Poetry. `poetry.toml` keeps the environment inside the repository at `.venv`, ignored by Git. Run `poetry env use python3.12`, then `poetry install`. Start with `./dev.sh`; it runs Uvicorn on `127.0.0.1:8801` with automatic reload. Override the local port with `OAKGATE_DEV_PORT=8001 ./dev.sh`. Run `poetry run pytest` for the HTTP contract and static asset checks.

No container image is built locally. Sign-in reads client settings from `.env.dev` through `dev.sh`; the application does not read the deployment `.env` file. That file configures Docker Compose on Beelink.

## Deployment

Commit `pyproject.toml`, `poetry.lock`, application source, the logo asset, Dockerfile, and Compose changes together. Pull them on Beelink and run `./start-oakgate.sh`, or use `./refresh-containers.sh` for normal updates. Both build on the deployment machine and use Compose’s `--wait --wait-timeout` to wait for app, Redis and Keycloak health. The default wait is 300 seconds; pass `--timeout 600` to either script to extend it. Build time is separate. Failure returns nonzero with container status, health-check output and recent logs, without rollback. Keycloak’s `/health/ready` check uses its internal HTTP management port 9000; that port is not published. This verifies service health, not public HTTPS, sign-in, payment settlement or recovery. See [Compose health waiting](https://docs.docker.com/reference/cli/docker/compose/up/) and [Keycloak health checks](https://www.keycloak.org/observability/health). For routine app-only updates, use `./refresh-app.sh`: it checks for tracked changes, pulls with `--ff-only`, validates Compose, and runs `docker compose up --build --detach --no-deps --force-recreate app`. It waits up to 120 seconds for app Docker health after build/recreation; `--timeout 300` changes that startup window. Missing health checks, stopped/unhealthy containers, inspection errors or timeout cause a nonzero exit with app status, health-check output and recent app logs. A failed build/start also prints diagnostics. There is no automatic rollback or dependency restart. Keycloak and Redis stay running. This requires an existing running session service; use the full startup workflow for initial deployment.

The Docker build installs only runtime dependencies from the lockfile in a builder stage. The final Python 3.12 image runs as a non-root user and contains the application, its logo, and its virtual environment. An allowlist in `.dockerignore` excludes local credentials, virtual environments, and unrelated repository files. Production runs without reload. Container liveness checks `/health`.

The app publishes port 8801 by default; Keycloak retains port 8800. Configure `OAKGATE_PORT` and `OAKGATE_BIND_ADDRESS` in the deployment `.env` to change the app binding. Redis stores temporary sessions in memory. Acorn custody uses a separate encrypted database mounted from `/mnt/bitcoin/oakgate`; see [Connect an Acorn](007-acorn-custody.md) for directory permissions and the encryption key. Keycloak continues using `/mnt/bitcoin/keycloak`.

## HTTPS and authentication follow-up

Use `https://oakgate.safebox.dev` as the app origin and proxy it through the existing Nginx installation to the app port. Keycloak remains at `https://keycloak.safebox.dev`. To enable sign-in, register development and deployment callback URLs in the `oakgate` realm and configure the OIDC client secret and server-side sessions described in the authentication design.

Uvicorn currently disables proxy-header trust. Authentication redirects use `OAKGATE_PUBLIC_URL` directly, so they do not require proxy-header trust. `/health` reports only process liveness, not identity-provider readiness.

## Validation boundaries

Local verification uses the Poetry environment, HTTP tests, a real local Uvicorn smoke test, and Compose configuration validation. Container build and runtime verification must happen on Beelink, per the requested development workflow.

## Deployment settings

The app container already exists as the `app` Compose service. It is built on Beelink from the Poetry lockfile, not on the development machine. Add or update these entries in Beelink's existing `.env`; preserve its passwords and storage settings:

```dotenv
OAKGATE_PUBLIC_URL=https://oakgate.safebox.dev
OAKGATE_BIND_ADDRESS=0.0.0.0
OAKGATE_PORT=8801

KC_HOSTNAME=https://keycloak.safebox.dev
KEYCLOAK_BIND_ADDRESS=0.0.0.0
KEYCLOAK_PORT=8800
```

| Service | Public HTTPS origin | Host binding | Internal container port |
| --- | --- | --- | --- |
| OakGate app | `OAKGATE_PUBLIC_URL` | `OAKGATE_BIND_ADDRESS:OAKGATE_PORT` | 8000 |
| Keycloak | `KC_HOSTNAME` | `KEYCLOAK_BIND_ADDRESS:KEYCLOAK_PORT` | 8080 |

The app reads `OAKGATE_PUBLIC_URL` for its OpenAPI server address, login callbacks, and logout redirects. Compose also passes the OIDC client settings and private Redis URL, but not Keycloak's administrator credentials. Direct local development defaults to `http://127.0.0.1:8801`; set `OAKGATE_PUBLIC_URL` in the shell if changing the development port. Public origins must not contain an `/admin` path, credentials, or query string. Setting an origin does not create DNS records or configure TLS.

In Nginx's HTTPS server block for `oakgate.safebox.dev`, retain your certificate directives and proxy to the app:

```nginx
client_max_body_size 110M;

location / {
    proxy_pass http://127.0.0.1:8801;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Port 443;
    proxy_set_header X-Forwarded-For $remote_addr;
}
```

Set `client_max_body_size 110M;` in the HTTPS server block for **both**
`oakgate.safebox.dev` and `grove.safebox.dev`. The browser uploads to OakGate;
Acorn then uploads the encrypted attachment to Grove. Either proxy can reject
the request with HTTP 413. Check for smaller overrides in upload `location`
blocks. See [record upload limits and troubleshooting](011-record-workflows.md#nginx-upload-limits)
for validation and reload instructions. OakGate still enforces its own 25 MiB
attachment limit.

This upstream assumes Nginx runs directly on Beelink. If it runs in another container or on another machine, use the reachable Beelink address instead. Keycloak's server block continues forwarding to port 8800. If Nginx is on the host, each bind address can independently be narrowed to `127.0.0.1`. Otherwise restrict host ports to the proxy through network controls, particularly Keycloak's trusted-header endpoint.

After pulling the changes, build and start the app on Beelink:

```sh
docker compose up -d --build app
docker compose ps app
docker compose logs --tail=100 app
curl --fail https://oakgate.safebox.dev/health
```

If changing Keycloak's bind address or port too, apply its configuration separately with `docker compose up -d keycloak` and update the Nginx upstream to match. Normal `./refresh-containers.sh` updates both services. Prepare the app custody mount before starting the updated Compose service.
