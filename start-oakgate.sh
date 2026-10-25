#!/bin/sh

set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$repo_dir"

health_timeout=300
force_recreate=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --force-recreate) force_recreate=true ;;
        --timeout)
            [ "$#" -ge 2 ] || { printf '%s\n' 'Missing timeout value.' >&2; exit 2; }
            health_timeout=$2
            shift
            ;;
        -h|--help)
            printf '%s\n' 'Usage: ./start-oakgate.sh [--force-recreate] [--timeout SECONDS] (default: 300)'
            exit 0
            ;;
        *)
            printf '%s\n' "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
    shift
done

case "$health_timeout" in
    ''|0*|*[!0-9]*) printf '%s\n' 'Timeout must be an integer from 1 to 3600 seconds.' >&2; exit 2 ;;
esac
if [ "${#health_timeout}" -gt 4 ] || [ "$health_timeout" -gt 3600 ]; then
    printf '%s\n' 'Timeout must be an integer from 1 to 3600 seconds.' >&2
    exit 2
fi

startup_failed() {
    printf '%s\n' "Startup failed or did not become healthy within ${health_timeout}s." >&2
    docker compose ps --all app sessions keycloak postgres >&2 || true
    for service in app sessions keycloak postgres; do
        container=$(docker compose ps --all --quiet "$service") || continue
        case "$container" in ''|*[!a-zA-Z0-9]*) continue ;; esac
        printf '%s\n' "Diagnostics for $service:" >&2
        docker inspect --format '{{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} error={{.State.Error}}' "$container" >&2 || true
        docker inspect --format '{{if .State.Health}}{{range .State.Health.Log}}health exit={{.ExitCode}}: {{.Output}}{{end}}{{end}}' "$container" >&2 || true
    done
    docker compose logs --no-color --tail=100 app sessions keycloak postgres >&2 || true
    exit 1
}

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

# Require Compose's bounded health wait before changing any containers.
if ! docker compose up --help | grep -q -- '--wait-timeout'; then
    printf '%s\n' 'Update Docker Compose: --wait and --wait-timeout support is required.' >&2
    exit 1
fi

printf '%s\n' "Starting OakGate and waiting up to ${health_timeout}s for service health..."
set -- --build --detach --wait --wait-timeout "$health_timeout"
if [ "$force_recreate" = true ]; then
    set -- "$@" --force-recreate
fi
if ! docker compose up "$@"; then
    startup_failed
fi

docker compose ps
printf '%s\n' \
    'OakGate app, Redis, Keycloak and PostgreSQL passed their health checks.' \
    'Verify public HTTPS, login and payments separately.' \
    'App: OAKGATE_PUBLIC_URL from .env (default https://oakgate.safebox.dev)' \
    'Admin console: KC_HOSTNAME from .env followed by /admin/master/console/'
