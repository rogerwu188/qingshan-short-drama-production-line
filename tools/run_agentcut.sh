#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RUNTIME="$ROOT/.agentcut_env/bin/agentcut"

if [ ! -x "$RUNTIME" ]; then
  printf '%s\n' "AgentCut runtime is not activated: $RUNTIME" >&2
  printf '%s\n' "Create it with: $ROOT/.local/bin/python3 -m venv $ROOT/.agentcut_env" >&2
  exit 78
fi

exec "$RUNTIME" "$@"
