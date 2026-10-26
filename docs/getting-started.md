# Local development and documentation

Use this page for a development checkout and documentation preview. For a new
production home, start with [Planning for OakGate](planning-for-oakgate.md), then
follow [PostgreSQL commissioning](035-new-instance.md).

## Run the app locally

Install Python 3.12 and Poetry, then clone the repository:

```sh
git clone https://github.com/trbouma/oakgate.git
cd oakgate
poetry env use python3.12
poetry install
./dev.sh
```

Open <http://127.0.0.1:8801>. Source changes reload automatically. Stop the server with **Ctrl+C**. This workflow does not build a container. To test Google sign-in, follow [Connect OakGate sign-in](005-keycloak-sign-in.md) to create the application client and configure `.env.dev`.

```sh
poetry run pytest
```

[More about the FastAPI app](003-fastapi-app.md)

## Deploy a home instance

A fresh production deployment starts with PostgreSQL for both OakGate and
home-managed Keycloak. Follow [Planning for OakGate](planning-for-oakgate.md)
before the staged [new-instance commissioning guide](035-new-instance.md).
Do not use the local development setup as a production installation procedure.

For existing installations, use the documented refresh workflow with the
instance's configured storage paths and Compose overrides. Fresh-instance
commissioning is not an upgrade or migration tool.

## Preview this documentation

```sh
poetry install --with docs
poetry run mkdocs serve --dev-addr 127.0.0.1:8802
```

Open <http://127.0.0.1:8802/oakgate/>. The documentation preview is separate from the FastAPI app.

Build the static site with link and configuration checks:

```sh
poetry run mkdocs build --strict
```

## Publish with GitHub Pages

The repository includes a GitHub Actions workflow that builds the site and deploys on pushes to `main`, or on manual dispatch. In the repository's **Settings → Pages**, choose **GitHub Actions** as the source. Commit and push the site files and Poetry lockfile together.

The configured destination is `https://trbouma.github.io/oakgate/`. Adding the workflow locally does not publish the site; GitHub Pages must be enabled and the workflow must complete successfully. A future custom domain can be configured separately.
