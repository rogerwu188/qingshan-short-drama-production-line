#!/bin/bash
# Review bridge between the release train (collector, private runtime) and the patrol (via the fleet service):
#   * the open review request, if any, is mirrored to $SHARED/review_request.json (removed when none is open);
#   * a result the fleet service stored at $SHARED/review_results/<request_id>.json (POST
#     /v1/admin/collective/review, written by the patrol) is imported with `release_train.py import-review`
#     and moved to $SHARED/review_results/done/.
# Called at the end of collector_cycle.sh and collector_daily.sh.  Never fails the caller.
set -uo pipefail
OPT=/opt/nalu-collector
PY="$OPT/venv/bin/python"
ENGINE="$OPT/engine"
RUNTIME=/var/lib/nalu-collector
SHARED=/var/lib/nalu-fleet/collective
CFG=/etc/nalu-collector/release_train.json
STATUS="$SHARED/release_train_status.json"
cd "$ENGINE" || exit 0
open_id="$("$PY" -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("open_review_request") or "")
except Exception: print("")' "$STATUS")"
if [ -z "$open_id" ]; then
  rm -f "$SHARED/review_request.json"
  exit 0
fi
req="$(find "$RUNTIME" -path "*/review_requests/$open_id.json" -print -quit 2>/dev/null)"
if [ -n "$req" ]; then
  install -m 640 "$req" "$SHARED/review_request.json.tmp" && mv -f "$SHARED/review_request.json.tmp" "$SHARED/review_request.json"
fi
result="$SHARED/review_results/$open_id.json"
if [ -f "$result" ]; then
  mkdir -p "$SHARED/review_results/done"
  if "$PY" tools/collective_learning/release_train.py import-review --runtime-root "$RUNTIME" --tenant nalu \
       --config "$CFG" --result "$result" > "$SHARED/review_results/done/$open_id.import.json" 2>&1; then
    mv -f "$result" "$SHARED/review_results/done/$open_id.json"
    rm -f "$SHARED/review_request.json"
    "$PY" tools/collective_learning/release_train.py status --runtime-root "$RUNTIME" --tenant nalu --config "$CFG" \
      --cohort "$SHARED/cohort.json" --status-out "$STATUS" >/dev/null 2>&1
  else
    mv -f "$result" "$SHARED/review_results/done/$open_id.rejected.json"
  fi
fi
exit 0
