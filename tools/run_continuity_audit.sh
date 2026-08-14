#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

export FFMPEG="$("$ROOT_DIR/tools/find_ffmpeg.sh" "$ROOT_DIR")"

exec "$PYTHON_BIN" "$ROOT_DIR/tools/continuity_auditor.py" "$@"
