#!/usr/bin/env python3
"""Persist U04 V3 exactly-once remote submission and task-local wait."""

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
SUBMIT = ROOT / "workflow/tasks/E40_U04_V3_FAST720_EXACTLY_ONCE_SUBMIT_20260814.json"
READINESS = ROOT / "qa/e40_preproduction_20260814/u04_v3_fast720_no_submit_package_v1/E40_U04_V3_FAST720_PAID_READINESS_V1.json"
AUTHORIZED_PRECHECK = ROOT / "qa/e40_preproduction_20260814/u04_v3_fast720_no_submit_package_v1/E40_U04_V3_AUTHORIZED_MANIFEST_INSTALLED_PRECHECK_ONLY_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U04_V3_REMOTE_RUNNING_STATE_20260814.json"
TASK = "E40-U04-V3-ADMITTED-FRAME-FAST720-PREFLIGHT-AND-VIDEO-QA"


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
        task = next((item for item in scheduler["tasks"] if item.get("task_id") == TASK), None)
        if task is None:
            raise SystemExit("FAIL_CLOSED_SCHEDULER_TASK_MISSING")
        task.update({
            "state": "REMOTE_WAIT", "wait_scope": "TASK_LOCAL", "zero_cost": False,
            "maximum_new_submissions": 1, "authorization": True,
            "provider_post_allowed": False, "provider_query_allowed": True, "download_allowed": True,
            "provider_calls": 1, "transactions": 1, "credits": 64,
            "blocked_by": "BOUND_REMOTE_TASK_NOT_YET_TERMINAL",
            "progress": "EXACTLY_ONE_FAST720_POST_TRANSACTION_AND_TASK_ID_BOUND_PAY64_REMOTE_RUNNING",
            "last_progress_at": iso(now),
            "next_action": f"At the next scheduled wake, query only bound task_id {task_id}; if completed download once and run exact-frame, continuity, audio-absence, cadence, OCR and original-resolution human QA. Never resubmit this fingerprint.",
            "lease_expires_at": iso(now + timedelta(hours=3)),
            "next_due_at": iso(now + timedelta(minutes=15)),
            "executor_acknowledged_at": iso(now), "executor_next_wakeup_at": iso(now + timedelta(minutes=15)),
            "evidence_ref": str(SUBMIT.relative_to(ROOT)), "evidence_sha256": sha256(SUBMIT),
            "remote_task_id": task_id, "transaction_path": str(tx_path.relative_to(ROOT)), "transaction_sha256": sha256(tx_path),
        })
        scheduler["updated_at"] = iso(now)
        scheduler["recorded_at"] = iso(now)
        scheduler["scheduler_decision"] = {"global_wait": False, "reason": "U04_V3_BOUND_TASK_LOCAL_REMOTE_WAIT_EXACT_TASK_ID_ONLY"}
        scheduler["heartbeat_integration"]["episode_terminal"] = False
        atomic_json(SCHED, scheduler)
        scheduler_sha = sha256(SCHED)

        queue = json.loads(QUEUE.read_text(encoding="utf-8"))
        queue.update({
            "updated_at": iso(now),
            "mode": "E40_CONTINUOUS_EPISODE_PRODUCTION_U04_V3_TASK_LOCAL_REMOTE_WAIT",
            "status": "E40_U03_ADMITTED_U04_V3_FAST720_EXACTLY_ONCE_BOUND_REMOTE_RUNNING",
            "updated_note_latest": f"U04 V3 passed all fast-only paid gates and exactly one durable submission. Transaction was persisted before POST, task_id {task_id} is bound, authoritative Pay is 64, and no replay is allowed. This lane is task-local REMOTE_WAIT; U18 remains isolated.",
            "next_action": f"At the next scheduled wake query only U04 task_id {task_id}; on completion download once and run mandatory source QA before edit admission.",
            "occupied_scope_count": 2, "real_active_handle_count": 2,
            "blocked_by": "U04_V3_BOUND_REMOTE_TASK_NOT_YET_TERMINAL",
        })
        credits = queue["e40_credits"]
        credits.update({
            "gross_pay": 1577, "net": 1449, "remaining": 8551,
            "video_pay": 1184, "active_remote_video_pay": 64,
            "status": "AUTHORITATIVE_TOTALS_1577_128_1449_U04_V3_PAY64_BOUND_REMOTE_RUNNING",
            "totals_fresh_through": f"U04_V3_TASK_ID_{task_id}_AUTHORITATIVE_PAY64",
            "active_remote_video_task_id": task_id,
            "pending_remote_video_task_count": 1,
            "pending_remote_video_task_ids": [task_id],
        })
        queue["latest_e40_u04_v3_fast720_remote_submission"] = {
            "path": str(SUBMIT.relative_to(ROOT)), "sha256": sha256(SUBMIT),
            "task_id": task_id, "transaction": str(tx_path.relative_to(ROOT)), "transaction_sha256": sha256(tx_path),
            "model": "seedance-2.0-fast", "charged_credits": 64, "status": "REMOTE_RUNNING_TASK_LOCAL_NO_REPLAY",
        }
        queue["task_lane_scheduler"]["sha256"] = scheduler_sha
        queue["task_lane_scheduler"]["heartbeat_integration"]["episode_terminal"] = False
        atomic_json(QUEUE, queue)

    entry = f"""

## {iso(now)} — E40 U04 V3 exactly-once Fast720 submission bound

- U04 V3 no-submit manifest passed the installed authoritative gate after one zero-cost schema repair (`FRAME0_PRE_ENCODE_RAW_RGB_AUTHORITY_REQUIRED`); schema failure was persisted, provider posts=`0`.
- Fresh paid readiness made one exact-task ledger GET against the prior same-model 4-second task and confirmed `seedance-2.0-fast` authoritative price=`64` (`16/s`). Task key, submission fingerprint and transport fingerprint collision counts were all zero; projected E40 net=`1449 <= 10000`.
- Authorized manifest SHA=`{submit['manifest_sha256']}` passed installed precheck with submitted=`0`, then the deployed durable submitter executed exactly once. Transaction `{row['transaction']}` SHA=`{sha256(tx_path)}` recorded intent before POST and immediately bound task_id=`{task_id}`. Submission receipt `{SUBMIT.relative_to(ROOT)}` SHA=`{sha256(SUBMIT)}`; authoritative Pay=`64`, Refund=`0` so far, ambiguity=`NO_AMBIGUOUS_SUBMISSIONS`.
- Scheduler lane `{TASK}` is now task-local REMOTE_WAIT. Next wake queries only this task_id, downloads once if terminal-completed, then runs exact-frame/continuity, audio-absence, cadence, OCR and original-resolution human QA. No replay, no second transaction, no E38/E39 mutation, no upload/release.
"""
    with X2CL.open("a", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.write(entry)
        stream.flush()
        os.fsync(stream.fileno())
    atomic_json(RECEIPT, {
        "schema": "qingshan.e40.u04.v3.remote_running_state.v1",
        "status": "PASS_TASK_LOCAL_REMOTE_WAIT_BOUND_NO_REPLAY",
        "recorded_at": iso(now), "task_id": task_id,
        "submit_receipt_sha256": sha256(SUBMIT), "transaction_sha256": sha256(tx_path),
        "scheduler_sha256": sha256(SCHED), "work_queue_sha256": sha256(QUEUE), "x2cl_sha256": sha256(X2CL),
        "paid_credits": 64, "refund_credits": 0, "net_credits": 64,
    })
    print(json.dumps({"status": "PASS_TASK_LOCAL_REMOTE_WAIT_BOUND_NO_REPLAY", "task_id": task_id, "scheduler_sha256": sha256(SCHED), "work_queue_sha256": sha256(QUEUE)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
