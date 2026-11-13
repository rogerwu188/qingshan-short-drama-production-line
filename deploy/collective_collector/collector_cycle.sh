#!/bin/bash
# Every 5 minutes (nalu-collective-cycle.timer): allow-list the fleet cohort, ingest the inbox, reconcile the
# signed channel pointers / revocation list (through the release gate), refresh the dashboard status file.
# Fails closed: without runtime/collective/env, run-cycle records CREDENTIALS_MISSING and touches no network.
set -uo pipefail
OPT=/opt/nalu-collector
PY="$OPT/venv/bin/python"
ENGINE="$OPT/engine"
RUNTIME=/var/lib/nalu-collector
SHARED=/var/lib/nalu-fleet/collective
CFG=/etc/nalu-collector/release_train.json
cd "$ENGINE"
"$PY" tools/collective_learning/release_train.py register-cohort --runtime-root "$RUNTIME" --tenant nalu \
  --config "$CFG" --cohort "$SHARED/cohort.json" >/dev/null
"$PY" tools/collective_learning/s3_sync.py run-cycle --runtime-root "$RUNTIME" --tenant nalu --interval 300 >/dev/null
rc=$?
"$PY" tools/collective_learning/release_train.py status --runtime-root "$RUNTIME" --tenant nalu \
  --config "$CFG" --cohort "$SHARED/cohort.json" --status-out "$SHARED/release_train_status.json" >/dev/null
"$OPT/collector_review_bridge.sh"
exit $rc
