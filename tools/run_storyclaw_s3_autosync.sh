#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

set -a
source "$ROOT/.secrets/s3_relay.env"
set +a

EXPLICIT_FINAL=0
EXPLICIT_SCAN_MODE=0
EXPLICIT_FOREGROUND=0
FORWARD_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --final-video) EXPLICIT_FINAL=1 ;;
    --no-scan) EXPLICIT_SCAN_MODE=1 ;;
    --foreground) EXPLICIT_FOREGROUND=1; continue ;;
  esac
  FORWARD_ARGS+=("$arg")
done

if [[ "$EXPLICIT_FINAL" -eq 1 && "$EXPLICIT_SCAN_MODE" -eq 0 ]]; then
  exec "$ROOT/.s3_relay_env_py312/bin/python3" \
    "$ROOT/tools/storyclaw_s3_autosync.py" ${FORWARD_ARGS[@]+"${FORWARD_ARGS[@]}"} --no-scan
fi

if [[ "$EXPLICIT_FINAL" -eq 1 || "$EXPLICIT_FOREGROUND" -eq 1 ]]; then
  exec "$ROOT/.s3_relay_env_py312/bin/python3" \
    "$ROOT/tools/storyclaw_s3_autosync.py" ${FORWARD_ARGS[@]+"${FORWARD_ARGS[@]}"}
fi

RUNTIME_DIR="$ROOT/workflow/s3_relay/runtime"
PID_FILE="$RUNTIME_DIR/storyclaw_s3_autosync.pid"
LOG_FILE="$RUNTIME_DIR/storyclaw_s3_autosync.log"
mkdir -p "$RUNTIME_DIR"

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(tr -dc '0-9' < "$PID_FILE")"
  if [[ -n "$EXISTING_PID" ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    printf '{"status":"ALREADY_RUNNING_ASYNC","pid":%s,"log":"%s"}\n' "$EXISTING_PID" "$LOG_FILE"
    exit 0
  fi
fi

nohup "$ROOT/.s3_relay_env_py312/bin/python3" \
  "$ROOT/tools/storyclaw_s3_autosync.py" ${FORWARD_ARGS[@]+"${FORWARD_ARGS[@]}"} \
  >>"$LOG_FILE" 2>&1 &
ASYNC_PID=$!
printf '%s\n' "$ASYNC_PID" > "$PID_FILE"
printf '{"status":"STARTED_ASYNC","pid":%s,"log":"%s"}\n' "$ASYNC_PID" "$LOG_FILE"
