#!/usr/bin/env python3
"""Sync E40 full-performance keyframe submission/Q1/ledger state."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULER = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
MANIFEST = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_KEYFRAME_BATCH_V1.json"
HARVEST = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes/E40_FULL_PERFORMANCE_KEYFRAME_HARVEST_V1.json"
Q1 = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes/q1_registered/E40_FULL_PERFORMANCE_KEYFRAME_Q1_INDEX_V1.json"
BOUND = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes/E40_FULL_PERFORMANCE_KEYFRAME_BOUND_TASKS_V1.json"
CREDIT = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes/E40_FULL_PERFORMANCE_KEYFRAME_CREDIT_RECONCILIATION_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def portable(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    observed_at = datetime.now(timezone.utc)
    now = observed_at.isoformat().replace("+00:00", "Z")
    next_due = (observed_at + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    lease_expires = (observed_at + timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
    scheduler = json.loads(SCHEDULER.read_text(encoding="utf-8"))
    tasks = scheduler.setdefault("tasks", [])
    by_id = {row.get("task_id"): row for row in tasks}
    compile_id = "E40-FULL-PERFORMANCE-KEYFRAME-BATCH-COMPILE-V1"
    by_id[compile_id].update({
        "state": "TERMINAL",
        "wait_scope": "NONE",
        "progress": "COMPILED_13_NATIVE_REGISTRY_SPATIAL_KEYFRAMES_PRECHECK_13_OF_13_PASS",
        "completed_at": now,
        "last_progress_at": now,
        "next_due_at": None,
        "evidence_ref": portable(MANIFEST),
        "evidence_sha256": sha(MANIFEST),
    })

    q1 = json.loads(Q1.read_text(encoding="utf-8"))
    for item in q1["results"]:
        task_id = f"{item['task_key']}-REMOTE"
        row = {
            "task_id": task_id,
            "lane_id": "E40_FULL_PERFORMANCE_KEYFRAME_Q1",
            "state": "TERMINAL",
            "wait_scope": "NONE",
            "zero_cost": False,
            "deliverable_type": "EXACT_SHA_Q1_KEYFRAME",
            "liveness_role": "TERMINAL_EVIDENCE",
            "provider_post_allowed": False,
            "provider_query_allowed": False,
            "download_allowed": False,
            "maximum_new_submissions": 0,
            "remote_task_id": item["task_id"],
            "progress": item["downstream_status"],
            "last_progress_at": now,
            "completed_at": now,
            "next_due_at": None,
            "evidence_ref": item["admission_result"],
            "evidence_sha256": item["admission_result_sha256"],
            "next_action": "Compile Seedance native-dialogue video contract." if item["downstream_status"] == "ADMITTED_FOR_VIDEO_SUBMIT" else "Isolate failed keyframe; no video POST from this SHA.",
        }
        if task_id in by_id:
            by_id[task_id].update(row)
        else:
            tasks.append(row)
            by_id[task_id] = row

    bound = json.loads(BOUND.read_text(encoding="utf-8"))
    for transaction in bound["ambiguous_transactions"]:
        tx = json.loads((ROOT / transaction).read_text(encoding="utf-8"))
        task_id = f"{tx['task_key']}-AMBIGUOUS-POST"
        row = {
            "task_id": task_id,
            "lane_id": "E40_FULL_PERFORMANCE_KEYFRAME_LEDGER_RECONCILIATION",
            "state": "WAITING_DEPENDENCY",
            "wait_scope": "TASK_LOCAL",
            "zero_cost": False,
            "deliverable_type": "PAID_POST_AMBIGUITY_LEDGER_CLASSIFICATION",
            "liveness_role": "BLOCKED_EVIDENCE",
            "provider_post_allowed": False,
            "provider_query_allowed": False,
            "download_allowed": False,
            "maximum_new_submissions": 0,
            "remote_task_id": None,
            "progress": "RESPONSE_LOST_PENDING_AUTHORITATIVE_LEDGER_RECONCILIATION",
            "last_progress_at": now,
            "next_due_at": now,
            "waiting_on_predecessor_task_id": "E40-FULL-PERFORMANCE-KEYFRAME-CREDIT-RECONCILIATION-V1",
            "exact_predecessor_task_id": "E40-FULL-PERFORMANCE-KEYFRAME-CREDIT-RECONCILIATION-V1",
            "evidence_ref": transaction,
            "evidence_sha256": sha(ROOT / transaction),
            "next_action": "Never repeat POST; await exact ledger-window classification.",
        }
        if task_id in by_id:
            by_id[task_id].update(row)
        else:
            tasks.append(row)
            by_id[task_id] = row

    reconciliation_id = "E40-FULL-PERFORMANCE-KEYFRAME-CREDIT-RECONCILIATION-V1"
    reconciliation = {
        "task_id": reconciliation_id,
        "lane_id": "E40_FULL_PERFORMANCE_KEYFRAME_LEDGER_RECONCILIATION",
        "state": "RUNNING" if not CREDIT.is_file() else "TERMINAL",
        "wait_scope": "NONE",
        "zero_cost": True,
        "deliverable_type": "AUTHORITATIVE_13_POST_CREDIT_WINDOW_CLASSIFICATION",
        "liveness_role": "PRODUCING",
        "provider_post_allowed": False,
        "provider_query_allowed": False,
        "download_allowed": False,
        "maximum_new_submissions": 0,
        "progress": "LEDGER_RETRY_PROCESS_ACTIVE" if not CREDIT.is_file() else "LEDGER_CLASSIFICATION_PERSISTED",
        "last_progress_at": now,
        "next_due_at": next_due if not CREDIT.is_file() else None,
        "lease_owner": "codex-e40-credit-reconciliation" if not CREDIT.is_file() else None,
        "lease_expires_at": lease_expires if not CREDIT.is_file() else None,
        "executor_handle": None if CREDIT.is_file() else "unified_exec_session:88090",
        "executor_task_id": reconciliation_id if not CREDIT.is_file() else None,
        "evidence_ref": portable(CREDIT) if CREDIT.is_file() else portable(BOUND),
        "evidence_sha256": sha(CREDIT) if CREDIT.is_file() else sha(BOUND),
        "next_action": "Persist exact Pay count and classify all five response-lost transactions; no re-POST.",
    }
    if reconciliation_id in by_id:
        by_id[reconciliation_id].update(reconciliation)
    else:
        tasks.append(reconciliation)
    scheduler.update({
        "updated_at": now,
        "status": "ACTIVE_KEYFRAME_LEDGER_RECONCILIATION_AND_ADMITTED_VIDEO_COMPILE_PENDING",
        "target_slots": 2,
        "real_active_handle_count": 0 if CREDIT.is_file() else 1,
    })
    write(SCHEDULER, scheduler)

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue.update({
        "updated_at": now,
        "mode": "FULL_PERFORMANCE_KEYFRAME_Q1_AND_LEDGER_RECONCILIATION",
        "status": "ACTIVE_8_COMPLETED_6_Q1_ADMITTED_2_Q1_FAILED_5_RESPONSE_LOST_NO_REPOST",
    })
    queue["latest_e40_full_performance_keyframes"] = {
        "manifest": portable(MANIFEST),
        "manifest_sha256": sha(MANIFEST),
        "bound_task_ids": 8,
        "completed_downloaded": 8,
        "q1_admitted": 6,
        "q1_failed": 2,
        "response_lost_pending_ledger": 5,
        "credit_reconciliation_active": not CREDIT.is_file(),
        "credit_reconciliation_executor": None if CREDIT.is_file() else "unified_exec_session:88090",
        "q1_index": portable(Q1),
        "q1_index_sha256": sha(Q1),
        "next_action": "Compile six admitted exact-SHA Seedance Fast native-dialogue video manifests while ledger reconciliation continues; never submit from the two failed SHAs.",
    }
    write(QUEUE, queue)
    print(json.dumps({"status": "PASS", "scheduler_sha256": sha(SCHEDULER), "queue_sha256": sha(QUEUE), "real_active_handle_count": scheduler["real_active_handle_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
