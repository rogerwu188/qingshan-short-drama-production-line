#!/usr/bin/env python3
"""Persist U05 V3 exactly-once remote submission and task-local QA successor."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHED = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
LOCK = ROOT / "workflow/work_queue.json.lock"
X2CL = ROOT / "workflow/CODEX_TO_CLAUDE.md"
SUBMIT = ROOT / "workflow/tasks/E40_U05_V3_FAST720_EXACTLY_ONCE_SUBMIT_20260814.json"
READINESS = ROOT / "qa/e40_preproduction_20260814/u05_v3_fast720_no_submit_package_v1/E40_U05_V3_FAST720_PAID_READINESS_V1.json"
AUTHORIZED_PRECHECK = ROOT / "qa/e40_preproduction_20260814/u05_v3_fast720_no_submit_package_v1/E40_U05_V3_AUTHORIZED_MANIFEST_INSTALLED_PRECHECK_ONLY_V1.json"
FRAME_ADMISSION = ROOT / "workflow/releases/E40_U05_V2_EXACT_START_FRAME_ADMISSION_20260814.json"
FRAME_HUMAN_QA = ROOT / "qa/e40_preproduction_20260814/u05_v2_imagegen_coherent_exact_start_frame_v1/E40_U05_V2_EXACT_START_FRAME_HUMAN_QA_V1.json"
FRAME_OCR_QA = ROOT / "qa/e40_preproduction_20260814/u05_v2_imagegen_coherent_exact_start_frame_v1/E40_U05_V2_EXACT_START_FRAME_OCR_AUDIT_V1.json"
NO_SUBMIT_MANIFEST = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u05_v3_fast720_admitted_frame_v1/E40_U05_V3_FAST720_NO_SUBMIT_MANIFEST_V1.json"
NO_SUBMIT_PRECHECK = ROOT / "qa/e40_preproduction_20260814/u05_v3_fast720_no_submit_package_v1/E40_U05_V3_INSTALLED_PRECHECK_ONLY_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U05_V3_REMOTE_RUNNING_STATE_20260814.json"
SOURCE_TASK = "E40-U05-COHERENT-PERFORMANCE-SOURCE-ACQUISITION-QA"
REMOTE_TASK = "E40-U05-V3-ADMITTED-FRAME-FAST720-NATIVE-DIA004-VIDEO-QA"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def main() -> int:
    submit = json.loads(SUBMIT.read_text(encoding="utf-8"))
    readiness = json.loads(READINESS.read_text(encoding="utf-8"))
    precheck = json.loads(AUTHORIZED_PRECHECK.read_text(encoding="utf-8"))
    if submit.get("status") != "PASS" or submit.get("submitted") != 1 or submit.get("failed") != 0:
        raise SystemExit("FAIL_CLOSED_SUBMIT_RECEIPT")
    if readiness.get("status") != "PASS" or precheck.get("status") != "PASS" or precheck.get("precheck_pass") != 1:
        raise SystemExit("FAIL_CLOSED_PAID_READINESS_OR_AUTHORIZED_PRECHECK")
    row = submit["tasks"][0]
    tx_path = ROOT / row["transaction"]
    tx = json.loads(tx_path.read_text(encoding="utf-8"))
    task_id = row["task_id"]
    credit = submit["credit_reconciliation"]
    if tx.get("state") != "SUBMITTED_TASK_ID_BOUND" or tx.get("task_id") != task_id:
        raise SystemExit("FAIL_CLOSED_TRANSACTION_NOT_BOUND")
    if credit.get("status") != "PASS" or credit.get("charged_credits") != 64 or credit["statement_rows"][0].get("project_id") != task_id:
        raise SystemExit("FAIL_CLOSED_AUTHORITATIVE_CHARGE")

    now = datetime.now(timezone.utc)
    with LOCK.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        scheduler = json.loads(SCHED.read_text(encoding="utf-8"))
        source = next((item for item in scheduler["tasks"] if item.get("task_id") == SOURCE_TASK), None)
        if source is None:
            raise SystemExit("FAIL_CLOSED_SOURCE_TASK_MISSING")
        source.update({
            "state": "TERMINAL",
            "wait_scope": "NONE",
            "terminal_outcome": "PASS_COHERENT_EXACT_START_FRAME_ADMITTED_AND_FAST720_PACKAGE_PREFLIGHT_PASS",
            "progress": "U05_V2_COHERENT_FRAME_HUMAN93_OCR0_ADMITTED_U05_V3_4S_FAST720_PREFLIGHT_PASS",
            "last_progress_at": iso(now),
            "blocked_by": None,
            "next_action": f"Successor {REMOTE_TASK} owns the bound remote task and post-harvest QA.",
            "evidence_ref": str(FRAME_ADMISSION.relative_to(ROOT)),
            "evidence_sha256": sha256(FRAME_ADMISSION),
            "lease_expires_at": iso(now),
            "next_due_at": iso(now),
        })
        remote = next((item for item in scheduler["tasks"] if item.get("task_id") == REMOTE_TASK), None)
        payload = {
            "task_id": REMOTE_TASK,
            "lane_id": "U05_GENERATION_AND_SOURCE_QA",
            "state": "REMOTE_WAIT",
            "wait_scope": "TASK_LOCAL",
            "zero_cost": False,
            "deliverable_type": "U05_FAST720_NATIVE_EXACT_LINE_VIDEO_AND_POST_HARVEST_QA",
            "priority": 173,
            "scope": ["E40", "U05", "SEEDANCE_2_FAST", "EXACT_FIRST_FRAME", "NATIVE_EXACT_LINE", "VIDEO_QA", "NO_RELEASE"],
            "exact_predecessor_task_id": SOURCE_TASK,
            "liveness_role": "PRODUCING",
            "observation_only": False,
            "maximum_new_submissions": 1,
            "authorization": True,
            "provider_post_allowed": False,
            "provider_query_allowed": True,
            "download_allowed": True,
            "provider_calls": 1,
            "transactions": 1,
            "credits": 64,
            "blocked_by": "BOUND_REMOTE_TASK_NOT_YET_TERMINAL",
            "progress": "EXACTLY_ONE_FAST720_POST_TRANSACTION_AND_TASK_ID_BOUND_PAY64_REMOTE_RUNNING",
            "last_progress_at": iso(now),
            "next_action": f"At the next scheduled wake, query only bound task_id {task_id}; if completed download once and run exact-frame, frame0-to-frame1 continuity, exact-line ASR, sole-speaker, natural-speed, visible lip-sync, OCR and original-resolution human QA. Never resubmit this fingerprint.",
            "lease_owner": "codex-e40-production:u05-v3-remote",
            "lease_expires_at": iso(now + timedelta(hours=3)),
            "next_due_at": iso(now + timedelta(minutes=15)),
            "execution_mode": "CONTINUOUS",
            "executor_handle": "automation:e40",
            "executor_task_id": REMOTE_TASK,
            "executor_acknowledged_at": iso(now),
            "executor_next_wakeup_at": iso(now + timedelta(minutes=15)),
            "evidence_ref": str(SUBMIT.relative_to(ROOT)),
            "evidence_sha256": sha256(SUBMIT),
            "remote_task_id": task_id,
            "transaction_path": str(tx_path.relative_to(ROOT)),
            "transaction_sha256": sha256(tx_path),
        }
        if remote is None:
            scheduler["tasks"].append(payload)
        else:
            remote.update(payload)
        scheduler["updated_at"] = iso(now)
        scheduler["recorded_at"] = iso(now)
        scheduler["scheduler_decision"] = {"global_wait": False, "reason": "U05_V3_BOUND_TASK_LOCAL_REMOTE_WAIT_EXACT_TASK_ID_ONLY"}
        scheduler["heartbeat_integration"]["episode_terminal"] = False
        atomic_json(SCHED, scheduler)
        scheduler_sha = sha256(SCHED)

        queue = json.loads(QUEUE.read_text(encoding="utf-8"))
        queue.update({
            "updated_at": iso(now),
            "mode": "E40_CONTINUOUS_EPISODE_PRODUCTION_U05_V3_TASK_LOCAL_REMOTE_WAIT",
            "status": "E40_U04_V6_ADMITTED_U05_V3_FAST720_EXACTLY_ONCE_BOUND_REMOTE_RUNNING",
            "updated_note_latest": f"U05 coherent exact-start frame passed human QA 93 and OCR 0. The 6-second package failed locally with no POST/credit; PF-042 was recorded and the prompt was materially rewritten to 4 seconds. U05 V3 then passed all fast-only gates and exactly one durable submission bound task_id {task_id} with authoritative Pay 64.",
            "next_action": f"At the next scheduled wake query only U05 task_id {task_id}; on completion download once and run mandatory exact-frame, dialogue/lip-sync, OCR and human source QA before edit admission.",
            "occupied_scope_count": 2,
            "real_active_handle_count": 2,
            "blocked_by": "U05_V3_BOUND_REMOTE_TASK_NOT_YET_TERMINAL",
        })
        credits = queue["e40_credits"]
        credits.update({
            "gross_pay": int(credits["gross_pay"]) + 64,
            "net": int(credits["net"]) + 64,
            "remaining": int(credits["remaining"]) - 64,
            "video_pay": int(credits["video_pay"]) + 64,
            "active_remote_video_pay": 64,
            "status": "AUTHORITATIVE_TOTALS_1641_128_1513_U05_V3_PAY64_BOUND_REMOTE_RUNNING",
            "totals_fresh_through": f"U05_V3_TASK_ID_{task_id}_AUTHORITATIVE_PAY64",
            "active_remote_video_task_id": task_id,
            "pending_remote_video_task_count": 1,
            "pending_remote_video_task_ids": [task_id],
        })
        queue["latest_e40_u05_v2_exact_start_frame_admission"] = {
            "path": str(FRAME_ADMISSION.relative_to(ROOT)),
            "sha256": sha256(FRAME_ADMISSION),
            "human_qa": str(FRAME_HUMAN_QA.relative_to(ROOT)),
            "human_qa_sha256": sha256(FRAME_HUMAN_QA),
            "ocr_qa": str(FRAME_OCR_QA.relative_to(ROOT)),
            "ocr_qa_sha256": sha256(FRAME_OCR_QA),
            "status": "PASS_HUMAN93_OCR0",
        }
        queue["latest_e40_u05_v3_fast720_precheck"] = {
            "path": str(NO_SUBMIT_PRECHECK.relative_to(ROOT)),
            "sha256": sha256(NO_SUBMIT_PRECHECK),
            "manifest": str(NO_SUBMIT_MANIFEST.relative_to(ROOT)),
            "manifest_sha256": sha256(NO_SUBMIT_MANIFEST),
            "status": "PASS_4S_AFTER_PF042_MATERIAL_REWRITE",
        }
        queue["latest_e40_u05_v3_fast720_remote_submission"] = {
            "path": str(SUBMIT.relative_to(ROOT)),
            "sha256": sha256(SUBMIT),
            "task_id": task_id,
            "transaction": str(tx_path.relative_to(ROOT)),
            "transaction_sha256": sha256(tx_path),
            "model": "seedance-2.0-fast",
            "charged_credits": 64,
            "status": "REMOTE_RUNNING_TASK_LOCAL_NO_REPLAY",
        }
        queue["task_lane_scheduler"]["sha256"] = scheduler_sha
        queue["task_lane_scheduler"]["heartbeat_integration"]["episode_terminal"] = False
        atomic_json(QUEUE, queue)

    entry = f"""

