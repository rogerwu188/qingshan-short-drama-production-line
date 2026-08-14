#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
sys.path.insert(0, "/Users/rogerwu/.local/share/backlotos/share/pipeline-tools")

from task_lane_state_store import commit_task_updates, read_scheduler_snapshot  # noqa: E402

TASK_ID = "E40-U18-V44-NEW-VERSION-AND-PER-BUNDLE-AUTHORITY-TASK-LOCAL-REMOTE-WAIT"


def utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> None:
    now = datetime.now(timezone.utc)
    snapshot = read_scheduler_snapshot(STATE)
    task = copy.deepcopy(next(row for row in snapshot.payload["tasks"] if row["task_id"] == TASK_ID))
    required = (
        task.get("state") == "REMOTE_WAIT"
        and task.get("wait_scope") == "TASK_LOCAL"
        and task.get("maximum_new_submissions") == 0
        and task.get("authorization") is False
        and task.get("provider_post_allowed") is False
        and task.get("provider_query_allowed") is False
        and task.get("download_allowed") is False
        and task.get("executor_handle") == "agent:/root/e40_next_unit_audit"
        and task.get("blocked_by")
        == "NEW_VERSION_SHA_INDEPENDENT_SECURITY_AUDIT_AND_FRESH_PER_BUNDLE_AUTHORITY_NOT_PRESENT"
    )
    if not required:
        raise SystemExit("FAIL_CLOSED_U18_V44_BOUNDARY_DRIFT")
    task.update(
        {
            "lease_expires_at": utc(now + timedelta(hours=24)),
            "last_progress_at": utc(now),
            "next_due_at": utc(now + timedelta(hours=12)),
            "executor_acknowledged_at": utc(now),
            "executor_next_wakeup_at": utc(now + timedelta(hours=6)),
        }
    )
    print(
        commit_task_updates(
            STATE,
            base_snapshot=snapshot,
            task_updates={TASK_ID: task},
            writer_id="codex-e40-next-unit-audit:u18-v44-continuity-renew",
        )
    )


if __name__ == "__main__":
    main()
