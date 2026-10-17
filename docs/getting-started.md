# Getting started

OakGate currently provides a branded FastAPI landing page, API documentation, a health endpoint, and a separate Keycloak deployment. It also supports [creating or connecting an Acorn](007-acorn-custody.md), with encrypted recovery storage and cash-balance display.

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

## Deploy on your server

On Beelink, configure `.env`, confirm the external storage mount, and prepare the [Acorn data directory and custody key](007-acorn-custody.md#deploy-on-beelink), then run:

```sh
docker compose up -d --build
```

The app uses port 8801 by default. Keycloak uses port 8800 behind the existing HTTPS proxy. Follow the [Keycloak setup guide](002-keycloak-beelink.md) for storage permissions, credentials, and proxy configuration before starting a fresh deployment.

For subsequent updates:

```sh
./refresh-containers.sh
```

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