## {iso(now)} — E40 U05 coherent frame admitted and V3 Fast720 exactly-once submission bound

- Built one coherent U05 start frame with Chenji in white robe, exactly two blank pages, visible table contact gap, curtain-directed gaze and dialogue onset. Source SHA=`355271d8462a08be47a4e51ed99a5b05eb3c504dfdfbf7dc8847af1e61dde3e2`; 720x1280 SHA=`4f5205fa8a001b1943a322ee146ec19f4a62c530a9b1286bf921e327c2dbcc7e`; original-image human QA=`93`, OCR recognitions=`0`; admission `{FRAME_ADMISSION.relative_to(ROOT)}` SHA=`{sha256(FRAME_ADMISSION)}`.
- The initial 6-second package failed locally on `ATOMIC_ACTION_DURATION_INVITES_SLOW_MOTION`; provider posts=`0`, transactions=`0`, credits=`0`. Failure memory PF-042 was persisted, then the prompt was materially rewritten to a 4-second real-time action with contact complete by `0.8s`, exact line complete by `3.35s`, and an active reaction tail. Rewritten no-submit manifest SHA=`{sha256(NO_SUBMIT_MANIFEST)}` and installed precheck SHA=`{sha256(NO_SUBMIT_PRECHECK)}` both passed.
- Fresh same-model paid readiness confirmed `seedance-2.0-fast` price=`64` (`16/s`), zero task/submission/transport collision, projected net within cap, and exactly one 4-second generation. Authorized manifest SHA=`{submit['manifest_sha256']}` passed installed precheck with submitted=`0`.
- The deployed durable submitter executed exactly once. Transaction `{row['transaction']}` SHA=`{sha256(tx_path)}` recorded intent before POST and immediately bound task_id=`{task_id}`. Submission receipt `{SUBMIT.relative_to(ROOT)}` SHA=`{sha256(SUBMIT)}`; authoritative Pay=`64`, Refund=`0`, ambiguity=`NO_AMBIGUOUS_SUBMISSIONS`.
- Scheduler successor `{REMOTE_TASK}` is task-local REMOTE_WAIT. Next wake queries only this task_id, downloads once if terminal-completed, then runs exact-frame, frame0 continuity, exact-line ASR, sole-speaker, natural speed, visible lip-sync, OCR and original-resolution human QA. No replay, no E38/E39 mutation, and no release before admission.
"""
    with X2CL.open("a", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.write(entry)
        stream.flush()
        os.fsync(stream.fileno())
    atomic_json(RECEIPT, {
        "schema": "qingshan.e40.u05.v3.remote_running_state.v1",
        "status": "PASS_TASK_LOCAL_REMOTE_WAIT_BOUND_NO_REPLAY",
        "recorded_at": iso(now),
        "task_id": task_id,
        "submit_receipt_sha256": sha256(SUBMIT),
        "transaction_sha256": sha256(tx_path),
        "scheduler_sha256": sha256(SCHED),
        "work_queue_sha256": sha256(QUEUE),
        "x2cl_sha256": sha256(X2CL),
        "paid_credits": 64,
        "refund_credits": 0,
        "net_credits": 64,
    })
    print(json.dumps({"status": "PASS_TASK_LOCAL_REMOTE_WAIT_BOUND_NO_REPLAY", "task_id": task_id, "scheduler_sha256": sha256(SCHED), "work_queue_sha256": sha256(QUEUE)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
