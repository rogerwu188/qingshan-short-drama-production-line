#!/usr/bin/env python3
"""Close V4 changed-input QA and register V5 exact-two root-authorization wait."""

from __future__ import annotations

import copy
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
AUDIT = ROOT / "qa/e40_preproduction_20260813/u18_v5_changed_compact_precheck_v1/E40_U18_V5_CHANGED_COMPACT_EXECUTION_READINESS_AUDIT_V1.json"
V4 = "E40-U18-V4-EXACT-TWO-IMAGE-ONE-POST-TASK-ID-BINDING"
V5 = "E40-U18-V5-CHANGED-COMPACT-EXACT-TWO-ROOT-AUTHORIZATION-TASK-LOCAL-REMOTE-WAIT"
sys.path.insert(0, "/Users/rogerwu/.local/share/backlotos/share/pipeline-tools")
from task_lane_state_store import commit_task_updates, read_scheduler_snapshot  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ts(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def main() -> int:
    now = datetime.now(timezone.utc)
    snap = read_scheduler_snapshot(STATE)
    row = next((copy.deepcopy(item) for item in snap.payload["tasks"] if item.get("task_id") == V4), None)
    if row is None or row.get("state") != "QA":
        raise SystemExit(f"unexpected V4 state: {None if row is None else row.get('state')}")
    evidence_sha = sha(AUDIT)
    row.update({
        "state": "TERMINAL",
        "wait_scope": "NONE_TERMINAL",
        "progress": "PASS_V5_CHANGED_CHINESE_COMPACT_EXACT_TWO_PREFLIGHT_ZERO_SUBMIT",
        "completed_at": ts(now),
        "terminal_status": "PASS_V5_CHANGED_COMPACT_EXACT_TWO_PREFLIGHT_NOT_AUTHORIZED_NO_SUBMIT",
        "next_due_at": None,
        "blocked_by": "SEPARATE_V5_ROOT_EXACT_TWO_IMMUTABLE_AUTHORIZATION_MISSING",
        "evidence_ref": str(AUDIT.relative_to(ROOT)),
        "evidence_sha256": evidence_sha,
        "next_action": "Wait for separate V5 exact-two authorization; no unchanged V1 replay."
    })
    for key in ("execution_mode", "executor_handle", "executor_task_id", "executor_acknowledged_at", "executor_next_wakeup_at"):
        row.pop(key, None)
    wait = {
        "task_id": V5,
        "lane_id": "U18_ISOLATED_ASSET_ACQUISITION",
        "state": "REMOTE_WAIT",
        "zero_cost": True,
        "deliverable_type": "V5_CHANGED_COMPACT_EXACT_TWO_ROOT_AUTHORIZATION_TASK_LOCAL_REMOTE_WAIT",
        "priority": 177,
        "scope": ["E40", "U18", "V5", "CHANGED_INPUT", "ROOT_AUTHORIZATION", "TASK_LOCAL", "NO_PROVIDER", "NO_TRANSACTION", "NO_CREDITS"],
        "exact_predecessor_task_id": V4,
        "liveness_role": "PRODUCING",
        "observation_only": False,
        "maximum_new_submissions": 0,
        "authorization": False,
        "provider_post_allowed": False,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
        "wait_scope": "TASK_LOCAL",
        "blocked_by": "SEPARATE_V5_ROOT_EXACT_TWO_IMMUTABLE_AUTHORIZATION_MISSING",
        "progress": "V5_CHANGED_COMPACT_PREFLIGHT_PASS_WAITING_ROOT_AUTHORIZATION",
        "last_progress_at": ts(now),
        "next_action": "Wake only for immutable V5 exact-two authorization after immediate price/cap/uniqueness re-read.",
        "lease_owner": "codex-e40-next-unit-audit:u18-v5-root-wait",
        "lease_expires_at": ts(now + timedelta(hours=24)),
        "next_due_at": ts(now + timedelta(hours=12)),
        "execution_mode": "CONTINUOUS",
        "executor_handle": "agent:/root/e40_next_unit_audit",
        "executor_task_id": V5,
        "executor_acknowledged_at": ts(now),
        "executor_next_wakeup_at": ts(now + timedelta(hours=6)),
        "evidence_ref": str(AUDIT.relative_to(ROOT)),
        "evidence_sha256": evidence_sha
    }
    print(commit_task_updates(STATE, base_snapshot=snap, task_updates={V4: row, V5: wait}, writer_id="codex-root:u18-v5-precheck-closeout"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
