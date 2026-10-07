#!/bin/bash
# paid_stage.sh — the line's single, auditable entry point for PAID provider stages.
#
# WHY THIS EXISTS
# A paid stage needs the provider credential in the environment and the `--paid` flag.  Written
# out as a shell one-liner it is `cd … && set -a && source .env && … && nalu_pipeline.py run
# --paid`, which no permission rule can match narrowly: the command is a chain, it sources a
# file full of secrets, and the interesting part (`--paid`) is buried in the middle.  The result
# is that every paid step is either re-approved by hand or refused outright, and the line owner
# has to sit in the loop for work his standing order already authorised.
#
# This script collapses that into ONE argv with no shell operators and no visible secret access,
# so a permission rule can name exactly this entry point and nothing else.  It does not grant
# itself anything: the authorization it relies on is the line's own, checked at run time by
# materialize_paid_authorization.py (D-11) and nalu_budget_ledger.py, exactly as before.
#
# WHAT STILL GUARDS THE SPEND (none of it is bypassed here)
#   * the line owner's private order: sequence, episode scope, paid stages, model, rights basis,
#     confirmed source receipt, and paid_requests_allowed=true;
#   * configs-relative `generation.paid_requests_enabled` in the runtime's qingshan.json — the
#     second lock, independent of `--paid`;
#   * the per-episode credit cap (HARD_STOP at the order's cap; the ledger refuses before POST);
#   * the whole-batch prompt gate (K041) — every unit's keyframe and video prompt must be
#     registered with a reviewer PASS receipt whose SHA still matches the file;
#   * the durable transaction store, so a task fingerprint is never POSTed twice.
#
# USAGE
#   paid_stage.sh <EPISODE> <FROM_STAGE> <UNTIL_STAGE>
#   paid_stage.sh E11 S5 S5
#   paid_stage.sh E11 S6 S6
#
#   paid_stage.sh --check <EPISODE>            print the budget position, spend nothing
#
# Exit codes: 0 ok · 2 usage · 3 preflight refused (no spend, no POST attempted) · other = pipeline.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_ROOT="$(cd "$HERE/../../../.." && pwd)"
VENV="${NALU_VENV_PYTHON:-$ENGINE_ROOT/.qingshan-venv/bin/python}"

die() { printf 'paid_stage: %s\n' "$*" >&2; exit "${2:-3}"; }

usage() {
  printf 'usage: paid_stage.sh <EPISODE> <FROM_STAGE> <UNTIL_STAGE>\n' >&2
  printf '       paid_stage.sh --check <EPISODE>\n' >&2
  exit 2
}

[ $# -ge 2 ] || usage
CHECK_ONLY=0
if [ "$1" = "--check" ]; then CHECK_ONLY=1; EPISODE="$2"; else
  [ $# -eq 3 ] || usage
  EPISODE="$1"; FROM_STAGE="$2"; UNTIL_STAGE="$3"
fi
case "$EPISODE" in E[0-9][0-9]) ;; *) die "episode must look like E11, got '$EPISODE'" 2 ;; esac

# The credential and the authority coordinates normally sit in .env.  Load it only when they are
# not already in the environment: a deployment that injects them per-process (for example an agent
# runtime whose settings carry an `env` block) then never has this script read a secret file at
# all, which is the difference between "the runtime can run its own paid stages" and "every paid
# step needs a human to type a command".  Never echo the values either way.
ENV_FILE="$ENGINE_ROOT/.env"
if [ -z "${GIGGLE_API_KEY:-}" ] || [ -z "${NALU_PAID_ORDER_SEQ:-}" ]; then
  [ -f "$ENV_FILE" ] || die "credentials are not in the environment and there is no $ENV_FILE"
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
[ -x "$VENV" ] || die "no interpreter at $VENV (set NALU_VENV_PYTHON)"

for var in NALU_RUNTIME_ROOT NALU_ENGINE_ROOT NALU_SUPERVISOR_ORDERS_PATH NALU_PAID_ORDER_SEQ \
           NALU_LATEST_ORDER_SEQ NALU_LINE_OWNER_ID; do
  [ -n "${!var:-}" ] || die "$var is unset after sourcing $ENV_FILE; refusing to spend without it"
done
[ -n "${GIGGLE_API_KEY:-}" ] || die "GIGGLE_API_KEY is unset; the paid submitter would fail after the gate passed"

export PYTHONPATH="$ENGINE_ROOT:$ENGINE_ROOT/lines/nalu/runtime/tools${PYTHONPATH:+:$PYTHONPATH}"
export QINGSHAN_VOICE_REGISTRY="${QINGSHAN_VOICE_REGISTRY:-$NALU_RUNTIME_ROOT/runtime/voice_registry.json}"
export NALU_WORK_ROOT="${NALU_WORK_ROOT:-$ENGINE_ROOT/workflow/nalu}"

LEDGER="$ENGINE_ROOT/lines/nalu/runtime/tools/nalu_budget_ledger.py"
if [ -f "$LEDGER" ]; then
  echo "paid_stage: budget position for $EPISODE"
  "$VENV" "$LEDGER" --check --episode "$EPISODE" --planned-credits 0 || die "budget preflight refused; no POST was attempted"
fi
[ "$CHECK_ONLY" = 1 ] && exit 0

echo "paid_stage: $EPISODE $FROM_STAGE..$UNTIL_STAGE --paid (order seq=$NALU_PAID_ORDER_SEQ, owner=$NALU_LINE_OWNER_ID)"
exec "$VENV" "$ENGINE_ROOT/lines/nalu/runtime/tools/nalu_pipeline.py" run \
  --episode "$EPISODE" --from "$FROM_STAGE" --until "$UNTIL_STAGE" --paid
