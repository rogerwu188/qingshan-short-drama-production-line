#!/usr/bin/env python3
"""CAS-transition U18 exact-two root authorization into one-shot execution/remote wait."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
AUTH = ROOT / "workflow/approvals/E40_U18_EXACT_TWO_ISOLATED_ASSET_IMAGE_AUTHORIZATION_20260813.json"
REPORT = ROOT / "qa/e40_production_20260813/u18_exact_two_isolated_asset_execution_v1/E40_U18_EXACT_TWO_ONE_POST_TASK_ID_BINDING_RECEIPT_V1.json"
STORE = Path("/Users/rogerwu/.local/share/backlotos/share/pipeline-tools")
sys.path.insert(0, str(STORE))
from task_lane_state_store import commit_task_updates, read_scheduler_snapshot  # noqa: E402

WAIT_ID = "E40-U18-V3-EXACT-TWO-ROOT-AUTHORIZATION-TASK-LOCAL-REMOTE-WAIT"
EXEC_ID = "E40-U18-V4-EXACT-TWO-IMAGE-ONE-POST-TASK-ID-BINDING"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("authorize-running", "bind-remote", "fail-qa"))
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    snap = read_scheduler_snapshot(STATE)
    wait = next((copy.deepcopy(row) for row in snap.payload["tasks"] if row.get("task_id") == WAIT_ID), None)
    if wait is None:
        raise SystemExit("authorization wait task missing")
    updates = {}
    if args.action == "authorize-running":
        if wait.get("state") != "REMOTE_WAIT":
            raise SystemExit(f"unexpected wait state {wait.get('state')}")
        wait.update({
            "state": "TERMINAL",
            "wait_scope": "NONE_TERMINAL",
            "progress": "ROOT_EXACT_TWO_IMMUTABLE_AUTHORIZATION_GRANTED",
            "authorization": True,
            "provider_post_allowed": False,
            "maximum_new_submissions": 0,
            "completed_at": stamp(now),
            "terminal_status": "AUTHORIZED_EXACTLY_TWO_HANDOFF_TO_V4",
            "evidence_ref": str(AUTH.relative_to(ROOT)),
            "evidence_sha256": sha(AUTH),
            "next_due_at": None,
            "blocked_by": None,
            "next_action": "V4 performs only the two authorized exact image posts with transaction-before-POST and immediate task-id binding."
        })
        for key in ("execution_mode", "executor_handle", "executor_task_id", "executor_acknowledged_at", "executor_next_wakeup_at"):
            wait.pop(key, None)
        updates[WAIT_ID] = wait
        updates[EXEC_ID] = {
            "task_id": EXEC_ID,
            "lane_id": "U18_ISOLATED_ASSET_ACQUISITION",
            "state": "RUNNING",
            "zero_cost": False,
            "deliverable_type": "EXACT_TWO_IMAGE_ONE_POST_TASK_ID_BINDING",
            "priority": 176,
            "scope": ["E40", "U18", "EXACT_TWO", "IMAGE_GENERATION", "NO_STATUS_POLL", "NO_RETRY"],
            "exact_predecessor_task_id": WAIT_ID,
            "liveness_role": "PRODUCING",
            "observation_only": False,
            "maximum_new_submissions": 2,
            "authorization": True,
            "provider_post_allowed": True,
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
            "wait_scope": "NONE_ACTIVE_RUNNING",
            "progress": "AUTHORIZED_RUNNING_PRE_POST_EXACT_TRANSACTION_BINDING",
            "last_progress_at": stamp(now),
            "next_action": "Persist each exact transaction before POST and bind each returned task_id; no generation-status poll.",
            "lease_owner": "codex-root:u18-exact-two-v4",
            "lease_expires_at": stamp(now + timedelta(hours=2)),
            "next_due_at": stamp(now + timedelta(minutes=20)),
            "execution_mode": "CONTINUOUS",
            "executor_handle": "agent:/root",
            "executor_task_id": EXEC_ID,
            "executor_acknowledged_at": stamp(now),
            "executor_next_wakeup_at": stamp(now + timedelta(minutes=10)),
            "evidence_ref": str(AUTH.relative_to(ROOT)),
            "evidence_sha256": sha(AUTH)
        }
    else:
        row = next((copy.deepcopy(item) for item in snap.payload["tasks"] if item.get("task_id") == EXEC_ID), None)
        if row is None or row.get("state") != "RUNNING":
            raise SystemExit("running V4 task missing")
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        task_ids = [item.get("task_id") for item in report.get("results", []) if item.get("task_id")]
        if args.action == "fail-qa":
            if report.get("status") != "FAIL_CLOSED_RESPONSE_LOSS_CLASSIFIED_NO_RETRY" or task_ids:
                raise SystemExit("execution report is not classified zero-task failure")
            failures = report.get("failures", [])
            if len(failures) != 2 or any(item.get("credit_status") != "FAILED_ZERO_VERIFIED" for item in failures):
                raise SystemExit("failure classification is not exact-two FAILED_ZERO_VERIFIED")
            row.update({
                "state": "QA",
                "zero_cost": True,
                "wait_scope": "NONE_ACTIVE_QA",
                "progress": "EXACT_TWO_WRITE_TIMEOUT_PAY0_TASK_ID0_FAILURE_MEMORY_PERSISTED_V5_CHANGED_INPUT_QA",
                "provider_calls": 2,
                "transactions": 2,
                "credits": 0,
                "maximum_new_submissions": 0,
                "authorization": False,
                "provider_post_allowed": False,
                "task_ids": [],
                "last_progress_at": stamp(now),
                "blocked_by": "V1_FINGERPRINTS_CLOSED_UNCHANGED_REPLAY_FORBIDDEN_V5_CHANGED_PROMPTS_NOT_YET_PRECHECKED",
                "next_action": "Compile materially changed Chinese compact V5 prompts with new task keys/fingerprints; run zero-submit installed precheck before any fresh authorization.",
                "lease_expires_at": stamp(now + timedelta(hours=2)),
                "next_due_at": stamp(now + timedelta(minutes=20)),
                "executor_handle": "agent:/root/e40_next_unit_audit",
                "executor_task_id": EXEC_ID,
                "executor_acknowledged_at": stamp(now),
                "executor_next_wakeup_at": stamp(now + timedelta(minutes=10)),
                "evidence_ref": str(REPORT.relative_to(ROOT)),
                "evidence_sha256": sha(REPORT)
            })
            updates[EXEC_ID] = row
            print(commit_task_updates(STATE, base_snapshot=snap, task_updates=updates, writer_id="codex-root:u18-exact-two-v4-failure-qa"))
            return 0
        if report.get("status") != "PASS_EXACT_TWO_TASK_IDS_BOUND_REMOTE_WAIT_NO_STATUS_POLL" or len(task_ids) != 2:
            raise SystemExit("execution report is not exact-two bound PASS")
        row.update({
            "state": "REMOTE_WAIT",
            "wait_scope": "TASK_LOCAL",
            "progress": "EXACT_TWO_TASK_IDS_BOUND_REMOTE_WAIT_NO_STATUS_POLL",
            "provider_calls": 2,
            "transactions": 2,
            "credits": None,
            "maximum_new_submissions": 0,
            "authorization": False,
            "provider_post_allowed": False,
            "task_ids": task_ids,
            "last_progress_at": stamp(now),
            "blocked_by": "REMOTE_IMAGE_OUTPUTS_NOT_YET_RETRIEVED_AND_CREDIT_LEDGER_NOT_YET_CLASSIFIED",
            "next_action": "Wait task-locally; later perform one exact-task retrieval/classification checkpoint, then run U18 output machine and human gates. No replay.",
            "lease_expires_at": stamp(now + timedelta(hours=24)),
            "next_due_at": stamp(now + timedelta(hours=1)),
            "executor_handle": "agent:/root/e40_next_unit_audit",
            "executor_task_id": EXEC_ID,
            "executor_acknowledged_at": stamp(now),
            "executor_next_wakeup_at": stamp(now + timedelta(minutes=30)),
            "evidence_ref": str(REPORT.relative_to(ROOT)),
            "evidence_sha256": sha(REPORT)
        })
        updates[EXEC_ID] = row
    print(commit_task_updates(STATE, base_snapshot=snap, task_updates=updates, writer_id="codex-root:u18-exact-two-v4"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
