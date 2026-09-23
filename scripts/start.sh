#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
HOST="${CONTEXTMESH_HOST:-127.0.0.1}"
PORT="${CONTEXTMESH_PORT:-8765}"
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)/src"
python -m contextmesh.cli serve --host "$HOST" --port "$PORT" "$@"
