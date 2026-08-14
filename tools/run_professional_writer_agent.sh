#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
AGENT_HOME=${QINGSHAN_WRITER_AGENT_HOME:-"$ROOT/.professional_writer_agent/current"}
RUNTIME=${QINGSHAN_WRITER_AGENT_BIN:-"$AGENT_HOME/bin/qingshan-writer"}
PROVIDER=${QINGSHAN_WRITER_PROVIDER_BIN:-"$ROOT/.professional_writer_agent/provider-current/bin/qingshan-writer-codex-provider"}

if [ ! -x "$RUNTIME" ]; then
  printf '%s\n' "Professional Writer Agent runtime is not activated: $RUNTIME" >&2
  printf '%s\n' "Install an accepted package, then set QINGSHAN_WRITER_AGENT_HOME or QINGSHAN_WRITER_AGENT_BIN." >&2
  exit 78
fi

case "${1:-}" in
  health|--health|--version)
    exec "$RUNTIME" "$@"
    ;;
  version)
    exec "$RUNTIME" --version
    ;;
esac

"$RUNTIME" health >/dev/null

if [ "${1:-}" = "generate" ]; then
  if [ -z "${QINGSHAN_WRITER_PROVIDER_COMMAND:-}" ] && [ -x "$PROVIDER" ]; then
    QINGSHAN_WRITER_PROVIDER_COMMAND=$PROVIDER
    export QINGSHAN_WRITER_PROVIDER_COMMAND
  fi
  has_model=false
  for arg in "$@"; do
    if [ "$arg" = "--model" ]; then
      has_model=true
      break
    fi
  done
  if [ "$has_model" = false ]; then
    exec "$RUNTIME" "$@" --model "${QINGSHAN_WRITER_MODEL:-gpt-5.6-sol}"
  fi
fi

exec "$RUNTIME" "$@"
