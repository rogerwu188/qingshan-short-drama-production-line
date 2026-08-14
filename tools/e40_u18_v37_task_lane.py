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

PREDECESSOR = "E40-U18-V36-REAL-ONE-TIME-ROOT-PERSISTENCE-AUTHORITY-TASK-LOCAL-REMOTE-WAIT"
TASK = "E40-U18-V37-AUTHORITY-CONSUMPTION-PREFLIGHT-QA"
SUCCESSOR = "E40-U18-V38-REAL-AUTHORITY-CONSUMPTION-TASK-LOCAL-REMOTE-WAIT"


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
            raise SystemExit("V36 is not the active REMOTE_WAIT predecessor")
        predecessor.update({
            "state": "TERMINAL", "wait_scope": "NONE_TERMINAL", "next_due_at": None,
            "completed_at": z(now), "terminal_status": "HANDOFF_TO_V37_AUTHORITY_CONSUMPTION_PREFLIGHT_QA",
        })
        strip_executor(predecessor)
        task = {
            "task_id": TASK, "lane_id": "U18_ISOLATED_ASSET_ACQUISITION", "state": "QA", "zero_cost": True,
            "deliverable_type": "AUTHORITY_CONSUMPTION_PREFLIGHT_QA", "priority": 207,
            "scope": ["E40", "U18", "V37", "LOCAL_ONLY", "SYNTHETIC_FIXTURES_ONLY", "NO_EXECUTION", "NO_NETWORK"],
            "exact_predecessor_task_id": PREDECESSOR, "liveness_role": "PRODUCING", "observation_only": False,
            "maximum_new_submissions": 0, "authorization": False, "provider_post_allowed": False,
            "provider_query_allowed": False, "download_allowed": False, "provider_calls": 0, "transactions": 0,
            "credits": 0, "wait_scope": "NONE_ACTIVE_QA", "progress": "REGISTERED_V37_AUTHORITY_CONSUMPTION_PREFLIGHT_QA",
            "last_progress_at": z(now), "next_action": "Compile/test read-only authority consumption preflight contract; never consume authority or write nonce/target.",
            "lease_owner": "codex-e40-next-unit-audit:u18-v37", "lease_expires_at": z(now + timedelta(hours=2)),
            "next_due_at": z(now + timedelta(minutes=20)), "execution_mode": "CONTINUOUS",
            "executor_handle": "agent:/root/e40_next_unit_audit", "executor_task_id": TASK,
            "executor_acknowledged_at": z(now), "executor_next_wakeup_at": z(now + timedelta(minutes=10)),
            "evidence_ref": args.evidence_ref, "evidence_sha256": args.evidence_sha256,
        }
        updates = {PREDECESSOR: predecessor, TASK: task}
    else:
        task = by_id[TASK]
        if task.get("state") != "QA":
            raise SystemExit("V37 is not active QA")
        task.update({
            "state": "TERMINAL", "wait_scope": "NONE_TERMINAL", "next_due_at": None,
            "completed_at": z(now), "terminal_status": "PASS_V37_AUTHORITY_CONSUMPTION_PREFLIGHT_NO_EXECUTION",
            "progress": "PASS_V37_COLLISION_RACE_STALE_AND_VALID_BRANCH_TESTS",
            "evidence_ref": args.evidence_ref, "evidence_sha256": args.evidence_sha256,
        })
        strip_executor(task)
        successor = {
            "task_id": SUCCESSOR, "lane_id": "U18_ISOLATED_ASSET_ACQUISITION", "state": "REMOTE_WAIT", "zero_cost": True,
            "deliverable_type": "REAL_AUTHORITY_CONSUMPTION_TASK_LOCAL_REMOTE_WAIT", "priority": 208,
            "scope": ["E40", "U18", "V38", "TASK_LOCAL", "OFFLINE_ONLY", "NO_WATCH", "NO_NETWORK"],
            "exact_predecessor_task_id": TASK, "liveness_role": "PRODUCING", "observation_only": False,
            "maximum_new_submissions": 0, "authorization": False, "provider_post_allowed": False,
            "provider_query_allowed": False, "download_allowed": False, "provider_calls": 0, "transactions": 0,
            "credits": 0, "wait_scope": "TASK_LOCAL",
            "blocked_by": "REAL_V35_VALID_AUTHORITY_DOCUMENT_AND_DISTINCT_SECOND_LOCAL_WITNESS_NOT_PRESENT",
            "progress": "V37_PREFLIGHT_READY_WAITING_REAL_EXACT_AUTHORITY_AND_DISTINCT_LOCAL_WITNESS",
            "last_progress_at": z(now),
            "next_action": "Wake only on an exact real V35-valid authority document and distinct local preflight witness; no watch, writes, consumption, nonce registration, or target action.",
            "lease_owner": "codex-e40-next-unit-audit:u18-v38", "lease_expires_at": z(now + timedelta(hours=24)),
            "next_due_at": z(now + timedelta(hours=12)), "execution_mode": "CONTINUOUS",
            "executor_handle": "agent:/root/e40_next_unit_audit", "executor_task_id": SUCCESSOR,
            "executor_acknowledged_at": z(now), "executor_next_wakeup_at": z(now + timedelta(hours=6)),
            "evidence_ref": args.evidence_ref, "evidence_sha256": args.evidence_sha256,
        }
        updates = {TASK: task, SUCCESSOR: successor}

    print(commit_task_updates(STATE, base_snapshot=snapshot, task_updates=updates, writer_id="codex-e40-next-unit-audit:u18-v37"))


if __name__ == "__main__":
    main()
