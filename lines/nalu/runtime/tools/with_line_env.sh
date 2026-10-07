#!/bin/bash
# with_line_env.sh — run any command with the nalu line's environment already loaded.
#
# WHY THIS EXISTS
# The provider credential (GIGGLE_API_KEY) and the line-owner authority coordinates live in
# $ENGINE_ROOT/.env, not in the process environment.  So every tool that touches the provider had
# to be launched as `set -a; source .env; set +a; <tool>`, and that form is un-runnable by an
# automated caller: it is a shell chain that reads a file full of secrets.  A deployment that
# injects these variables per-process does not need this script at all; this is the fallback for
# one that does not, so the caller's command line stays a plain tool invocation.
#
# It grants nothing by itself.  It loads the same file the human-run one-liner loaded, exports the
# same variables, and execs the caller's command unchanged.  Paid stages still go through
# paid_stage.sh, which carries the order/budget/batch gates.
#
#   with_line_env.sh <command> [args...]
#   with_line_env.sh .qingshan-venv/bin/python tools/harvest_giggle_image_batch.py --submit-report …
#
# The values are never echoed.  Exit code is the command's own.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_ROOT="$(cd "$HERE/../../../.." && pwd)"

[ $# -ge 1 ] || { printf 'usage: with_line_env.sh <command> [args...]\n' >&2; exit 2; }

ENV_FILE="$ENGINE_ROOT/.env"
if [ -z "${GIGGLE_API_KEY:-}" ] || [ -z "${NALU_PAID_ORDER_SEQ:-}" ]; then
  [ -f "$ENV_FILE" ] || { printf 'with_line_env: no %s and the variables are not already set\n' "$ENV_FILE" >&2; exit 3; }
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

# The tools resolve paths through nalu_paths.py and import siblings from tools/.
export PYTHONPATH="$ENGINE_ROOT:$ENGINE_ROOT/lines/nalu/runtime/tools${PYTHONPATH:+:$PYTHONPATH}"
export QINGSHAN_VOICE_REGISTRY="${QINGSHAN_VOICE_REGISTRY:-${NALU_RUNTIME_ROOT:-$ENGINE_ROOT/runtime}/runtime/voice_registry.json}"

case "$1" in
  /*) exec "$@" ;;                                        # absolute command path
  ./*|../*) exec "$ENGINE_ROOT/$1" "${@:2}" ;;             # engine-relative path
  *) exec "$@" ;;                                          # resolve on PATH
esac
