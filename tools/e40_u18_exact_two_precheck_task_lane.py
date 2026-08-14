#!/usr/bin/env python3
"""CAS-register/close the local-only U18 exact-two image precheck lane."""

from __future__ import annotations

import argparse
import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
STORE = Path("/Users/rogerwu/.local/share/backlotos/share/pipeline-tools")
sys.path.insert(0, str(STORE))
from task_lane_state_store import commit_task_updates, read_scheduler_snapshot  # noqa: E402

TASK_ID = "E40-U18-V2-EXACT-TWO-ISOLATED-ASSET-EXECUTION-PRECHECK-NO-SUBMIT"
WAIT_TASK_ID = "E40-U18-V3-EXACT-TWO-ROOT-AUTHORIZATION-TASK-LOCAL-REMOTE-WAIT"


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("register", "renew", "terminal", "terminal-and-wait"))
    parser.add_argument("--progress", required=True)
    parser.add_argument("--evidence-ref")
    parser.add_argument("--evidence-sha256")
    parser.add_argument("--terminal-status")
    parser.add_argument("--blocked-by")
    parser.add_argument("--next-action")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    snapshot = read_scheduler_snapshot(STATE)
    row = next((copy.deepcopy(x) for x in snapshot.payload["tasks"] if x.get("task_id") == TASK_ID), None)
    if row is None:
        if args.action != "register":
            raise SystemExit(f"{TASK_ID} is not registered")
        row = {
            "task_id": TASK_ID,
            "lane_id": "U18_ISOLATED_ASSET_ACQUISITION",
            "state": "QA",
            "zero_cost": True,
            "deliverable_type": "EXACT_TWO_IMAGE_EXECUTION_PRECHECK_NO_SUBMIT",
            "priority": 174,
            "scope": ["E40", "U18", "EXACT_TWO", "IMAGE_PREFLIGHT", "NO_PROVIDER", "NO_TRANSACTION", "NO_CREDITS"],
            "exact_predecessor_task_id": "E40-A01-RETRY-STRATEGY-AUDIT-V1",
            "liveness_role": "PRODUCING",
            "observation_only": False,
            "maximum_new_submissions": 0,
            "authorization": False,
            "provider_post_allowed": False,
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
            "wait_scope": "NONE_ACTIVE_QA",
        }
    elif args.action == "register" and row.get("state") != "TERMINAL":
        raise SystemExit(f"refusing duplicate register: {row.get('state')}")
    row.update({"progress": args.progress, "last_progress_at": stamp(now), "next_action": args.next_action or row.get("next_action")})
    if args.action in {"register", "renew"}:
        row.update({
            "state": "QA",
            "lease_owner": "codex-e40-next-unit-audit:u18-exact-two-precheck",
            "lease_expires_at": stamp(now + timedelta(hours=2)),
            "next_due_at": stamp(now + timedelta(minutes=20)),
            "execution_mode": "CONTINUOUS",
            "executor_handle": "agent:/root/e40_next_unit_audit",
            "executor_task_id": TASK_ID,
            "executor_acknowledged_at": stamp(now),
            "executor_next_wakeup_at": stamp(now + timedelta(minutes=10)),
        })
    else:
        if not args.evidence_ref or not args.evidence_sha256 or not args.terminal_status:
            raise SystemExit("terminal requires evidence ref/SHA and terminal status")
        row.update({
            "state": "TERMINAL",
            "next_due_at": None,
            "maximum_new_submissions": 0,
            "authorization": False,
            "provider_post_allowed": False,
            "completed_at": stamp(now),
            "terminal_status": args.terminal_status,
            "evidence_ref": args.evidence_ref,
            "evidence_sha256": args.evidence_sha256,
            "blocked_by": args.blocked_by,
        })
        for key in ("execution_mode", "executor_handle", "executor_task_id", "executor_acknowledged_at", "executor_next_wakeup_at"):
            row.pop(key, None)
    updates = {TASK_ID: row}
    if args.action == "terminal-and-wait":
        updates[WAIT_TASK_ID] = {
            "task_id": WAIT_TASK_ID,
            "lane_id": "U18_ISOLATED_ASSET_ACQUISITION",
            "state": "REMOTE_WAIT",
            "zero_cost": True,
            "deliverable_type": "EXACT_TWO_ROOT_AUTHORIZATION_TASK_LOCAL_REMOTE_WAIT",
            "priority": 175,
            "scope": ["E40", "U18", "EXACT_TWO", "ROOT_AUTHORIZATION", "TASK_LOCAL", "NO_PROVIDER", "NO_TRANSACTION", "NO_CREDITS"],
            "exact_predecessor_task_id": TASK_ID,
            "liveness_role": "PRODUCING",
            "observation_only": False,
            "maximum_new_submissions": 0,
            "authorization": False,
            "provider_post_allowed": False,
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
            "wait_scope": "TASK_LOCAL",
            "blocked_by": "SEPARATE_ROOT_EXACT_TWO_IMMUTABLE_AUTHORIZATION_MISSING",
            "progress": "PREFLIGHT_PASS_WAITING_SEPARATE_ROOT_EXACT_TWO_AUTHORIZATION",
            "last_progress_at": stamp(now),
            "next_action": "Wake only on a separate immutable root exact-two authorization; rerun fresh price, cap and uniqueness before any execution.",
            "lease_owner": "codex-e40-next-unit-audit:u18-exact-two-root-wait",
            "lease_expires_at": stamp(now + timedelta(hours=24)),
            "next_due_at": stamp(now + timedelta(hours=12)),
            "execution_mode": "CONTINUOUS",
            "executor_handle": "agent:/root/e40_next_unit_audit",
            "executor_task_id": WAIT_TASK_ID,
            "executor_acknowledged_at": stamp(now),
            "executor_next_wakeup_at": stamp(now + timedelta(hours=6)),
            "evidence_ref": args.evidence_ref,
            "evidence_sha256": args.evidence_sha256,
        }
    print(commit_task_updates(STATE, base_snapshot=snapshot, task_updates=updates, writer_id="codex-e40-next-unit-audit:u18-exact-two-precheck"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
