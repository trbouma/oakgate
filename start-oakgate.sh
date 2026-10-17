#!/bin/sh

set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$repo_dir"

force_recreate=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --force-recreate) force_recreate=true ;;
        -h|--help)
            printf '%s\n' 'Usage: ./start-oakgate.sh [--force-recreate]'
            exit 0
            ;;
        *)
            printf '%s\n' "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
    shift
done

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    printf '%s\n' 'Docker with the Compose plugin is required to start OakGate.' >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    printf '%s\n' 'Docker is not available; check that it is running and your user has access.' >&2
    exit 1
fi

printf '%s\n' 'Validating the OakGate Compose configuration...'
docker compose config --quiet

printf '%s\n' 'Starting OakGate...'
if [ "$force_recreate" = true ]; then
    docker compose up --detach --force-recreate
else
    docker compose up --detach
fi

docker compose ps
printf '%s\n' \
    'Startup requested. Keycloak may still be initializing.' \
    'Check startup logs with: docker compose logs --tail=100 keycloak' \
    'Open the SSH tunnel described in docs/002-keycloak-beelink.md to reach the console.'
