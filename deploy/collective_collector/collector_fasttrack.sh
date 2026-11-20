#!/bin/bash
# Hourly (nalu-collective-fasttrack.timer, 2026-11-20 global fast-track): safety valves for live fast-track rules
# (recurrence / regression auto-retire, always), then -- unless the kill switch is on -- publish approved rules still
# queued and export newly eligible FINAL_REVIEW:<kind>|global clusters as the fast-track review request (ft-...),
# then one collector cycle and the review bridge so the request reaches the patrol at once.
# Needs an engine checkout with `release_train.py fasttrack` (engine PR feat/kb-global-fasttrack).
# Kill switch: touch /var/lib/nalu-collector/runtime/collective/release_train/FASTTRACK_KILL
#              (or "fasttrack_enabled": false in /etc/nalu-collector/release_train.json).
set -uo pipefail
OPT=/opt/nalu-collector
PY="$OPT/venv/bin/python"
ENGINE="$OPT/engine"
RUNTIME=/var/lib/nalu-collector
SHARED=/var/lib/nalu-fleet/collective
CFG=/etc/nalu-collector/release_train.json
cd "$ENGINE"
"$PY" tools/collective_learning/release_train.py fasttrack --runtime-root "$RUNTIME" --tenant nalu --config "$CFG" \
  --cohort "$SHARED/cohort.json" --status-out "$SHARED/release_train_status.json" \
  > "$RUNTIME/runtime/collective/release_train_fasttrack.last.json"
rc=$?
"$PY" tools/collective_learning/s3_sync.py run-cycle --runtime-root "$RUNTIME" --tenant nalu --interval 300 >/dev/null
"$OPT/collector_review_bridge.sh"
exit $rc
