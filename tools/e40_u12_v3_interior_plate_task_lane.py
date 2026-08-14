#!/usr/bin/env python3
"""CAS-register and close the E40 U12 V3 interior plate exactly-one image lane."""

from __future__ import annotations

import argparse
import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
sys.path.insert(0, "/Users/rogerwu/.local/share/backlotos/share/pipeline-tools")
from task_lane_state_store import commit_task_updates, read_scheduler_snapshot  # noqa: E402

TASK_ID = "E40-U12-V3-INTERIOR-DESK-MOUTH-ABSENT-PLATE-EXACTLY-ONE-IMAGE"


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("register", "renew", "terminal"))
    parser.add_argument("--progress", required=True)
    parser.add_argument("--evidence-ref")
    parser.add_argument("--evidence-sha256")
    parser.add_argument("--terminal-status")
    parser.add_argument("--blocked-by")
    parser.add_argument("--next-action")
    parser.add_argument("--provider-task-id")
    parser.add_argument("--authorization-active", action="store_true")
    parser.add_argument("--submission-consumed", action="store_true")
    parser.add_argument("--task-local", action="store_true")
    parser.add_argument("--wait-scope")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    snapshot = read_scheduler_snapshot(STATE)
    current = next((copy.deepcopy(row) for row in snapshot.payload.get("tasks", []) if row.get("task_id") == TASK_ID), None)
    if current is None:
        if args.action != "register":
            raise SystemExit("V3 interior plate task is not registered")
        current = {
            "task_id": TASK_ID,
            "lane_id": "IMAGE_ASSET",
            "state": "RUNNING",
            "zero_cost": False,
            "deliverable_type": "EXACTLY_ONE_INTERIOR_DESK_MOUTH_ABSENT_SOURCE_PLATE_AND_QA",
            "priority": 100,
            "scope": ["E40", "U12", "INTERIOR_DESK", "MOUTH_ABSENT", "EXACTLY_ONE_IMAGE", "NO_VIDEO"],
            "exact_predecessor_task_id": "E40-U12-V2-CHANGED-REPRESENTATION-DETERMINISTIC-PAPER-TRANSFER-REMEDIATION",
            "liveness_role": "PRODUCING",
            "observation_only": False,
            "maximum_new_submissions": 1,
            "authorization": False,
        }
    elif args.action == "register":
        raise SystemExit(f"refusing duplicate register: {current.get('state')}")
    current.update({
        "progress": args.progress,
        "last_progress_at": stamp(now),
        "next_action": args.next_action or current.get("next_action"),
    })
    if args.provider_task_id:
        current["provider_task_id"] = args.provider_task_id
    if args.authorization_active:
        current["authorization"] = True
        current["maximum_new_submissions"] = 1
        current["submission_consumed"] = False
    if args.submission_consumed:
        current["authorization"] = False
        current["maximum_new_submissions"] = 0
        current["submission_consumed"] = True
        current["submitter_reentry"] = "FORBIDDEN_DURABLE_TASK_ID_ALREADY_BOUND"
    if args.task_local:
        current["liveness_role"] = "TASK_LOCAL"
        current["observation_only"] = False
    if args.wait_scope:
        current["wait_scope"] = args.wait_scope
    if args.action in {"register", "renew"}:
        current.update({
            "state": "RUNNING",
            "liveness_role": current.get("liveness_role", "PRODUCING"),
            "lease_owner": "codex-e40-u12:v3-interior-mouth-absent-plate",
            "lease_expires_at": stamp(now + timedelta(hours=2)),
            "next_due_at": stamp(now + timedelta(minutes=10)),
        })
    else:
        if not args.evidence_ref or not args.evidence_sha256 or not args.terminal_status:
            raise SystemExit("terminal requires evidence ref/SHA and terminal status")
        current.update({
            "state": "TERMINAL",
            "next_due_at": None,
            "maximum_new_submissions": 0,
            "authorization": False,
            "completed_at": stamp(now),
            "terminal_status": args.terminal_status,
            "evidence_ref": args.evidence_ref,
            "evidence_sha256": args.evidence_sha256,
            "blocked_by": args.blocked_by,
        })
    result = commit_task_updates(
        STATE,
        base_snapshot=snapshot,
        task_updates={TASK_ID: current},
        writer_id="codex-e40-u12:v3-interior-mouth-absent-plate",
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
