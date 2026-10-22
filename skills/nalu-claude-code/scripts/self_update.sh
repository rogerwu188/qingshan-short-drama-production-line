#!/usr/bin/env bash
# self_update.sh — keep the OpenClaw agent on its latest published TalentHub version, unattended.
#
# Run by the agent on every wake-up, after setup_host.sh returned READY:
#   self_update.sh --agent-id qingshan-ai-drama-factory-minipc [--restart]
# * an episode in flight (the executor running, or its last NALU_STATUS is neither FINAL_CUT_READY nor BLOCKED) -> no change;
# * otherwise `talenthub agent list` (registry catalog, cached by talenthub for up to 1 h); when this agent
#   shows "Update available", `talenthub agent update <id>` rewrites its instruction files and refreshes
#   its skills.  The new instructions apply from the next session; with --restart the OpenClaw gateway is
#   restarted 30 s later in the background so the current reply can finish first.
# Ends with ONE line:  SELF_UPDATE: {"status":"UP_TO_DATE|UPDATED|DEFERRED_IN_FLIGHT|SKIPPED|ERROR", ...}
set -uo pipefail
AGENT=""; RESTART=0
while [ $# -gt 0 ]; do
  case "$1" in
    --agent-id) AGENT="$2"; shift 2 ;;
    --restart) RESTART=1; shift ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac
done
say() { printf 'SELF_UPDATE: {"status":"%s","agent":"%s","detail":"%s"}\n' "$1" "$AGENT" "${2//\"/\'}"; }
[ -n "$AGENT" ] || { say ERROR "--agent-id is required"; exit 2; }
export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"
S="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="${NALU_RUNTIME_ROOT:-$HOME/nalu_runtime}"
LOG="$HOME/.nalu_self_update.log"

busy="$(python3 - "$RUNTIME" "$S" <<'PY' 2>/dev/null
import json, sys
from pathlib import Path
runtime, scripts = Path(sys.argv[1]), sys.argv[2]
sys.path.insert(0, scripts)
import claude_production as cp
out = []
for session in sorted((runtime / "claude_code").glob("*/session.json")):
    s = json.loads(session.read_text(encoding="utf-8"))
    state = ((cp.parse_log(Path(s.get("log") or "")).get("nalu_status")) or {}).get("state")
    # a stopped BLOCKED episode is waiting for a fix (often this very update), not in flight; neither is
    # a run whose executor is gone without ever printing NALU_STATUS (killed or crashed) -- same rule as
    # setup_host.sh (#110), else the update that fixes the episode can never install
    if cp.alive(s.get("pid")) or (state is not None and state not in ("FINAL_CUT_READY", "BLOCKED")):
        out.append(session.parent.name)
print(",".join(out))
PY
)"
if [ -n "$busy" ]; then say DEFERRED_IN_FLIGHT "episode in flight: $busy"; exit 0; fi
command -v talenthub >/dev/null || { say SKIPPED "talenthub CLI not on PATH"; exit 0; }

row="$(talenthub agent list 2>>"$LOG" | grep -E "^[[:space:]]*$AGENT[[:space:]]" | head -1)"
[ -n "$row" ] || { say SKIPPED "agent not installed via talenthub on this host"; exit 0; }
case "$row" in
  *"Update available"*) ;;
  *) say UP_TO_DATE "$(printf '%s' "$row" | tr -s ' ' | sed 's/^ //')"; exit 0 ;;
esac
latest="$(printf '%s' "$row" | sed -n 's/.*Update available (\(.*\)).*/\1/p')"
printf '[%s] updating %s -> %s\n' "$(date -u +%FT%TZ)" "$AGENT" "$latest" >>"$LOG"
if ! talenthub agent update "$AGENT" >>"$LOG" 2>&1; then say ERROR "talenthub agent update failed; see $LOG"; exit 3; fi
if [ $RESTART = 1 ] && command -v openclaw >/dev/null; then
  nohup sh -c 'sleep 30; openclaw gateway restart' >>"$LOG" 2>&1 &
  say UPDATED "updated to $latest; gateway restart scheduled in 30 s"
else
  say UPDATED "updated to $latest; new instructions apply from the next session"
fi
