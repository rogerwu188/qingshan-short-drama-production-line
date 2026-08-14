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

PREVIOUS = "E40-U29C-V57-ARTICULATED-HEAD-CHANGED-REPRESENTATION-DESIGN-AND-TESTS"
CURRENT = "E40-U29C-V58-ARTICULATED-HEAD-LOCAL-RENDER-AND-QA"


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
    parser.add_argument("--evidence-ref", required=True)
    parser.add_argument("--evidence-sha256", required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    snapshot = read_scheduler_snapshot(SCHEDULER)
    tasks = {task["task_id"]: copy.deepcopy(task) for task in snapshot.payload["tasks"]}
    previous = tasks[PREVIOUS]
    if previous.get("state") != "QA" or previous.get("maximum_new_submissions") != 0:
        raise SystemExit("V57 is not active fail-closed QA")
    previous.update({
        "state": "TERMINAL",
        "wait_scope": "NONE_TERMINAL",
        "next_due_at": None,
        "completed_at": iso(now),
        "terminal_status": "PASS_ZERO_VIDEO_PRECHECK_RENDER_V58_MAY_BE_REGISTERED",
        "progress": "PASS_DESIGN_AND_5_OF_5_NEGATIVE_TESTS_NO_VIDEO_WRITTEN",
        "evidence_ref": args.evidence_ref,
        "evidence_sha256": args.evidence_sha256,
    })
    strip_executor(previous)
    current = {
        "task_id": CURRENT,
        "lane_id": "U29_VIDEO_QA",
        "state": "RUNNING",
        "zero_cost": True,
        "deliverable_type": "ARTICULATED_HEAD_LOCAL_RENDER_AND_QA",
        "priority": 144,
        "scope": [
            "E40", "U29C", "V58", "LOCAL_ONLY", "RENDER", "MACHINE_QA",
            "NO_PROVIDER", "NO_SUBMIT", "NO_TRANSACTION", "NO_CREDITS",
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
        "wait_scope": "NONE_ACTIVE_RUNNING",
        "blocked_by": None,
        "progress": "REGISTERED_V58_LOCAL_RENDER_AFTER_ZERO_VIDEO_PRECHECK_PASS",
        "last_progress_at": iso(now),
        "next_action": "Render exactly one zero-credit local V58 candidate, then run exact-frame/audio/anchor/OCR/determinism and human QA.",
        "lease_owner": "codex-e40-next-unit-audit:u29c-v58",
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
    print(commit_task_updates(
        SCHEDULER,
        base_snapshot=snapshot,
        task_updates={PREVIOUS: previous, CURRENT: current},
        writer_id="codex-e40-next-unit-audit:u29c-v57-v58",
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
