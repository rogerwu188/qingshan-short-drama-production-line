#!/bin/bash
# Review bridge between the release train (collector, private runtime) and the patrol (via the fleet service).
# Two independent slots (2026-11-20 global fast-track):
#   daily      status.open_review_request           -> $SHARED/review_request.json
#   fast-track status.open_fasttrack_review_request -> $SHARED/review_request_fasttrack.json
# For each slot: the open request, if any, is mirrored (removed when none is open); a result the fleet service
# stored at $SHARED/review_results/<request_id>.json (POST /v1/admin/collective/review, written by the patrol) is
# imported with `release_train.py import-review` and moved to $SHARED/review_results/done/.  A fast-track import
# publishes approved global rules to RELEASED inside import-review; one collector cycle then pushes the signed
# pointers to the bucket at once.
# Called at the end of collector_cycle.sh, collector_daily.sh and collector_fasttrack.sh.  Never fails the caller.
set -uo pipefail
OPT=/opt/nalu-collector
PY="$OPT/venv/bin/python"
ENGINE="$OPT/engine"
RUNTIME=/var/lib/nalu-collector
SHARED=/var/lib/nalu-fleet/collective
CFG=/etc/nalu-collector/release_train.json
STATUS="$SHARED/release_train_status.json"
cd "$ENGINE" || exit 0

status_field() {
  "$PY" -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get(sys.argv[2]) or "")
except Exception: print("")' "$STATUS" "$1"
}

refresh_status() {
  "$PY" tools/collective_learning/release_train.py status --runtime-root "$RUNTIME" --tenant nalu --config "$CFG" \
    --cohort "$SHARED/cohort.json" --status-out "$STATUS" >/dev/null 2>&1
}

# bridge_slot <status field> <mirror file> <push pointers after import: 0|1>
bridge_slot() {
  local field="$1" mirror="$2" push="$3" open_id req result
  open_id="$(status_field "$field")"
  if [ -z "$open_id" ]; then
    rm -f "$mirror"
    return 0
  fi
  req="$(find "$RUNTIME" -path "*/review_requests/$open_id.json" -print -quit 2>/dev/null)"
  if [ -n "$req" ]; then
    install -m 640 "$req" "$mirror.tmp" && mv -f "$mirror.tmp" "$mirror"
  fi
  result="$SHARED/review_results/$open_id.json"
  if [ -f "$result" ]; then
    mkdir -p "$SHARED/review_results/done"
    if "$PY" tools/collective_learning/release_train.py import-review --runtime-root "$RUNTIME" --tenant nalu \
         --config "$CFG" --result "$result" > "$SHARED/review_results/done/$open_id.import.json" 2>&1; then
      mv -f "$result" "$SHARED/review_results/done/$open_id.json"
      rm -f "$mirror"
      if [ "$push" = 1 ]; then
        "$PY" tools/collective_learning/s3_sync.py run-cycle --runtime-root "$RUNTIME" --tenant nalu --interval 300 \
          >/dev/null 2>&1
      fi
      refresh_status
    else
      mv -f "$result" "$SHARED/review_results/done/$open_id.rejected.json"
    fi
  fi
}

bridge_slot open_review_request "$SHARED/review_request.json" 0
bridge_slot open_fasttrack_review_request "$SHARED/review_request_fasttrack.json" 1
exit 0
