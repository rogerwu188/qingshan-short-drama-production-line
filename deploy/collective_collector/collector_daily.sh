#!/bin/bash
# Once a day (nalu-collective-daily.timer): evaluate the canary pack (promote / roll back), retire rules that did
# not help, build today's pack from the reviewed backlog, export a new review request for the patrol, then run one
# collector cycle so the new pointers reach the bucket at once.
set -uo pipefail
OPT=/opt/nalu-collector
PY="$OPT/venv/bin/python"
ENGINE="$OPT/engine"
RUNTIME=/var/lib/nalu-collector
SHARED=/var/lib/nalu-fleet/collective
CFG=/etc/nalu-collector/release_train.json
cd "$ENGINE"
"$PY" tools/collective_learning/release_train.py daily --runtime-root "$RUNTIME" --tenant nalu --config "$CFG" \
  --cohort "$SHARED/cohort.json" --status-out "$SHARED/release_train_status.json" \
  > "$RUNTIME/runtime/collective/release_train_daily.last.json"
"$PY" tools/collective_learning/s3_sync.py run-cycle --runtime-root "$RUNTIME" --tenant nalu --interval 300 >/dev/null
"$OPT/collector_review_bridge.sh"
