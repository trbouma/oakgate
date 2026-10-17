# FastAPI application

Date: 2026-10-17

## Current scope

The first application slice provides a branded landing page, the approved OakGate logo, a liveness endpoint, and FastAPI API documentation. Authentication, sessions, and protected routes are a subsequent milestone. The existing Keycloak service remains separate; app startup and liveness do not depend on Keycloak availability.

## Local development

Use Python 3.12 with Poetry. `poetry.toml` keeps the environment inside the repository at `.venv`, ignored by Git. Run `poetry env use python3.12`, then `poetry install`. Start with `./dev.sh`; it runs Uvicorn on `127.0.0.1:8801` with automatic reload. Override the local port with `OAKGATE_DEV_PORT=8001 ./dev.sh`. Run `poetry run pytest` for the HTTP contract and static asset checks.

No container image is built locally. The application currently needs no environment secrets and does not read the deployment `.env` file. That file configures Docker Compose on Beelink.

## Deployment

Commit `pyproject.toml`, `poetry.lock`, application source, the logo asset, Dockerfile, and Compose changes together. Pull them on Beelink and run `./start-oakgate.sh`, or use `./refresh-containers.sh` for normal updates. Both use `docker compose up --build` on the deployment machine. An app-only rebuild is `docker compose up -d --build app`.

The Docker build installs only runtime dependencies from the lockfile in a builder stage. The final Python 3.12 image runs as a non-root user and contains the application, its logo, and its virtual environment. An allowlist in `.dockerignore` excludes local credentials, virtual environments, and unrelated repository files. Production runs without reload. Container liveness checks `/health`.

The app publishes port 8801 by default; Keycloak retains port 8800. Configure `OAKGATE_PORT` and `OAKGATE_BIND_ADDRESS` in the deployment `.env` to change the app binding. No app volume is needed until it stores state. Keycloak continues using `/mnt/bitcoin/keycloak`.

## HTTPS and authentication follow-up

Choose a separate public app hostname and proxy it through the existing Nginx installation to the app port. Keycloak remains at `https://keycloak.safebox.dev`. Before adding sign-in, register development and deployment callback URLs in the `oakgate` realm and configure the OIDC client secret and server-side sessions described in the authentication design.

Uvicorn currently disables proxy-header trust. Establish the actual Nginx network path and trusted proxy addresses when adding redirect-generating authentication routes. `/health` reports only process liveness, not identity-provider readiness.

## Validation boundaries

Local verification uses the Poetry environment, HTTP tests, a real local Uvicorn smoke test, and Compose configuration validation. Container build and runtime verification must happen on Beelink, per the requested development workflow.
