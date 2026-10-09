#!/bin/bash
# run_unattended.sh — advance one episode with nobody at the terminal.
#
# WHY THIS EXISTS
# An interactive Claude Code session asks a person every time a command is not on the allow-list.
# On a deployed machine there is no person, so every such question becomes a session that waits
# forever.  The fix is not "allow everything": it is to run in `dontAsk` mode, where anything not
# pre-allowed is *refused* instead of asked, and the agent is told (unattended_runner.md) to stop
# and leave a decision note when it hits something it may not do.
#
# The allow-list comes from .claude/settings.json (tracked, relative) and settings.local.json
# (generated per machine by automation_profile.py write).  Neither is an authority: spend is still
# gated by the deployed order, the qingshan.json lock, the per-episode cap, the K041 batch gate and
# the transaction store, all inside the repository's own code.
#
# USAGE
#   run_unattended.sh <EPISODE> [--max-turns N] [--max-budget-usd X]
#
# Typical schedule: cron / launchd every 20 minutes.  The script holds a lock, so two firings never
# overlap; a run that ends on REVIEW_REQUIRED simply resumes at the next firing after the agent has
# answered the review, and a run that ends on a decision note stays stopped until the owner acts.
#
# Exit codes: 0 session ended · 2 usage · 3 preflight refused · 4 another run holds the lock ·
#             5 a decision for the line owner is pending · other = claude CLI.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_ROOT="$(cd "$HERE/../../../.." && pwd)"
die() { printf 'run_unattended: %s\n' "$1" >&2; exit "${2:-3}"; }

[ $# -ge 1 ] || die "usage: run_unattended.sh <EPISODE> [--max-turns N] [--max-budget-usd X]" 2
EPISODE="$1"; shift
case "$EPISODE" in E[0-9][0-9]) ;; *) die "episode must look like E11, got '$EPISODE'" 2 ;; esac
MAX_TURNS=200
MAX_BUDGET_USD=""
while [ $# -gt 0 ]; do
  case "$1" in
    --max-turns) MAX_TURNS="$2"; shift 2 ;;
    --max-budget-usd) MAX_BUDGET_USD="$2"; shift 2 ;;
    *) die "unknown option $1" 2 ;;
  esac
done

: "${NALU_RUNTIME_ROOT:?set NALU_RUNTIME_ROOT}"
export NALU_ENGINE_ROOT="${NALU_ENGINE_ROOT:-$ENGINE_ROOT}"
command -v claude >/dev/null || die "claude CLI not on PATH"

# The profile must exist and be clean before an unattended session is allowed to start: without it
# dontAsk refuses even the line's own entry points and the run achieves nothing.
"${NALU_VENV_PYTHON:-$ENGINE_ROOT/.qingshan-venv/bin/python}" "$HERE/automation_profile.py" check \
  --repo-root "$ENGINE_ROOT" >/dev/null || die "automation profile missing or unsafe; run automation_profile.py write"

REPORTS="$NALU_RUNTIME_ROOT/runtime/reports"
mkdir -p "$REPORTS"
PENDING="$REPORTS/${EPISODE}_OWNER_DECISION_PENDING.md"
if [ -f "$PENDING" ]; then
  printf 'run_unattended: %s is waiting on the line owner: %s\n' "$EPISODE" "$PENDING" >&2
  exit 5
fi

LOCK="$NALU_RUNTIME_ROOT/runtime/.unattended_${EPISODE}.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  holder="$(cat "$LOCK/pid" 2>/dev/null || true)"
  if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
    printf 'run_unattended: run %s already active (pid %s)\n' "$EPISODE" "$holder" >&2
    exit 4
  fi
  rm -rf "$LOCK"; mkdir "$LOCK"   # stale lock from a crashed run
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

LOG="$REPORTS/${EPISODE}_unattended_$(date -u +%Y%m%dT%H%M%SZ).jsonl"
PROMPT="按 .claude/unattended_runner.md 推进 ${EPISODE}。先读它，再读 configs/ENGINEERING_KNOWLEDGE_V1.json 与 knowledge/failure_memory.jsonl。\
遇到不允许的动作或四类必须交线主的决定时，把待决说明写到 ${PENDING} 后结束。"

cd "$ENGINE_ROOT"
ARGS=(-p "$PROMPT" --permission-mode dontAsk --max-turns "$MAX_TURNS"
      --output-format stream-json --verbose
      --add-dir "$NALU_RUNTIME_ROOT"
      --append-system-prompt "$(cat "$ENGINE_ROOT/.claude/unattended_runner.md")")
[ -n "$MAX_BUDGET_USD" ] && ARGS+=(--max-budget-usd "$MAX_BUDGET_USD")

set +e
claude "${ARGS[@]}" > "$LOG" 2>&1
rc=$?
set -e
printf 'run_unattended: %s session ended rc=%s log=%s\n' "$EPISODE" "$rc" "$LOG"
[ -f "$PENDING" ] && { printf 'run_unattended: owner decision pending: %s\n' "$PENDING"; exit 5; }
exit "$rc"
