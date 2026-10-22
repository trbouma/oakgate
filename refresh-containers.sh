#!/bin/sh

set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$repo_dir"

if ! git diff --quiet || ! git diff --cached --quiet; then
    printf '%s\n' 'Tracked working-tree changes are present; review and preserve them before refreshing. Keep deployment storage paths in .env; do not stash storage changes just to bypass this check.' >&2
    exit 1
fi

printf '%s\n' 'Pulling fast-forward changes...'
git pull --ff-only

exec "$repo_dir/start-oakgate.sh" --force-recreate "$@"
