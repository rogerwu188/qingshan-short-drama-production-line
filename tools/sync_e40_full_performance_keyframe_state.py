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
RECOVERY_Q1 = [
    ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes/q1_recovery5_registered/E40_FULL_PERFORMANCE_KEYFRAME_Q1_INDEX_V1.json",
    ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes/q1_recovery4_registered/E40_FULL_PERFORMANCE_KEYFRAME_Q1_INDEX_V1.json",
]
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
RECOVERY_VIDEO_MANIFEST = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_VIDEO_RECOVERY2_NATIVE_TEXT_V1.json"
RECOVERY_VIDEO_SUBMISSION = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_RECOVERY2_NATIVE_TEXT_SUBMISSION_V1.json"
RECOVERY_VIDEO_RETRY_MANIFEST = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_VIDEO_RECOVERY2_I2V_NATIVE_TEXT_RETRY2_V1.json"
RECOVERY_VIDEO_RETRY_SUBMISSION = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_RECOVERY2_I2V_NATIVE_TEXT_RETRY2_SUBMISSION_V1.json"
RECOVERY_VIDEO_RETRY_HARVEST = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_RECOVERY2_I2V_NATIVE_TEXT_RETRY2_HARVEST_V7.json"
RECOVERY_VIDEO_RETRY_CREDIT = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_RECOVERY2_I2V_NATIVE_TEXT_RETRY2_CREDIT_CLASSIFICATION_V1.json"
RECOVERY_VIDEO_TERMINAL_COVERAGE_QA = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/terminal_dialogue_coverage_v1/E40_R02_R03_TERMINAL_DIALOGUE_COVERAGE_V1_QA.json"
I2V_WAITING_WAVE = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_VIDEO_I2V_WAITING_WAVE_V1.json"
KEYFRAME_REPAIR_WAVE = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_KEYFRAME_REPAIR_WAVE_V2.json"
KEYFRAME_REPAIR_SELECTED = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_KEYFRAME_REPAIR_SELECTED_V2.json"
KEYFRAME_REPAIR_SUBMISSION = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes_repair_v2/E40_FULL_PERFORMANCE_KEYFRAME_REPAIR_SELECTED_SUBMISSION_V2.json"
KEYFRAME_REPAIR_Q1 = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes_repair_v2/q1_registered/E40_FULL_PERFORMANCE_KEYFRAME_Q1_INDEX_V1.json"
I2V_PILOT = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_PILOT_V2.json"
I2V_PILOT_PRECHECK = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_PILOT_PRECHECK_V2.json"
I2V_PILOT_CREDIT = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_PILOT_CREDIT_STATUS_V2.json"
I2V_FINAL = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_FINAL_V3.json"
I2V_FINAL_PRECHECK = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_FINAL_PRECHECK_V3.json"
I2V_FINAL_CREDIT = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_FINAL_CREDIT_STATUS_V3.json"
I2V_FINAL_HARVEST = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_FINAL_Q2_HARVEST_V3.json"
R04_TERMINAL_COVERAGE = ROOT / "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/terminal_switch_coverage_v1/E40_R04_YUNFEI_OFFSCREEN_COVERAGE_V1.mp4"
R04_TERMINAL_COVERAGE_QA = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/terminal_switch_coverage_v1/E40_R04_YUNFEI_OFFSCREEN_COVERAGE_V1_QA.json"
ASSEMBLY_V3 = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V6_ALL_DIALOGUE_COVERED.mp4"
ASSEMBLY_V3_QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V6_ALL_DIALOGUE_COVERED_QA.json"
VIDEO_TX_DIR = ROOT / "workflow/tasks/giggle_video_submit_transactions/E40"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def portable(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def report_passed(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("status") == "PASS"
    except (OSError, json.JSONDecodeError):
        return False


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
    all_q1_rows = list(q1["results"])
    for recovery_q1_path in RECOVERY_Q1:
        if recovery_q1_path.is_file():
            all_q1_rows.extend(json.loads(recovery_q1_path.read_text(encoding="utf-8"))["results"])
    for item in all_q1_rows:
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
        recovered = tx.get("state") == "SUBMITTED_TASK_ID_BOUND" and bool(tx.get("task_id"))
        row = {
            "task_id": task_id,
            "lane_id": "E40_FULL_PERFORMANCE_KEYFRAME_LEDGER_RECONCILIATION",
            "state": "TERMINAL" if recovered else "WAITING_DEPENDENCY",
            "wait_scope": "NONE" if recovered else "TASK_LOCAL",
            "zero_cost": False,
            "deliverable_type": "PAID_POST_AMBIGUITY_LEDGER_CLASSIFICATION",
            "liveness_role": "TERMINAL_EVIDENCE" if recovered else "BLOCKED_EVIDENCE",
            "provider_post_allowed": False,
            "provider_query_allowed": False,
            "download_allowed": False,
            "maximum_new_submissions": 0,
            "remote_task_id": tx.get("task_id"),
            "progress": "RECOVERED_TASK_ID_BOUND_AND_Q1_TERMINAL" if recovered else "RESPONSE_LOST_PENDING_AUTHORITATIVE_LEDGER_RECONCILIATION",
            "last_progress_at": now,
            "next_due_at": None if recovered else now,
            "waiting_on_predecessor_task_id": "E40-FULL-PERFORMANCE-KEYFRAME-CREDIT-RECONCILIATION-V1",
            "exact_predecessor_task_id": "E40-FULL-PERFORMANCE-KEYFRAME-CREDIT-RECONCILIATION-V1",
            "evidence_ref": transaction,
            "evidence_sha256": sha(ROOT / transaction),
            "next_action": "No duplicate POST; recovered provider task is terminalized by exact-SHA Q1." if recovered else "Never repeat POST; await exact ledger-window classification.",
        }
        if task_id in by_id:
            by_id[task_id].update(row)
        else:
            tasks.append(row)
            by_id[task_id] = row

    reconciliation_id = "E40-FULL-PERFORMANCE-KEYFRAME-CREDIT-RECONCILIATION-V1"
    credit_terminal = report_passed(CREDIT)
    reconciliation = {
        "task_id": reconciliation_id,
        "lane_id": "E40_FULL_PERFORMANCE_KEYFRAME_LEDGER_RECONCILIATION",
        "state": "TERMINAL" if credit_terminal else "RUNNING",
        "wait_scope": "NONE",
        "zero_cost": True,
        "deliverable_type": "AUTHORITATIVE_13_POST_CREDIT_WINDOW_CLASSIFICATION",
        "liveness_role": "PRODUCING",
        "provider_post_allowed": False,
        "provider_query_allowed": False,
        "download_allowed": False,
        "maximum_new_submissions": 0,
        "progress": "LEDGER_CLASSIFICATION_PERSISTED" if credit_terminal else "LEDGER_RETRY_PROCESS_ACTIVE",
        "last_progress_at": now,
        "next_due_at": None if credit_terminal else next_due,
        "lease_owner": None if credit_terminal else "codex-e40-credit-reconciliation",
        "lease_expires_at": None if credit_terminal else lease_expires,
        "executor_handle": None if credit_terminal else "unified_exec_session:88090",
        "executor_task_id": None if credit_terminal else reconciliation_id,
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
    video_credit_terminal = report_passed(VIDEO_CREDIT)
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
        pilot_terminal = str(pilot_tx.get("state") or "").startswith("TERMINAL_")
        pilot_active = bool(pilot_bound)
        pilot_id = "E40-FP-R04-YUNFEI-B-V1-VIDEO-V2-I2V-NATIVE-TEXT-PILOT"
        pilot_task = {
            "task_id": pilot_id,
            "lane_id": "E40_FULL_PERFORMANCE_VIDEO_PROVIDER_ROUTE_PILOT",
            "state": "TERMINAL" if pilot_terminal else "REMOTE_WAIT" if pilot_bound else "WAITING_DEPENDENCY",
            "wait_scope": "NONE" if pilot_terminal else "TASK_LOCAL",
            "zero_cost": False,
            "deliverable_type": "SEEDANCE_FAST_I2V_SAME_TASK_NATIVE_DIALOGUE_VIDEO",
            "liveness_role": "TERMINAL_EVIDENCE" if pilot_terminal else "REMOTE_PROVIDER_TASK" if pilot_bound else "DEPENDENCY",
            "remote_task_id": pilot_tx.get("task_id"),
            "provider_post_allowed": False,
            "provider_query_allowed": bool(pilot_bound),
            "maximum_new_submissions": 0,
            "progress": "I2V_NATIVE_TEXT_PILOT_FAILED_REFUNDED" if pilot_terminal else "I2V_NATIVE_TEXT_PILOT_REMOTE_RUNNING" if pilot_bound else str(pilot_tx.get("state")),
            "last_progress_at": now,
            "next_due_at": next_due if pilot_bound else None,
            "lease_owner": "codex-e40-i2v-native-text-pilot" if pilot_bound else None,
            "lease_expires_at": lease_expires if pilot_bound else None,
            "evidence_ref": portable(pilot_transactions[0]),
            "evidence_sha256": sha(pilot_transactions[0]),
            "next_action": "Final materially changed V3 owns the successor; never replay V2." if pilot_terminal else "Query only the bound task; on completion download once and run exact-frame, native-audio and registered Q2 QA. Never repeat POST.",
        }
        if pilot_id in by_id:
            by_id[pilot_id].update(pilot_task)
        else:
            tasks.append(pilot_task)
    final_active = False
    final_transactions = sorted(VIDEO_TX_DIR.glob("E40-FP-R04-YUNFEI-B1-V1-VIDEO-V3__*.json"))
    if I2V_FINAL.is_file() and len(final_transactions) == 1:
        final_tx = json.loads(final_transactions[0].read_text(encoding="utf-8"))
        final_bound = final_tx.get("state") == "SUBMITTED_TASK_ID_BOUND" and bool(final_tx.get("task_id"))
        final_coverage_terminal = (
            final_tx.get("state") == "TERMINAL_FAILED_REFUNDED"
            and R04_TERMINAL_COVERAGE.is_file()
            and R04_TERMINAL_COVERAGE_QA.is_file()
        )
        final_active = bool(final_bound)
        final_id = "E40-FP-R04-YUNFEI-B1-V1-VIDEO-V3-I2V-NATIVE-TEXT-FINAL"
        final_task = {
            "task_id": final_id,
            "lane_id": "E40_FULL_PERFORMANCE_VIDEO_PROVIDER_ROUTE_FINAL",
            "state": "TERMINAL" if final_coverage_terminal else "REMOTE_WAIT" if final_bound else "WAITING_DEPENDENCY",
            "wait_scope": "NONE" if final_coverage_terminal else "TASK_LOCAL",
            "zero_cost": False,
            "deliverable_type": "SEEDANCE_FAST_REDUCED_LOAD_I2V_NATIVE_DIALOGUE_VIDEO",
            "liveness_role": "TERMINAL_EVIDENCE" if final_coverage_terminal else "REMOTE_PROVIDER_TASK" if final_bound else "DEPENDENCY",
            "remote_task_id": final_tx.get("task_id"),
            "provider_post_allowed": False,
            "provider_query_allowed": bool(final_bound),
            "maximum_new_submissions": 0,
            "progress": "ATTEMPT3_FAILED_REFUNDED_SWITCH_COVERAGE_BUILT_NO_V4" if final_coverage_terminal else "I2V_NATIVE_TEXT_FINAL_REMOTE_RUNNING" if final_bound else str(final_tx.get("state")),
            "last_progress_at": now,
            "next_due_at": next_due if final_bound else None,
            "lease_owner": "codex-e40-i2v-native-text-final" if final_bound else None,
            "lease_expires_at": lease_expires if final_bound else None,
            "evidence_ref": portable(R04_TERMINAL_COVERAGE_QA) if final_coverage_terminal else portable(final_transactions[0]),
            "evidence_sha256": sha(R04_TERMINAL_COVERAGE_QA) if final_coverage_terminal else sha(final_transactions[0]),
            "completed_at": now if final_coverage_terminal else None,
            "next_action": "Insert the admitted zero-cost R04 visual coverage into assembly; do not submit V4." if final_coverage_terminal else "Query only the bound final task; completion enters registered Q2, failure forces SWITCH_COVERAGE_NO_V4.",
        }
        if final_id in by_id:
            by_id[final_id].update(final_task)
        else:
            tasks.append(final_task)
    if ASSEMBLY_V3.is_file() and ASSEMBLY_V3_QA.is_file():
        assembly_id = "E40-CURRENT-ASSEMBLY-V3-R04-TERMINAL-COVERAGE"
        assembly_task = {
            "task_id": assembly_id,
            "lane_id": "E40_FULL_EPISODE_RUNTIME_COMPLETION",
            "state": "TERMINAL",
            "wait_scope": "NONE",
            "zero_cost": True,
            "deliverable_type": "ORDERED_ASSEMBLY_WITH_R02_R03_R04_TERMINAL_COVERAGE",
            "liveness_role": "TERMINAL_EVIDENCE",
            "provider_post_allowed": False,
            "provider_query_allowed": False,
            "download_allowed": False,
            "maximum_new_submissions": 0,
            "progress": "R02_R03_R04_TERMINAL_COVERAGE_STORY_ORDER_TECHNICAL_PASS_FINAL_COMPLETENESS_FAIL",
            "last_progress_at": now,
            "completed_at": now,
            "next_due_at": None,
            "evidence_ref": portable(ASSEMBLY_V3_QA),
            "evidence_sha256": sha(ASSEMBLY_V3_QA),
            "assembly_candidate": portable(ASSEMBLY_V3),
            "assembly_candidate_sha256": sha(ASSEMBLY_V3),
            "next_action": "Continue missing full-performance units; candidate is not releaseable.",
        }
        if assembly_id in by_id:
            by_id[assembly_id].update(assembly_task)
        else:
            tasks.append(assembly_task)
    recovery_video_active = 0
    keyframe_repair_active = 0
    recovery_submission_path = RECOVERY_VIDEO_RETRY_SUBMISSION if RECOVERY_VIDEO_RETRY_SUBMISSION.is_file() else RECOVERY_VIDEO_SUBMISSION
    recovery_manifest_path = RECOVERY_VIDEO_RETRY_MANIFEST if RECOVERY_VIDEO_RETRY_MANIFEST.is_file() else RECOVERY_VIDEO_MANIFEST
    recovery_terminal_coverage = False
    if RECOVERY_VIDEO_RETRY_CREDIT.is_file() and RECOVERY_VIDEO_TERMINAL_COVERAGE_QA.is_file():
        recovery_credit = json.loads(RECOVERY_VIDEO_RETRY_CREDIT.read_text(encoding="utf-8"))
        recovery_coverage = json.loads(RECOVERY_VIDEO_TERMINAL_COVERAGE_QA.read_text(encoding="utf-8"))
        recovery_terminal_coverage = (
            recovery_credit.get("status") == "PASS_ZERO_REFUNDED"
            and recovery_coverage.get("status") == "PASS_ZERO_COST_COVERAGE_NO_VISIBLE_LIP"
        )
    for row in tasks:
        if row.get("lane_id") == "E40_FULL_PERFORMANCE_RECOVERY2_NATIVE_TEXT_VIDEO":
            row.update({
                "state": "TERMINAL",
                "wait_scope": "NONE",
                "provider_query_allowed": False,
                "download_allowed": False,
                "progress": "PRIOR_OMNI_ROUTE_FAILED_ZERO_REFUNDED_REPLACED_BY_I2V_RETRY",
                "completed_at": now,
                "next_due_at": None,
            })
    if recovery_submission_path.is_file():
        recovery_submit = json.loads(recovery_submission_path.read_text(encoding="utf-8"))
        for item in recovery_submit.get("tasks") or []:
            remote_id = item.get("task_id")
            if not remote_id:
                continue
            task_id = f"{item['task_key']}-REMOTE"
            row = {
                "task_id": task_id,
                "lane_id": "E40_FULL_PERFORMANCE_RECOVERY2_NATIVE_TEXT_VIDEO",
                "state": "TERMINAL" if recovery_terminal_coverage else "REMOTE_WAIT",
                "wait_scope": "NONE" if recovery_terminal_coverage else "TASK_LOCAL",
                "zero_cost": False,
                "deliverable_type": "SEEDANCE_FAST_SAME_TASK_NATIVE_DIALOGUE_VIDEO",
                "liveness_role": "TERMINAL_EVIDENCE" if recovery_terminal_coverage else "REMOTE_PROVIDER_TASK",
                "remote_task_id": remote_id,
                "provider_post_allowed": False,
                "provider_query_allowed": not recovery_terminal_coverage,
                "download_allowed": not recovery_terminal_coverage,
                "maximum_new_submissions": 0,
                "progress": "PROVIDER_TIMEOUT_ZERO_REFUNDED_TERMINAL_COVERAGE_BUILT_NO_REPOST" if recovery_terminal_coverage else "TRANSACTION_BOUND_REMOTE_RUNNING",
                "last_progress_at": now,
                "next_due_at": None if recovery_terminal_coverage else next_due,
                "lease_owner": None if recovery_terminal_coverage else "codex-e40-recovery2-native-text-video",
                "lease_expires_at": None if recovery_terminal_coverage else lease_expires,
                "evidence_ref": portable(RECOVERY_VIDEO_TERMINAL_COVERAGE_QA) if recovery_terminal_coverage else portable(recovery_submission_path),
                "evidence_sha256": sha(RECOVERY_VIDEO_TERMINAL_COVERAGE_QA) if recovery_terminal_coverage else sha(recovery_submission_path),
                "completed_at": now if recovery_terminal_coverage else None,
                "next_action": "Insert the no-visible-lip zero-cost coverage in story order; same-fingerprint repost is forbidden." if recovery_terminal_coverage else "Query/download only this bound task, then run registered original-resolution Q2 with native audio preserved.",
            }
            if task_id in by_id:
                by_id[task_id].update(row)
            else:
                tasks.append(row)
                by_id[task_id] = row
            if not recovery_terminal_coverage:
                recovery_video_active += 1
    if I2V_WAITING_WAVE.is_file():
        waiting_id = "E40-FULL-PERFORMANCE-I2V-WAITING-WAVE-V1"
        waiting_row = {
            "task_id": waiting_id,
            "lane_id": "E40_FULL_PERFORMANCE_I2V_PREPRODUCTION",
            "state": "TERMINAL",
            "wait_scope": "NONE",
            "zero_cost": True,
            "deliverable_type": "FOUR_PRECOMPILED_I2V_NATIVE_DIALOGUE_TASKS",
            "liveness_role": "TERMINAL_EVIDENCE",
            "provider_post_allowed": False,
            "provider_query_allowed": False,
            "download_allowed": False,
            "maximum_new_submissions": 0,
            "progress": "PRECOMPILED_WAITING_PROVIDER_ROUTE_PROOF_NO_POST",
            "last_progress_at": now,
            "completed_at": now,
            "next_due_at": None,
            "evidence_ref": portable(I2V_WAITING_WAVE),
            "evidence_sha256": sha(I2V_WAITING_WAVE),
            "next_action": "Promote only after a recovery2 I2V result passes registered Q2; keep POST disabled meanwhile.",
        }
        if waiting_id in by_id:
            by_id[waiting_id].update(waiting_row)
        else:
            tasks.append(waiting_row)
            by_id[waiting_id] = waiting_row
    if KEYFRAME_REPAIR_WAVE.is_file():
        repair_id = "E40-FULL-PERFORMANCE-KEYFRAME-REPAIR-WAVE-V2"
        repair_row = {
            "task_id": repair_id,
            "lane_id": "E40_FULL_PERFORMANCE_KEYFRAME_PREPRODUCTION",
            "state": "TERMINAL",
            "wait_scope": "NONE",
            "zero_cost": True,
            "deliverable_type": "FIVE_MATERIAL_KEYFRAME_REPAIR_CONTRACTS",
            "liveness_role": "TERMINAL_EVIDENCE",
            "provider_post_allowed": False,
            "provider_query_allowed": False,
            "download_allowed": False,
            "maximum_new_submissions": 0,
            "progress": "PRECOMPILED_WAITING_COST_AND_RETRY_CAP_ADMISSION_NO_POST",
            "last_progress_at": now,
            "completed_at": now,
            "next_due_at": None,
            "evidence_ref": portable(KEYFRAME_REPAIR_WAVE),
            "evidence_sha256": sha(KEYFRAME_REPAIR_WAVE),
            "next_action": "Run registered retry/cost admission before any paid image submit; repaired SHAs require fresh Q1.",
        }
        if repair_id in by_id:
            by_id[repair_id].update(repair_row)
        else:
            tasks.append(repair_row)
            by_id[repair_id] = repair_row
    if KEYFRAME_REPAIR_SUBMISSION.is_file():
        repair_submit = json.loads(KEYFRAME_REPAIR_SUBMISSION.read_text(encoding="utf-8"))
        repair_q1_rows = {}
        if KEYFRAME_REPAIR_Q1.is_file():
            repair_q1_rows = {
                row["task_key"]: row
                for row in json.loads(KEYFRAME_REPAIR_Q1.read_text(encoding="utf-8")).get("results") or []
            }
        for item in repair_submit.get("results") or []:
            remote_id = item.get("task_id")
            if not remote_id:
                continue
            remote_row_id = f"{item['task_key']}-REMOTE"
            q1_row = repair_q1_rows.get(item["task_key"])
            terminal = q1_row is not None
            remote_row = {
                "task_id": remote_row_id,
                "lane_id": "E40_FULL_PERFORMANCE_KEYFRAME_REPAIR",
                "state": "TERMINAL" if terminal else "REMOTE_WAIT",
                "wait_scope": "NONE" if terminal else "TASK_LOCAL",
                "zero_cost": False,
                "deliverable_type": "NATIVE_REGISTRY_IDENTITY_REPAIR_KEYFRAME",
                "liveness_role": "TERMINAL_EVIDENCE" if terminal else "REMOTE_PROVIDER_TASK",
                "remote_task_id": remote_id,
                "provider_post_allowed": False,
                "provider_query_allowed": not terminal,
                "download_allowed": not terminal,
                "maximum_new_submissions": 0,
                "progress": q1_row["downstream_status"] if terminal else "TRANSACTION_BOUND_REMOTE_RUNNING",
                "last_progress_at": now,
                "next_due_at": None if terminal else next_due,
                "lease_owner": None if terminal else "codex-e40-keyframe-repair",
                "lease_expires_at": None if terminal else lease_expires,
                "evidence_ref": q1_row["admission_result"] if terminal else portable(KEYFRAME_REPAIR_SUBMISSION),
                "evidence_sha256": q1_row["admission_result_sha256"] if terminal else sha(KEYFRAME_REPAIR_SUBMISSION),
                "next_action": "Isolate failed repair SHA; no video submit." if terminal else "Query/download only this task, then run fresh exact-SHA registered Q1; never reuse the failed image.",
            }
            if remote_row_id in by_id:
                by_id[remote_row_id].update(remote_row)
            else:
                tasks.append(remote_row)
                by_id[remote_row_id] = remote_row
            if not terminal:
                keyframe_repair_active += 1
    scheduler.update({
        "updated_at": now,
        "status": "ACTIVE_RECOVERY2_NATIVE_TEXT_VIDEO_REMOTE_WAIT" if recovery_video_active else "ACTIVE_TERMINAL_COVERAGE_LOCAL_SUCCESSORS",
        "target_slots": 3,
        "real_active_handle_count": (0 if credit_terminal else 1) + (0 if audio_terminal else 1) + (0 if asr_terminal else 1) + (0 if video_submit_terminal else 1) + (0 if video_credit_terminal else 1) + (1 if pilot_active else 0) + (1 if final_active else 0) + recovery_video_active + keyframe_repair_active,
    })
    scheduler.setdefault("heartbeat_integration", {}).update({
        "state": "ACTIVE",
        "real_active_handle_count": scheduler["real_active_handle_count"],
        "episode_terminal": False,
        "blocking_units": ["R01", "R06A", "R07", "R08"],
        "解除条件": "Continue equivalent coverage for the remaining missing full-performance units, then assemble and run full-episode registered QA.",
    })
    write(SCHEDULER, scheduler)

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue.update({
        "updated_at": now,
        "mode": "FULL_PERFORMANCE_TERMINAL_COVERAGE_AND_ASSEMBLY",
        "status": "ACTIVE_TWO_BOUND_RECOVERY_NATIVE_TEXT_VIDEOS" if recovery_video_active else "ACTIVE_LOCAL_SUCCESSORS_NO_REMOTE",
        "target_slots": 3,
        "real_active_handle_count": scheduler["real_active_handle_count"],
        "next_action": "Compile the next eligible missing full-performance unit after R04 coverage was inserted in sequence order; no V4 and no release of the 23.404-second candidate." if ASSEMBLY_V3_QA.is_file() else "Insert the admitted R04 zero-cost visual coverage into assembly and continue missing full-performance units; no V4." if R04_TERMINAL_COVERAGE_QA.is_file() else "Harvest the bound R04 final image-to-video native-dialogue attempt; if it passes provider and Q2, expand only to eligible units. Failure forces coverage with no V4.",
    })
    queue["latest_e40_full_performance_i2v_native_text_pilot_v2"] = {
        "manifest": portable(I2V_PILOT) if I2V_PILOT.is_file() else None,
        "manifest_sha256": sha(I2V_PILOT) if I2V_PILOT.is_file() else None,
        "precheck": portable(I2V_PILOT_PRECHECK) if I2V_PILOT_PRECHECK.is_file() else None,
        "precheck_sha256": sha(I2V_PILOT_PRECHECK) if I2V_PILOT_PRECHECK.is_file() else None,
        "remote_task_id": pilot_tx.get("task_id") if I2V_PILOT.is_file() and len(pilot_transactions) == 1 else None,
        "status": "TERMINAL_FAILED_REFUNDED" if pilot_terminal else "REMOTE_RUNNING" if pilot_active else "NOT_BOUND",
        "credit_status": portable(I2V_PILOT_CREDIT) if I2V_PILOT_CREDIT.is_file() else None,
        "credit_status_sha256": sha(I2V_PILOT_CREDIT) if I2V_PILOT_CREDIT.is_file() else None,
        "duplicate_post_forbidden": True,
        "next_action": "Query/download only this task and run exact-frame plus native-dialogue Q2 before any batch expansion.",
    }
    queue["latest_e40_full_performance_i2v_native_text_final_v3"] = {
        "manifest": portable(I2V_FINAL) if I2V_FINAL.is_file() else None,
        "manifest_sha256": sha(I2V_FINAL) if I2V_FINAL.is_file() else None,
        "precheck": portable(I2V_FINAL_PRECHECK) if I2V_FINAL_PRECHECK.is_file() else None,
        "precheck_sha256": sha(I2V_FINAL_PRECHECK) if I2V_FINAL_PRECHECK.is_file() else None,
        "remote_task_id": final_tx.get("task_id") if I2V_FINAL.is_file() and len(final_transactions) == 1 else None,
        "status": "TERMINAL_FAILED_REFUNDED_SWITCH_COVERAGE_NO_V4" if R04_TERMINAL_COVERAGE_QA.is_file() else "REMOTE_RUNNING_FINAL_ATTEMPT" if final_active else "NOT_BOUND",
        "credit_status": portable(I2V_FINAL_CREDIT) if I2V_FINAL_CREDIT.is_file() else None,
        "credit_status_sha256": sha(I2V_FINAL_CREDIT) if I2V_FINAL_CREDIT.is_file() else None,
        "retry_attempt": 3,
        "no_further_automatic_retry": True,
        "terminal_decision_if_failed": "SWITCH_COVERAGE_NO_V4",
        "duplicate_post_forbidden": True,
        "harvest": portable(I2V_FINAL_HARVEST) if I2V_FINAL_HARVEST.is_file() else None,
        "harvest_sha256": sha(I2V_FINAL_HARVEST) if I2V_FINAL_HARVEST.is_file() else None,
        "terminal_coverage": portable(R04_TERMINAL_COVERAGE) if R04_TERMINAL_COVERAGE.is_file() else None,
        "terminal_coverage_sha256": sha(R04_TERMINAL_COVERAGE) if R04_TERMINAL_COVERAGE.is_file() else None,
        "terminal_coverage_qa": portable(R04_TERMINAL_COVERAGE_QA) if R04_TERMINAL_COVERAGE_QA.is_file() else None,
        "terminal_coverage_qa_sha256": sha(R04_TERMINAL_COVERAGE_QA) if R04_TERMINAL_COVERAGE_QA.is_file() else None,
        "next_action": "Insert terminal coverage into assembly; no V4." if R04_TERMINAL_COVERAGE_QA.is_file() else "Query/download only this final task; completion enters registered Q2, failure terminalizes R04 automatic retry.",
    }
    if ASSEMBLY_V3.is_file() and ASSEMBLY_V3_QA.is_file():
        queue["latest_e40_assembly_candidate_v3"] = {
            "status": "TECHNICAL_PASS_NOT_FINAL_COMPLETE_VIDEO_GATE_FAIL",
            "sequence": portable(ASSEMBLY_V3),
            "sequence_sha256": sha(ASSEMBLY_V3),
            "qa": portable(ASSEMBLY_V3_QA),
            "qa_sha256": sha(ASSEMBLY_V3_QA),
            "duration_seconds": 23.404,
            "canonical_target_seconds": 163,
            "release_allowed": False,
        }
    if final_active and I2V_FINAL_CREDIT.is_file():
        final_credit = json.loads(I2V_FINAL_CREDIT.read_text(encoding="utf-8"))
        queue.setdefault("e40_credits", {}).update({
            "active_remote_video_pay": final_credit.get("actual_charged_credits_known_total"),
            "active_remote_video_task_id": final_tx.get("task_id"),
            "pending_remote_video_task_count": 1,
            "pending_remote_video_task_ids": [final_tx.get("task_id")],
            "status": "R04_I2V_NATIVE_TEXT_FINAL_RUNNING_EXACT_PAY64_REFUND0; ATTEMPT3_NO_V4",
        })
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
        "bound_task_ids": 13,
        "completed_downloaded": 13,
        "q1_admitted": 8,
        "q1_failed": 5,
        "response_lost_pending_ledger": 0,
        "credit_reconciliation_active": not credit_terminal,
        "credit_reconciliation_executor": None if credit_terminal else "unified_exec_session:88090",
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
        "next_action": "Harvest the two newly bound native-text Seedance Fast videos and run registered Q2; never submit video from the five failed keyframe SHAs.",
    }
    queue["latest_e40_recovery2_native_text_videos"] = {
        "status": "REMOTE_RUNNING" if recovery_video_active else "NOT_BOUND",
        "manifest": portable(recovery_manifest_path) if recovery_manifest_path.is_file() else None,
        "manifest_sha256": sha(recovery_manifest_path) if recovery_manifest_path.is_file() else None,
        "submission": portable(recovery_submission_path) if recovery_submission_path.is_file() else None,
        "submission_sha256": sha(recovery_submission_path) if recovery_submission_path.is_file() else None,
        "remote_task_count": recovery_video_active,
        "native_audio_policy": "PRESERVE_SAME_TASK_NATIVE_DIALOGUE_AMBIENCE_FOLEY_SFX_NO_POST_REDUB",
        "next_action": "Query and download without duplicate POST, then registered Q2.",
    }
    if I2V_WAITING_WAVE.is_file():
        waiting = json.loads(I2V_WAITING_WAVE.read_text(encoding="utf-8"))
        queue["latest_e40_i2v_waiting_wave"] = {
            "status": waiting.get("status"),
            "manifest": portable(I2V_WAITING_WAVE),
            "manifest_sha256": sha(I2V_WAITING_WAVE),
            "task_count": len(waiting.get("tasks") or []),
            "provider_post_allowed": False,
            "maximum_new_submissions": 0,
            "next_action": "Promote only after the active I2V route proves provider success and registered-Q2 admission.",
        }
    if KEYFRAME_REPAIR_WAVE.is_file():
        repair = json.loads(KEYFRAME_REPAIR_WAVE.read_text(encoding="utf-8"))
        queue["latest_e40_keyframe_repair_wave"] = {
            "status": repair.get("status"),
            "manifest": portable(KEYFRAME_REPAIR_WAVE),
            "manifest_sha256": sha(KEYFRAME_REPAIR_WAVE),
            "task_count": len(repair.get("tasks") or []),
            "provider_post_allowed": False,
            "maximum_new_submissions": 0,
            "next_action": "Run registered retry/cost admission; after generation, fresh exact-SHA Q1 is mandatory before video.",
        }
    if KEYFRAME_REPAIR_SUBMISSION.is_file():
        repair_submit = json.loads(KEYFRAME_REPAIR_SUBMISSION.read_text(encoding="utf-8"))
        remote_ids = [row.get("task_id") for row in repair_submit.get("results") or [] if row.get("task_id")]
        q1_terminal = KEYFRAME_REPAIR_Q1.is_file()
        queue["latest_e40_keyframe_repair_submission"] = {
            "status": "TERMINAL_Q1_FAIL_NOT_ADMITTED" if q1_terminal else "REMOTE_RUNNING" if remote_ids else "NOT_BOUND",
            "manifest": portable(KEYFRAME_REPAIR_SELECTED),
            "manifest_sha256": sha(KEYFRAME_REPAIR_SELECTED),
            "submission": portable(KEYFRAME_REPAIR_SUBMISSION),
            "submission_sha256": sha(KEYFRAME_REPAIR_SUBMISSION),
            "remote_task_ids": remote_ids,
            "newly_submitted": len(remote_ids),
            "charged_credits": (repair_submit.get("credit_reconciliation") or {}).get("charged_credits"),
            "q1_index": portable(KEYFRAME_REPAIR_Q1) if q1_terminal else None,
            "q1_index_sha256": sha(KEYFRAME_REPAIR_Q1) if q1_terminal else None,
            "duplicate_post_forbidden": True,
            "next_action": "Query/download only, then fresh exact-SHA Q1 before any video compile.",
        }
    write(QUEUE, queue)
    print(json.dumps({"status": "PASS", "scheduler_sha256": sha(SCHEDULER), "queue_sha256": sha(QUEUE), "real_active_handle_count": scheduler["real_active_handle_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
