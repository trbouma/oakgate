#!/bin/sh
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$repo_dir"
exec poetry run uvicorn app.main:app --reload --host 127.0.0.1 --port "${OAKGATE_DEV_PORT:-8801}" "$@"
