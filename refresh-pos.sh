#!/bin/sh

set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$repo_dir"

usage() {
    printf '%s\n' 'Usage: ./refresh-pos.sh [--timeout SECONDS]' \
        'Pull updates, rebuild/recreate only pos, and wait for Docker health (default: 120 seconds).' \
        'OakGate, Keycloak and Redis are left running. The existing OakGate app must be running for /ready to report connected.'
}

health_timeout=120
case "$#:${1:-}" in
    0:) ;;
    1:-h|1:--help) usage; exit 0 ;;
    2:--timeout) health_timeout=$2 ;;
    *) usage >&2; exit 2 ;;
esac
case "$health_timeout" in
    ''|0*|*[!0-9]*) printf '%s\n' 'Timeout must be an integer from 1 to 3600 seconds.' >&2; exit 2 ;;
esac
if [ "${#health_timeout}" -gt 4 ] || [ "$health_timeout" -gt 3600 ]; then
    printf '%s\n' 'Timeout must be an integer from 1 to 3600 seconds.' >&2
    exit 2
fi

pos_container=
startup_failed() {
    printf '%s\n' "$1" >&2
    printf '%s\n' 'POS status and recent logs (OakGate, Keycloak and Redis were not restarted):' >&2
    docker compose ps --all pos >&2 || true
    if [ -n "$pos_container" ]; then
        docker inspect --format '{{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} error={{.State.Error}}' "$pos_container" >&2 || true
        docker inspect --format '{{if .State.Health}}{{range .State.Health.Log}}health exit={{.ExitCode}}: {{.Output}}{{end}}{{end}}' "$pos_container" >&2 || true
    fi
    docker compose logs --no-color --tail=100 pos >&2 || true
    exit 1
}

if ! git diff --quiet || ! git diff --cached --quiet; then
    printf '%s\n' 'Tracked working-tree changes are present; review and preserve them before refreshing. Keep deployment storage paths in .env; do not stash storage changes just to bypass this check.' >&2
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

printf '%s\n' 'Rebuilding and restarting the OakGate pos...'
if ! docker compose up --build --detach --no-deps --force-recreate pos; then
    startup_failed 'POS build or startup failed.'
fi

if ! pos_container=$(docker compose ps --all --quiet pos); then
    startup_failed 'Could not locate the pos container.'
fi
# This deployment expects exactly one pos container. Do not accidentally inspect
# or wait on another service or a stale list of replicas.
case "$pos_container" in
    ''|*[!a-zA-Z0-9]*) startup_failed 'Expected one pos container after recreation.' ;;
esac

deadline=$(( $(date +%s) + health_timeout ))
printf '%s\n' "Waiting up to ${health_timeout}s for the pos to become healthy..."
while :; do
    if ! status=$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$pos_container"); then
        startup_failed 'Could not inspect the pos container.'
    fi
    case "$status" in
        'running healthy')
            docker compose ps pos
            printf '%s\n' 'OakGate pos is healthy. OakGate, Keycloak and Redis were left running.'
            exit 0
            ;;
        *' missing') startup_failed 'The pos container has no Docker health check.' ;;
        'exited '*|'dead '*|'removing '*) startup_failed "POS stopped before becoming healthy ($status)." ;;
        *' unhealthy') startup_failed "POS failed its Docker health check ($status)." ;;
    esac
    remaining=$(( deadline - $(date +%s) ))
    if [ "$remaining" -le 0 ]; then
        startup_failed "Timed out after ${health_timeout}s waiting for pos health (last state: $status)."
    fi
    if [ "$remaining" -lt 5 ]; then
        sleep "$remaining"
    else
        sleep 5
    fi
done
