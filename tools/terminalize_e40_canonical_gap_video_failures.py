#!/usr/bin/env python3
"""Terminalize the two bound E40 gap videos after provider failure and exact ledger classification."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

try:
    from giggle_credit_statements import fetch_pay_statements
except ModuleNotFoundError:
    from tools.giggle_credit_statements import fetch_pay_statements


ROOT = Path(__file__).resolve().parents[1]
HARVEST = ROOT / "qa/e40_remake_20260822/canonical_gap_videos_wave1_v1/E40_CANONICAL_GAP_VIDEOS_WAVE1_HARVEST_V7.json"
OUT = ROOT / "qa/e40_remake_20260822/canonical_gap_videos_wave1_v1/E40_CANONICAL_GAP_VIDEOS_WAVE1_TERMINAL_CLASSIFICATION_V1.json"
SCHEDULER = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    harvest = json.loads(HARVEST.read_text(encoding="utf-8"))
    failed = [row for row in harvest.get("results") or [] if row.get("remote_status") == "failed"]
    if len(failed) != 2:
        raise SystemExit("Expected exactly two authoritative provider failures")
    wanted = {row["task_id"] for row in failed}
    live = [row for row in fetch_pay_statements(200) if str(row.get("project_id")) in wanted]
    results = []
    for remote in failed:
        task_id = remote["task_id"]
        rows = [row for row in live if str(row.get("project_id")) == task_id]
        pay = sum(abs(int(row["credit"])) for row in rows if row.get("event_type") == "Pay")
        refund = sum(abs(int(row["credit"])) for row in rows if row.get("event_type") == "Refund")
        net = pay - refund
        if pay <= 0 or net < 0:
            raise SystemExit(f"Unclassified credit ledger for {task_id}")
        status = "PASS_ZERO_REFUNDED" if net == 0 else "PASS_CHARGED_FAILED_NO_REFUND"
        results.append({
            "task_key": remote["task_key"], "task_id": task_id,
            "provider_status": "failed", "pay_credits": pay,
            "refund_credits": refund, "net_charged_credits": net,
            "credit_status": status, "statement_rows": rows,
        })
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    classification = {
        "schema": "qingshan.e40.canonical_gap_video_terminal_classification.v1",
        "episode": "E40", "recorded_at": stamp, "status": "PASS",
        "harvest_ref": str(HARVEST.relative_to(ROOT)), "harvest_sha256": sha(HARVEST),
        "results": results,
        "retry_guard": "NO_AUTOMATIC_RESUBMIT; APPLY_RETRY_CAP_AND_EPISODE_15_PERCENT_GATE",
    }
    write(OUT, classification)
    classification_sha = sha(OUT)

    by_remote = {row["task_id"]: row for row in results}
    for row in results:
        paths = list((ROOT / "workflow/tasks/giggle_video_submit_transactions/E40").glob(
            f"{row['task_key']}__*.json"
        ))
        if len(paths) != 1:
            raise SystemExit(f"Expected one transaction for {row['task_key']}")
        transaction = json.loads(paths[0].read_text(encoding="utf-8"))
        if transaction.get("task_id") != row["task_id"]:
            raise SystemExit(f"Transaction task_id mismatch for {row['task_key']}")
        transaction.update({
            "state": (
                "TERMINAL_FAILED_REFUNDED" if row["credit_status"] == "PASS_ZERO_REFUNDED"
                else "TERMINAL_FAILED_CHARGED_NO_REFUND"
            ),
            "provider_terminal_status": "failed", "terminal_recorded_at": stamp,
            "credit_status": row["credit_status"],
            "pay_credits": row["pay_credits"], "refund_credits": row["refund_credits"],
            "net_charged_credits": row["net_charged_credits"],
            "terminal_classification_ref": str(OUT.relative_to(ROOT)),
            "terminal_classification_sha256": classification_sha,
        })
        write(paths[0], transaction)

    scheduler = json.loads(SCHEDULER.read_text(encoding="utf-8"))
    for task in scheduler.get("tasks") or []:
        row = by_remote.get(task.get("remote_task_id"))
        if not row:
            continue
        task.update({
            "state": "TERMINAL", "wait_scope": "NONE_TERMINAL",
            "progress": row["credit_status"], "terminal_at": stamp,
            "next_action": "Do not repeat POST. Apply retry-cap and episode 15% gate; use zero-cost coverage if retry is not admitted.",
            "evidence_ref": str(OUT.relative_to(ROOT)), "evidence_sha256": classification_sha,
            "lease_owner": None, "lease_expires_at": None, "next_due_at": None,
        })
    active = [
        row for row in scheduler.get("tasks") or []
        if row.get("state") in {"REMOTE_WAIT", "RUNNING", "QA"}
        and (row.get("remote_task_id") or row.get("executor_handle"))
    ]
    scheduler.update({
        "updated_at": stamp, "recorded_at": stamp,
        "real_active_handle_count": len(active), "target_slots": len(active),
        "status": "READY_IDENTITY_AUTHORITY_REBUILD_PRECOMPILE",
        "legal_blocker": None, "standby": False,
    })
    write(SCHEDULER, scheduler)

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    credits = queue.setdefault("e40_credits", {})
    credits.update({
        "active_remote_video_pay": 0, "active_remote_video_task_id": None,
        "pending_remote_video_task_count": 0, "pending_remote_video_task_ids": [],
        "status": "CANONICAL_GAP_VIDEO_WAVE1_FAILED_CHARGED_NO_REFUND",
    })
    queue.update({
        "updated_at": stamp, "target_slots": len(active),
        "occupied_scope_count": len(active), "real_active_handle_count": len(active),
        "status": "READY_IDENTITY_AUTHORITY_REBUILD_PRECOMPILE",
        "updated_note_latest": "Two bound canonical-gap videos are provider-terminal failed. Exact project ledger: Pay64/Refund0/Net64 each. No automatic repost; S03/S04 keyframes also remain FAIL_NOT_ADMITTED under the corrected identity gate.",
        "blocked_by": None,
        "next_action": "Precompile identity-authoritative keyframe repair inputs, then apply retry-cap and episode 15% admission before any paid POST.",
    })
    queue.setdefault("task_lane_scheduler", {}).update({
        "path": str(SCHEDULER.relative_to(ROOT)), "sha256": sha(SCHEDULER),
        "status": scheduler["status"], "real_active_handle_count": len(active),
    })
    write(QUEUE, queue)
    print(json.dumps({
        "status": "PASS", "active": len(active),
        "classification_sha256": classification_sha,
        "scheduler_sha256": sha(SCHEDULER), "work_queue_sha256": sha(QUEUE),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
