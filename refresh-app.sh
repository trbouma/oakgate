#!/bin/sh

set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$repo_dir"

case "$#:$*" in
    0:) ;;
    1:-h|1:--help)
        printf '%s\n' 'Usage: ./refresh-app.sh' 'Pull updates, then rebuild and recreate only the app container.' 'Requires the existing session service to be running.'
        exit 0
        ;;
    *)
        printf '%s\n' 'Usage: ./refresh-app.sh' >&2
        exit 2
        ;;
esac

if ! git diff --quiet || ! git diff --cached --quiet; then
    printf '%s\n' 'Tracked working-tree changes are present; commit or stash them before refreshing.' >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    printf '%s\n' 'Docker with the Compose plugin is required to refresh OakGate.' >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    printf '%s\n' 'Docker is not available; check that it is running and your user has access.' >&2
    exit 1
fi

printf '%s\n' 'Pulling fast-forward changes...'
git pull --ff-only

printf '%s\n' 'Validating the OakGate Compose configuration...'
docker compose config --quiet

printf '%s\n' 'Rebuilding and restarting the OakGate app...'
docker compose up --build --detach --no-deps --force-recreate app

docker compose ps app
printf '%s\n' \
    'App startup requested. Keycloak and Redis were left running.' \
    'Check startup logs with: docker compose logs --tail=100 app'
