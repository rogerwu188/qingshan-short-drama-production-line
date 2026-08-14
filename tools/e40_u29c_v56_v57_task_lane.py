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

PREVIOUS = "E40-U29C-V56-LOCAL-LIVING-REACTION-HUMAN-QA-TASK-LOCAL-REMOTE-WAIT"
CURRENT = "E40-U29C-V57-ARTICULATED-HEAD-CHANGED-REPRESENTATION-DESIGN-AND-TESTS"


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
    parser.add_argument("--human-qa-ref", required=True)
    parser.add_argument("--human-qa-sha256", required=True)
    parser.add_argument("--failure-memory-ref", required=True)
    parser.add_argument("--failure-memory-sha256", required=True)
    parser.add_argument("--spec-ref", required=True)
    parser.add_argument("--spec-sha256", required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    snapshot = read_scheduler_snapshot(SCHEDULER)
    tasks = {task["task_id"]: copy.deepcopy(task) for task in snapshot.payload["tasks"]}
    previous = tasks[PREVIOUS]
    if not (
        previous.get("state") == "REMOTE_WAIT"
        and previous.get("wait_scope") == "TASK_LOCAL"
        and previous.get("maximum_new_submissions") == 0
        and previous.get("authorization") is False
    ):
        raise SystemExit("V56 is not the expected fail-closed human-QA wait")
    previous.update({
        "state": "TERMINAL",
        "wait_scope": "NONE_TERMINAL",
        "next_due_at": None,
        "completed_at": iso(now),
        "terminal_status": "FAIL_78_OF_80_AUTHORED_HEAD_TURN_HARD_GATE",
        "progress": "HUMAN_QA_FAIL_FAILURE_MEMORY_PERSISTED_UNCHANGED_RETRY_FORBIDDEN",
        "blocked_by": "AUTHORED_HEAD_TURNS_ABSENT",
        "evidence_ref": args.human_qa_ref,
        "evidence_sha256": args.human_qa_sha256,
        "failure_memory_ref": args.failure_memory_ref,
        "failure_memory_sha256": args.failure_memory_sha256,
    })
    strip_executor(previous)
    current = {
        "task_id": CURRENT,
        "lane_id": "U29_VIDEO_QA",
        "state": "QA",
        "zero_cost": True,
        "deliverable_type": "ARTICULATED_HEAD_CHANGED_REPRESENTATION_DESIGN_AND_NEGATIVE_TESTS",
        "priority": 143,
        "scope": [
            "E40", "U29C", "V57", "LOCAL_ONLY", "DESIGN", "NEGATIVE_TESTS",
            "NO_RENDER", "NO_PROVIDER", "NO_SUBMIT", "NO_TRANSACTION", "NO_CREDITS",
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
        "progress": "REGISTERED_MATERIALLY_CHANGED_ARTICULATED_HEAD_DESIGN_AND_TESTS",
        "last_progress_at": iso(now),
        "next_action": "Implement local articulated-head renderer and closed-set negative tests; do not render until zero-render precheck passes.",
        "lease_owner": "codex-e40-next-unit-audit:u29c-v57",
        "lease_expires_at": iso(now + timedelta(hours=2)),
        "next_due_at": iso(now + timedelta(minutes=20)),
        "execution_mode": "CONTINUOUS",
        "executor_handle": "agent:/root/e40_next_unit_audit",
        "executor_task_id": CURRENT,
        "executor_acknowledged_at": iso(now),
        "executor_next_wakeup_at": iso(now + timedelta(minutes=10)),
        "evidence_ref": args.spec_ref,
        "evidence_sha256": args.spec_sha256,
        "failure_memory_ref": args.failure_memory_ref,
        "failure_memory_sha256": args.failure_memory_sha256,
    }
    print(commit_task_updates(
        SCHEDULER,
        base_snapshot=snapshot,
        task_updates={PREVIOUS: previous, CURRENT: current},
        writer_id="codex-e40-next-unit-audit:u29c-v56-v57",
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
