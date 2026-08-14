#!/usr/bin/env python3
"""CAS-register and close E40 U12's exactly-one Fast720 silent visual lane."""

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

TASK_ID = "E40-U12-MOUTH-NONVISIBLE-FAST720-SILENT-VISUAL-EXACTLY-ONE"


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
    parser.add_argument("--submission-consumed", action="store_true")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    snapshot = read_scheduler_snapshot(STATE)
    current = next((copy.deepcopy(row) for row in snapshot.payload.get("tasks", []) if row.get("task_id") == TASK_ID), None)
    if current is None:
        if args.action != "register":
            raise SystemExit("silent visual task is not registered")
        current = {
            "task_id": TASK_ID,
            "lane_id": "VIDEO_PRODUCTION",
            "state": "RUNNING",
            "zero_cost": False,
            "deliverable_type": "EXACTLY_ONE_FAST720_MOUTH_NONVISIBLE_SILENT_VISUAL_AND_QA",
            "priority": 100,
            "scope": ["E40", "U12", "MOUTH_NONVISIBLE", "SEEDANCE_2_0_FAST", "720P", "SILENT", "EXACTLY_ONCE"],
            "exact_predecessor_task_id": "E40-U12-DIA010-EXACTLY-ONE-TTS-EXECUTION",
            "liveness_role": "PRODUCING",
            "observation_only": False,
            "maximum_new_submissions": 1,
            "authorization": True,
        }
    elif args.action == "register":
        raise SystemExit(f"refusing duplicate register: {current.get('state')}")
    current.update({"progress": args.progress, "last_progress_at": stamp(now), "next_action": args.next_action or current.get("next_action")})
    if args.provider_task_id:
        current["provider_task_id"] = args.provider_task_id
    if args.submission_consumed:
        current["authorization"] = False
        current["maximum_new_submissions"] = 0
        current["submission_consumed"] = True
    if args.action in {"register", "renew"}:
        current.update({
            "state": "RUNNING",
            "liveness_role": "PRODUCING",
            "lease_owner": "codex-e40-u12:mouth-nonvisible-fast720-silent-visual",
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
        writer_id="codex-e40-u12:mouth-nonvisible-fast720-silent-visual",
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
