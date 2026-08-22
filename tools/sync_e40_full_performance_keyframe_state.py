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
VIDEO_PREPROD = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_VIDEO_PREPRODUCTION_V1.json"
AUDIO_PLAN = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_EXACT_DIALOGUE_AUDIO_REFERENCE_PLAN_V1.json"
AUDIO_RECEIPT = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/audio_refs_v1/E40_FULL_PERFORMANCE_AUDIO_REFERENCE_EXECUTION_V1.json"
AUDIO_ASR = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/audio_refs_v1/E40_FULL_PERFORMANCE_AUDIO_REFERENCE_ASR_QA_V1.json"
VIDEO_PRECHECK = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_PRECHECK_V4.json"
VIDEO_SUBMISSION = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_SUBMISSION_V1.json"
VIDEO_HARVEST = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_HARVEST_LATEST.json"
VIDEO_CREDIT = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_CREDIT_RECONCILIATION_V1.json"
I2V_PILOT = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_PILOT_V2.json"
I2V_PILOT_PRECHECK = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_PILOT_PRECHECK_V2.json"
I2V_PILOT_CREDIT = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_PILOT_CREDIT_STATUS_V2.json"
VIDEO_TX_DIR = ROOT / "workflow/tasks/giggle_video_submit_transactions/E40"


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
    video_compile_id = "E40-FULL-PERFORMANCE-ADMITTED-VIDEO-PREPRODUCTION-V1"
    video_compile = {
        "task_id": video_compile_id,
        "lane_id": "E40_FULL_PERFORMANCE_VIDEO_PREPRODUCTION",
        "state": "TERMINAL" if VIDEO_PREPROD.is_file() else "WAITING_DEPENDENCY",
        "wait_scope": "NONE",
        "zero_cost": True,
        "deliverable_type": "SIX_Q1_ADMITTED_NATIVE_DIALOGUE_VIDEO_CONTRACTS",
        "liveness_role": "TERMINAL" if VIDEO_PREPROD.is_file() else "DEPENDENCY",
        "provider_post_allowed": False,
        "progress": "COMPILED_6_VIDEO_TASKS_AND_8_AUDIO_INTENTS" if VIDEO_PREPROD.is_file() else "WAITING_FOR_Q1_ADMITTED_INPUTS",
        "last_progress_at": now,
        "next_due_at": None,
        "evidence_ref": portable(VIDEO_PREPROD) if VIDEO_PREPROD.is_file() else portable(Q1),
        "evidence_sha256": sha(VIDEO_PREPROD) if VIDEO_PREPROD.is_file() else sha(Q1),
        "next_action": "Bind exact dialogue audio provider assets, then rerun paid video precheck; no video POST before binding.",
    }
    if video_compile_id in by_id:
        by_id[video_compile_id].update(video_compile)
    else:
        tasks.append(video_compile)
    audio_id = "E40-FULL-PERFORMANCE-EXACT-AUDIO-REFERENCE-EXECUTION-V1"
    audio_terminal = AUDIO_RECEIPT.is_file()
    audio_task = {
        "task_id": audio_id,
        "lane_id": "E40_FULL_PERFORMANCE_EXACT_AUDIO_REFERENCE",
        "state": "TERMINAL" if audio_terminal else "RUNNING",
        "wait_scope": "NONE",
        "zero_cost": False,
        "deliverable_type": "EIGHT_EXACT_DIALOGUE_REFERENCE_AUDIO_ASSETS",
        "liveness_role": "TERMINAL" if audio_terminal else "PRODUCING",
        "provider_post_allowed": False,
        "provider_query_allowed": not audio_terminal,
        "maximum_new_submissions": 0,
        "progress": "EXECUTION_RECEIPT_PERSISTED" if audio_terminal else "TRANSACTIONS_PERSISTED_PROVIDER_EXECUTOR_ACTIVE",
        "last_progress_at": now,
        "next_due_at": None if audio_terminal else next_due,
        "lease_owner": None if audio_terminal else "codex-e40-full-performance-audio",
        "lease_expires_at": None if audio_terminal else lease_expires,
        "executor_handle": None if audio_terminal else "unified_exec_session:37891",
        "executor_task_id": None if audio_terminal else audio_id,
        "evidence_ref": portable(AUDIO_RECEIPT) if audio_terminal else portable(AUDIO_PLAN),
        "evidence_sha256": sha(AUDIO_RECEIPT) if audio_terminal else sha(AUDIO_PLAN),
        "next_action": "ASR exactness and provider asset upload, then bind only admitted keyframes into Seedance Fast tasks.",
    }
    if audio_id in by_id:
        by_id[audio_id].update(audio_task)
    else:
        tasks.append(audio_task)
    asr_id = "E40-FULL-PERFORMANCE-EXACT-AUDIO-ASR-QA-V1"
    asr_terminal = AUDIO_ASR.is_file()
    asr_task = {
        "task_id": asr_id,
        "lane_id": "E40_FULL_PERFORMANCE_EXACT_AUDIO_REFERENCE",
        "state": "TERMINAL" if asr_terminal else "RUNNING",
        "wait_scope": "NONE",
        "zero_cost": True,
        "deliverable_type": "EIGHT_EXACT_DIALOGUE_REFERENCE_ASR_QA",
        "liveness_role": "TERMINAL" if asr_terminal else "PRODUCING",
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "progress": "ASR_QA_PERSISTED" if asr_terminal else "LOCAL_ASR_QA_PROCESS_ACTIVE",
        "last_progress_at": now,
        "next_due_at": None if asr_terminal else next_due,
        "lease_owner": None if asr_terminal else "codex-e40-full-performance-audio-asr",
        "lease_expires_at": None if asr_terminal else lease_expires,
        "executor_handle": None if asr_terminal else "unified_exec_session:71164",
        "executor_task_id": None if asr_terminal else asr_id,
        "evidence_ref": portable(AUDIO_ASR) if asr_terminal else portable(AUDIO_RECEIPT),
        "evidence_sha256": sha(AUDIO_ASR) if asr_terminal else sha(AUDIO_RECEIPT),
        "next_action": "Upload only exact-ASR-passing audio as provider assets and bind them to six video manifests.",
    }
    if asr_id in by_id:
        by_id[asr_id].update(asr_task)
    else:
        tasks.append(asr_task)
    video_submit_id = "E40-FULL-PERFORMANCE-SEEDANCE-FAST-SUBMISSION-V1"
    video_submit_terminal = VIDEO_SUBMISSION.is_file()
    video_submit_task = {
        "task_id": video_submit_id,
        "lane_id": "E40_FULL_PERFORMANCE_VIDEO_SUBMISSION",
        "state": "TERMINAL" if video_submit_terminal else "RUNNING",
        "wait_scope": "NONE",
        "zero_cost": False,
        "deliverable_type": "SIX_SEEDANCE_FAST_NATIVE_DIALOGUE_REMOTE_TASK_BINDINGS",
        "liveness_role": "TERMINAL" if video_submit_terminal else "PRODUCING",
        "provider_post_allowed": False,
        "provider_query_allowed": False,
        "maximum_new_submissions": 0,
        "progress": "SUBMISSION_RECEIPT_PERSISTED" if video_submit_terminal else "TRANSACTION_FIRST_SUBMITTER_ACTIVE",
        "last_progress_at": now,
        "next_due_at": None if video_submit_terminal else next_due,
        "lease_owner": None if video_submit_terminal else "codex-e40-full-performance-video-submit",
        "lease_expires_at": None if video_submit_terminal else lease_expires,
        "executor_handle": None if video_submit_terminal else "unified_exec_session:68948",
        "executor_task_id": None if video_submit_terminal else video_submit_id,
        "evidence_ref": portable(VIDEO_SUBMISSION) if video_submit_terminal else portable(VIDEO_PRECHECK),
        "evidence_sha256": sha(VIDEO_SUBMISSION) if video_submit_terminal else sha(VIDEO_PRECHECK),
        "next_action": "Harvest each bound task independently; response-lost transactions require ledger classification and no replay.",
    }
    if video_submit_id in by_id:
        by_id[video_submit_id].update(video_submit_task)
    else:
        tasks.append(video_submit_task)
    video_credit_id = "E40-FULL-PERFORMANCE-VIDEO-CREDIT-RECONCILIATION-V1"
    video_credit_terminal = VIDEO_CREDIT.is_file()
    video_credit_task = {
        "task_id": video_credit_id,
        "lane_id": "E40_FULL_PERFORMANCE_VIDEO_LEDGER_RECONCILIATION",
        "state": "TERMINAL" if video_credit_terminal else "RUNNING",
        "wait_scope": "NONE",
        "zero_cost": True,
        "deliverable_type": "AUTHORITATIVE_SIX_VIDEO_POST_CREDIT_CLASSIFICATION",
        "liveness_role": "TERMINAL" if video_credit_terminal else "PRODUCING",
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "progress": "LEDGER_CLASSIFICATION_PERSISTED" if video_credit_terminal else "VIDEO_LEDGER_RETRY_PROCESS_ACTIVE",
        "last_progress_at": now,
        "next_due_at": None if video_credit_terminal else next_due,
        "lease_owner": None if video_credit_terminal else "codex-e40-full-performance-video-credit",
        "lease_expires_at": None if video_credit_terminal else lease_expires,
        "executor_handle": None if video_credit_terminal else "unified_exec_session:23956",
        "executor_task_id": None if video_credit_terminal else video_credit_id,
        "evidence_ref": portable(VIDEO_CREDIT) if video_credit_terminal else portable(VIDEO_HARVEST),
        "evidence_sha256": sha(VIDEO_CREDIT) if video_credit_terminal else sha(VIDEO_HARVEST),
        "next_action": "Classify five router failures and one response-lost transaction; no re-POST before authoritative result.",
    }
    if video_credit_id in by_id:
        by_id[video_credit_id].update(video_credit_task)
    else:
        tasks.append(video_credit_task)
    if VIDEO_HARVEST.is_file():
        video_harvest = json.loads(VIDEO_HARVEST.read_text(encoding="utf-8"))
        for row in video_harvest.get("results") or []:
            task_id = f"{row['task_key']}-PROVIDER-V1"
            terminal = row.get("status") in {"failed", "error", "canceled", "cancelled", "completed"}
            remote = {
                "task_id": task_id,
                "lane_id": "E40_FULL_PERFORMANCE_VIDEO_PROVIDER",
                "state": "TERMINAL" if terminal else "WAITING_DEPENDENCY",
                "wait_scope": "TASK_LOCAL" if not terminal else "NONE",
                "zero_cost": False,
                "deliverable_type": "SEEDANCE_FAST_NATIVE_DIALOGUE_VIDEO",
                "liveness_role": "TERMINAL" if terminal else "DEPENDENCY",
                "remote_task_id": row.get("task_id"),
                "provider_post_allowed": False,
                "maximum_new_submissions": 0,
                "progress": "PROVIDER_ROUTER_MAPPING_FAILED_PENDING_REFUND_CLASSIFICATION" if row.get("status") == "failed" else str(row.get("status")),
                "last_progress_at": now,
                "next_due_at": None,
                "exact_predecessor_task_id": video_credit_id if not terminal else None,
                "evidence_ref": portable(VIDEO_HARVEST),
                "evidence_sha256": sha(VIDEO_HARVEST),
                "next_action": "Classify exact task Pay/Refund; no replay. Router repair may proceed only after material transport correction.",
            }
            if task_id in by_id:
                by_id[task_id].update(remote)
            else:
                tasks.append(remote)
    pilot_active = False
    pilot_transactions = sorted(VIDEO_TX_DIR.glob("E40-FP-R04-YUNFEI-B-V1-VIDEO-V2__*.json"))
    if I2V_PILOT.is_file() and len(pilot_transactions) == 1:
        pilot_tx = json.loads(pilot_transactions[0].read_text(encoding="utf-8"))
        pilot_bound = pilot_tx.get("state") == "SUBMITTED_TASK_ID_BOUND" and bool(pilot_tx.get("task_id"))
        pilot_active = bool(pilot_bound)
        pilot_id = "E40-FP-R04-YUNFEI-B-V1-VIDEO-V2-I2V-NATIVE-TEXT-PILOT"
        pilot_task = {
            "task_id": pilot_id,
            "lane_id": "E40_FULL_PERFORMANCE_VIDEO_PROVIDER_ROUTE_PILOT",
            "state": "REMOTE_WAIT" if pilot_bound else "WAITING_DEPENDENCY",
            "wait_scope": "TASK_LOCAL",
            "zero_cost": False,
            "deliverable_type": "SEEDANCE_FAST_I2V_SAME_TASK_NATIVE_DIALOGUE_VIDEO",
            "liveness_role": "REMOTE_PROVIDER_TASK" if pilot_bound else "DEPENDENCY",
            "remote_task_id": pilot_tx.get("task_id"),
            "provider_post_allowed": False,
            "provider_query_allowed": bool(pilot_bound),
            "maximum_new_submissions": 0,
            "progress": "I2V_NATIVE_TEXT_PILOT_REMOTE_RUNNING" if pilot_bound else str(pilot_tx.get("state")),
            "last_progress_at": now,
            "next_due_at": next_due if pilot_bound else None,
            "lease_owner": "codex-e40-i2v-native-text-pilot" if pilot_bound else None,
            "lease_expires_at": lease_expires if pilot_bound else None,
            "evidence_ref": portable(pilot_transactions[0]),
            "evidence_sha256": sha(pilot_transactions[0]),
            "next_action": "Query only the bound task; on completion download once and run exact-frame, native-audio and registered Q2 QA. Never repeat POST.",
        }
        if pilot_id in by_id:
            by_id[pilot_id].update(pilot_task)
        else:
            tasks.append(pilot_task)
    scheduler.update({
        "updated_at": now,
        "status": "ACTIVE_LEDGER_RECONCILIATION_AND_I2V_NATIVE_DIALOGUE_ROUTE_PILOT",
        "target_slots": 3,
        "real_active_handle_count": (0 if CREDIT.is_file() else 1) + (0 if audio_terminal else 1) + (0 if asr_terminal else 1) + (0 if video_submit_terminal else 1) + (0 if video_credit_terminal else 1) + (1 if pilot_active else 0),
    })
    scheduler.setdefault("heartbeat_integration", {}).update({
        "state": "ACTIVE",
        "real_active_handle_count": scheduler["real_active_handle_count"],
        "episode_terminal": False,
        "blocking_units": ["R01", "R02", "R03", "R06A", "R07", "R08"],
        "解除条件": "Harvest the bound R04 image-to-video native-dialogue pilot and finish authoritative classification of response-lost image/video transactions.",
    })
    write(SCHEDULER, scheduler)

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue.update({
        "updated_at": now,
        "mode": "FULL_PERFORMANCE_I2V_NATIVE_DIALOGUE_ROUTE_PILOT_AND_LEDGER_RECONCILIATION",
        "status": "ACTIVE_I2V_NATIVE_DIALOGUE_ROUTE_PILOT_AND_TWO_LEDGER_RECONCILIATIONS",
        "target_slots": 3,
        "real_active_handle_count": scheduler["real_active_handle_count"],
        "next_action": "Harvest the bound R04 image-to-video native-dialogue pilot; if it passes provider and Q2, expand only to eligible units. Keep response-lost transactions isolated.",
    })
    queue["latest_e40_full_performance_i2v_native_text_pilot_v2"] = {
        "manifest": portable(I2V_PILOT) if I2V_PILOT.is_file() else None,
        "manifest_sha256": sha(I2V_PILOT) if I2V_PILOT.is_file() else None,
        "precheck": portable(I2V_PILOT_PRECHECK) if I2V_PILOT_PRECHECK.is_file() else None,
        "precheck_sha256": sha(I2V_PILOT_PRECHECK) if I2V_PILOT_PRECHECK.is_file() else None,
        "remote_task_id": pilot_tx.get("task_id") if I2V_PILOT.is_file() and len(pilot_transactions) == 1 else None,
        "status": "REMOTE_RUNNING" if pilot_active else "NOT_BOUND",
        "credit_status": portable(I2V_PILOT_CREDIT) if I2V_PILOT_CREDIT.is_file() else None,
        "credit_status_sha256": sha(I2V_PILOT_CREDIT) if I2V_PILOT_CREDIT.is_file() else None,
        "duplicate_post_forbidden": True,
        "next_action": "Query/download only this task and run exact-frame plus native-dialogue Q2 before any batch expansion.",
    }
    if pilot_active and I2V_PILOT_CREDIT.is_file():
        pilot_credit = json.loads(I2V_PILOT_CREDIT.read_text(encoding="utf-8"))
        queue.setdefault("e40_credits", {}).update({
            "active_remote_video_pay": pilot_credit.get("net_charged_credits"),
            "active_remote_video_task_id": pilot_tx.get("task_id"),
            "pending_remote_video_task_count": 1,
            "pending_remote_video_task_ids": [pilot_tx.get("task_id")],
            "status": "R04_I2V_NATIVE_TEXT_PILOT_RUNNING_EXACT_PAY128_REFUND0; RESPONSE_LOST_POSTS_REMAIN_ISOLATED",
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
        "video_preproduction_manifest": portable(VIDEO_PREPROD) if VIDEO_PREPROD.is_file() else None,
        "video_preproduction_manifest_sha256": sha(VIDEO_PREPROD) if VIDEO_PREPROD.is_file() else None,
        "exact_audio_reference_plan": portable(AUDIO_PLAN) if AUDIO_PLAN.is_file() else None,
        "exact_audio_reference_plan_sha256": sha(AUDIO_PLAN) if AUDIO_PLAN.is_file() else None,
        "exact_audio_executor": None if audio_terminal else "unified_exec_session:37891",
        "exact_audio_asr_qa": portable(AUDIO_ASR) if asr_terminal else None,
        "exact_audio_asr_executor": None if asr_terminal else "unified_exec_session:71164",
        "video_precheck": portable(VIDEO_PRECHECK) if VIDEO_PRECHECK.is_file() else None,
        "video_submission_executor": None if video_submit_terminal else "unified_exec_session:68948",
        "video_credit_reconciliation_executor": None if video_credit_terminal else "unified_exec_session:23956",
        "q1_index": portable(Q1),
        "q1_index_sha256": sha(Q1),
        "next_action": "Compile six admitted exact-SHA Seedance Fast native-dialogue video manifests while ledger reconciliation continues; never submit from the two failed SHAs.",
    }
    write(QUEUE, queue)
    print(json.dumps({"status": "PASS", "scheduler_sha256": sha(SCHEDULER), "queue_sha256": sha(QUEUE), "real_active_handle_count": scheduler["real_active_handle_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
