#!/usr/bin/env python3
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

PREDECESSOR = "E40-U18-V38-REAL-AUTHORITY-CONSUMPTION-TASK-LOCAL-REMOTE-WAIT"
TASK = "E40-U18-V39-EXECUTOR-INCAPABILITY-AUDIT-QA"
SUCCESSOR = "E40-U18-V40-INDEPENDENT-AUTHORIZED-EXECUTOR-TASK-LOCAL-REMOTE-WAIT"


def z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def strip_executor(task: dict) -> None:
    for key in ("execution_mode", "executor_handle", "executor_task_id", "executor_acknowledged_at", "executor_next_wakeup_at"):
        task.pop(key, None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["register", "terminal-and-wait"])
    parser.add_argument("--evidence-ref", required=True)
    parser.add_argument("--evidence-sha256", required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    snapshot = read_scheduler_snapshot(STATE)
    by_id = {item["task_id"]: copy.deepcopy(item) for item in snapshot.payload["tasks"]}
    if args.action == "register":
        predecessor = by_id[PREDECESSOR]
        if predecessor.get("state") != "REMOTE_WAIT":
            raise SystemExit("V38 is not active REMOTE_WAIT")
        predecessor.update({"state": "TERMINAL", "wait_scope": "NONE_TERMINAL", "next_due_at": None, "completed_at": z(now), "terminal_status": "HANDOFF_TO_V39_EXECUTOR_INCAPABILITY_AUDIT_QA"})
        strip_executor(predecessor)
        task = {
            "task_id": TASK, "lane_id": "U18_ISOLATED_ASSET_ACQUISITION", "state": "QA", "zero_cost": True,
            "deliverable_type": "EXECUTOR_INCAPABILITY_AUDIT_QA", "priority": 209,
            "scope": ["E40", "U18", "V39", "LOCAL_ONLY", "STATIC_AND_MONKEYPATCH_AUDIT", "NO_EXECUTOR_IMPLEMENTATION", "NO_EXECUTION", "NO_NETWORK"],
            "exact_predecessor_task_id": PREDECESSOR, "liveness_role": "PRODUCING", "observation_only": False,
            "maximum_new_submissions": 0, "authorization": False, "provider_post_allowed": False, "provider_query_allowed": False,
            "download_allowed": False, "provider_calls": 0, "transactions": 0, "credits": 0, "wait_scope": "NONE_ACTIVE_QA",
            "progress": "REGISTERED_V39_EXECUTOR_INCAPABILITY_AUDIT_QA", "last_progress_at": z(now),
            "next_action": "Statically and dynamically prove V31/V35/V37 core entrypoints lack execution/write/network capability; specify but do not implement a future independent executor.",
            "lease_owner": "codex-e40-next-unit-audit:u18-v39", "lease_expires_at": z(now + timedelta(hours=2)),
            "next_due_at": z(now + timedelta(minutes=20)), "execution_mode": "CONTINUOUS", "executor_handle": "agent:/root/e40_next_unit_audit",
            "executor_task_id": TASK, "executor_acknowledged_at": z(now), "executor_next_wakeup_at": z(now + timedelta(minutes=10)),
            "evidence_ref": args.evidence_ref, "evidence_sha256": args.evidence_sha256,
        }
        updates = {PREDECESSOR: predecessor, TASK: task}
    else:
        task = by_id[TASK]
        if task.get("state") != "QA":
            raise SystemExit("V39 is not active QA")
        task.update({"state": "TERMINAL", "wait_scope": "NONE_TERMINAL", "next_due_at": None, "completed_at": z(now),
                     "terminal_status": "CAPABILITY_SEPARATION_PASS_NO_EXECUTION", "progress": "PASS_V39_STATIC_ALLOWLIST_AND_WRITE_DENIAL_TESTS",
                     "evidence_ref": args.evidence_ref, "evidence_sha256": args.evidence_sha256})
        strip_executor(task)
        successor = {
            "task_id": SUCCESSOR, "lane_id": "U18_ISOLATED_ASSET_ACQUISITION", "state": "REMOTE_WAIT", "zero_cost": True,
            "deliverable_type": "INDEPENDENT_AUTHORIZED_EXECUTOR_TASK_LOCAL_REMOTE_WAIT", "priority": 210,
            "scope": ["E40", "U18", "V40", "TASK_LOCAL", "OFFLINE_ONLY", "NO_WATCH", "NO_NETWORK", "NO_EXECUTOR_PRESENT"],
            "exact_predecessor_task_id": TASK, "liveness_role": "PRODUCING", "observation_only": False,
            "maximum_new_submissions": 0, "authorization": False, "provider_post_allowed": False, "provider_query_allowed": False,
            "download_allowed": False, "provider_calls": 0, "transactions": 0, "credits": 0, "wait_scope": "TASK_LOCAL",
            "blocked_by": "INDEPENDENT_EXECUTOR_NOT_IMPLEMENTED_AND_REAL_EXACT_AUTHORITY_WITNESS_NOT_PRESENT",
            "progress": "V39_CAPABILITY_SEPARATION_PROVED_WAITING_SEPARATE_FUTURE_AUTHORIZED_EXECUTOR",
            "last_progress_at": z(now), "next_action": "Wake only on explicit authority to implement a separate executor plus exact real V35/V37 inputs; current verifier/dry-run tools remain incapable of writes.",
            "lease_owner": "codex-e40-next-unit-audit:u18-v40", "lease_expires_at": z(now + timedelta(hours=24)),
            "next_due_at": z(now + timedelta(hours=12)), "execution_mode": "CONTINUOUS", "executor_handle": "agent:/root/e40_next_unit_audit",
            "executor_task_id": SUCCESSOR, "executor_acknowledged_at": z(now), "executor_next_wakeup_at": z(now + timedelta(hours=6)),
            "evidence_ref": args.evidence_ref, "evidence_sha256": args.evidence_sha256,
        }
        updates = {TASK: task, SUCCESSOR: successor}
    print(commit_task_updates(STATE, base_snapshot=snapshot, task_updates=updates, writer_id="codex-e40-next-unit-audit:u18-v39"))


if __name__ == "__main__":
    main()
