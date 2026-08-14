#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEDULER = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
sys.path.insert(0, "/Users/rogerwu/.local/share/backlotos/share/pipeline-tools")
from task_lane_state_store import commit_task_updates, read_scheduler_snapshot  # noqa: E402

PREVIOUS = "E40-U29C-V54-CHANGED-REPRESENTATION-AUTHORITY-TASK-LOCAL-REMOTE-WAIT"
CURRENT = "E40-U29C-V55-LOCAL-LIVING-REACTION-RENDER-AND-QA"
SUCCESSOR = "E40-U29C-V56-LOCAL-LIVING-REACTION-HUMAN-QA-TASK-LOCAL-REMOTE-WAIT"


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def strip_executor(task: dict) -> None:
    for key in (
        "execution_mode", "executor_handle", "executor_task_id",
        "executor_acknowledged_at", "executor_next_wakeup_at",
    ):
        task.pop(key, None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("register", "terminal-and-wait"))
    parser.add_argument("--evidence-ref", required=True)
    parser.add_argument("--evidence-sha256", required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    snapshot = read_scheduler_snapshot(SCHEDULER)
    tasks = {task["task_id"]: copy.deepcopy(task) for task in snapshot.payload["tasks"]}

    if args.action == "register":
        previous = tasks[PREVIOUS]
        if not (
            previous.get("state") == "REMOTE_WAIT"
            and previous.get("wait_scope") == "TASK_LOCAL"
            and previous.get("maximum_new_submissions") == 0
            and previous.get("authorization") is False
        ):
            raise SystemExit("V54 boundary is not the expected fail-closed REMOTE_WAIT")
        previous.update({
            "state": "TERMINAL",
            "wait_scope": "NONE_TERMINAL",
            "next_due_at": None,
            "completed_at": iso(now),
            "terminal_status": "EXPLICIT_USER_CONTINUE_DIRECTIVE_UNLOCKED_LOCAL_CHANGED_REPRESENTATION_ONLY",
            "progress": "HANDOFF_TO_ZERO_COST_LOCAL_V55_NO_PROVIDER_AUTHORITY",
            "blocked_by": None,
            "evidence_ref": args.evidence_ref,
            "evidence_sha256": args.evidence_sha256,
        })
        strip_executor(previous)
        current = {
            "task_id": CURRENT,
            "lane_id": "U29_VIDEO_QA",
            "state": "QA",
            "zero_cost": True,
            "deliverable_type": "LOCAL_LIVING_REACTION_RENDER_AND_MACHINE_QA",
            "priority": 141,
            "scope": [
                "E40", "U29C", "V55", "LOCAL_ONLY", "CHANGED_REPRESENTATION",
                "EXACT_START_FRAME", "NO_PROVIDER", "NO_SUBMIT", "NO_TRANSACTION",
                "NO_CREDITS", "NO_AGENTCUT", "NO_ASSEMBLY",
            ],
            "exact_predecessor_task_id": PREVIOUS,
            "liveness_role": "PRODUCING",
            "observation_only": False,
            "maximum_new_submissions": 0,
            "authorization": False,
            "provider_post_allowed": False,
            "provider_query_allowed": False,
            "download_allowed": False,
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
            "wait_scope": "NONE_ACTIVE_QA",
            "blocked_by": None,
            "progress": "REGISTERED_ZERO_COST_LOCAL_CHANGED_REPRESENTATION_RENDER_AND_QA",
            "last_progress_at": iso(now),
            "next_action": "Render the exact-frame local candidate and run machine/OCR/human QA without any provider action.",
            "lease_owner": "codex-e40-next-unit-audit:u29c-v55",
            "lease_expires_at": iso(now + timedelta(hours=2)),
            "next_due_at": iso(now + timedelta(minutes=20)),
            "execution_mode": "CONTINUOUS",
            "executor_handle": "agent:/root/e40_next_unit_audit",
            "executor_task_id": CURRENT,
            "executor_acknowledged_at": iso(now),
            "executor_next_wakeup_at": iso(now + timedelta(minutes=10)),
            "evidence_ref": args.evidence_ref,
            "evidence_sha256": args.evidence_sha256,
        }
        updates = {PREVIOUS: previous, CURRENT: current}
    else:
        current = tasks[CURRENT]
        if current.get("state") != "QA":
            raise SystemExit("V55 is not active QA")
        current.update({
            "state": "TERMINAL",
            "wait_scope": "NONE_TERMINAL",
            "next_due_at": None,
            "completed_at": iso(now),
            "terminal_status": "LOCAL_MACHINE_QA_PASS_HUMAN_QA_REQUIRED",
            "progress": "PASS_LOCAL_RENDER_AND_MACHINE_QA_NO_EDITORIAL_ADMISSION",
            "evidence_ref": args.evidence_ref,
            "evidence_sha256": args.evidence_sha256,
        })
        strip_executor(current)
        successor = {
            "task_id": SUCCESSOR,
            "lane_id": "U29_VIDEO_QA",
            "state": "REMOTE_WAIT",
            "zero_cost": True,
            "deliverable_type": "LOCAL_LIVING_REACTION_HUMAN_QA_TASK_LOCAL_REMOTE_WAIT",
            "priority": 142,
            "scope": ["E40", "U29C", "V56", "TASK_LOCAL", "HUMAN_QA", "NO_PROVIDER", "NO_SUBMIT"],
            "exact_predecessor_task_id": CURRENT,
            "liveness_role": "PRODUCING",
            "observation_only": False,
            "maximum_new_submissions": 0,
            "authorization": False,
            "provider_post_allowed": False,
            "provider_query_allowed": False,
            "download_allowed": False,
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
            "wait_scope": "TASK_LOCAL",
            "blocked_by": "ORIGINAL_RESOLUTION_HUMAN_QA_SCORE_GE_80_NOT_YET_RECORDED",
            "progress": "MACHINE_QA_PASS_WAITING_ORIGINAL_RESOLUTION_HUMAN_QA",
            "last_progress_at": iso(now),
            "next_action": "Review the local lossless candidate at original resolution; admit only with score >=80 and all hard gates pass.",
            "lease_owner": "codex-e40-next-unit-audit:u29c-v56",
            "lease_expires_at": iso(now + timedelta(hours=24)),
            "next_due_at": iso(now + timedelta(hours=12)),
            "execution_mode": "CONTINUOUS",
            "executor_handle": "agent:/root/e40_next_unit_audit",
            "executor_task_id": SUCCESSOR,
            "executor_acknowledged_at": iso(now),
            "executor_next_wakeup_at": iso(now + timedelta(hours=6)),
            "evidence_ref": args.evidence_ref,
            "evidence_sha256": args.evidence_sha256,
        }
        updates = {CURRENT: current, SUCCESSOR: successor}

    print(commit_task_updates(
        SCHEDULER,
        base_snapshot=snapshot,
        task_updates=updates,
        writer_id="codex-e40-next-unit-audit:u29c-v55-local-living",
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
