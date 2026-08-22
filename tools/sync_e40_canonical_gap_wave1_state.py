#!/usr/bin/env python3
"""Idempotently sync harvested gap keyframes and bound gap videos into E40 state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULER = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
Q1 = ROOT / "qa/e40_remake_20260822/canonical_gap_keyframes_wave1_v1/q1_registered/E40_CANONICAL_GAP_KEYFRAMES_WAVE1_Q1_INDEX_V1.json"
SUBMISSION = ROOT / "qa/e40_remake_20260822/canonical_gap_videos_wave1_v1/E40_CANONICAL_GAP_VIDEOS_WAVE1_SUBMISSION_V1.json"
MARKER = "E40_CANONICAL_GAP_VIDEOS_WAVE1_SUBMITTED_128"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    now = datetime.now(timezone.utc)
    stamp = now.isoformat().replace("+00:00", "Z")
    q1 = json.loads(Q1.read_text(encoding="utf-8"))
    submission = json.loads(SUBMISSION.read_text(encoding="utf-8"))
    if q1.get("status") != "ADMITTED_2_FAILED_1" or submission.get("status") != "PASS":
        raise SystemExit("Expected Q1 and submission terminal evidence is absent")

    scheduler = json.loads(SCHEDULER.read_text(encoding="utf-8"))
    q1_by_key = {row["task_key"]: row for row in q1["results"]}
    for task in scheduler.get("tasks") or []:
        row = q1_by_key.get(task.get("task_id"))
        if row:
            task.update({
                "state": "TERMINAL",
                "wait_scope": "NONE_TERMINAL",
                "progress": row["downstream_status"],
                "terminal_at": stamp,
                "evidence_ref": row["admission_result"],
                "evidence_sha256": row["admission_result_sha256"],
                "next_action": "Video submission is allowed only for exact-SHA admitted rows; failed S04 remains isolated.",
                "lease_owner": None,
                "lease_expires_at": None,
                "next_due_at": None,
            })

    by_id = {task.get("task_id"): task for task in scheduler.get("tasks") or []}
    for row in submission["tasks"]:
        lane_id = row["task_key"].replace("-VIDEO-V1", "-VIDEO")
        task = by_id.get(row["task_key"])
        payload = {
            "task_id": row["task_key"],
            "lane_id": lane_id,
            "state": "REMOTE_WAIT",
            "wait_scope": "TASK_LOCAL",
            "zero_cost": False,
            "deliverable_type": "SEEDANCE_FAST_CANONICAL_GAP_VIDEO_WITH_SAME_TASK_NATIVE_AUDIO",
            "priority": 240,
            "remote_task_id": row["task_id"],
            "provider": "giggle",
            "model": "seedance-2.0-fast",
            "liveness_role": "PRODUCING",
            "observation_only": False,
            "provider_post_allowed": False,
            "provider_query_allowed": True,
            "download_allowed": True,
            "maximum_new_submissions": 0,
            "transactions": 1,
            "credits": 64,
            "progress": "SUBMITTED_TASK_ID_BOUND",
            "last_progress_at": stamp,
            "next_action": f"Query only bound task_id {row['task_id']}; download once on completion, then run exact-frame, continuity, identity, space, action-state, period, OCR and native-audio Q2.",
            "lease_owner": "automation:e40",
            "lease_expires_at": (now + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
            "next_due_at": (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            "evidence_ref": str(SUBMISSION.relative_to(ROOT)),
            "evidence_sha256": sha(SUBMISSION),
        }
        if task:
            task.update(payload)
        else:
            scheduler.setdefault("tasks", []).append(payload)
    scheduler.update({
        "updated_at": stamp,
        "recorded_at": stamp,
        "real_active_handle_count": 2,
        "target_slots": 2,
        "status": "ACTIVE_CANONICAL_GAP_VIDEOS_WAVE1_REMOTE",
        "legal_blocker": None,
        "standby": False,
    })
    write(SCHEDULER, scheduler)

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    credits = queue.setdefault("e40_credits", {})
    already = queue.get("latest_canonical_gap_video_wave1_state") == MARKER
    if not already:
        credits["gross_pay"] = int(credits.get("gross_pay", 0)) + 128
        credits["net"] = int(credits.get("net", 0)) + 128
        credits["remaining"] = int(credits.get("cap", 10000)) - int(credits["net"])
        credits["video_pay"] = int(credits.get("video_pay", 0)) + 128
    task_ids = [row["task_id"] for row in submission["tasks"]]
    credits.update({
        "active_remote_image_pay": 0,
        "pending_remote_image_task_count": 0,
        "pending_remote_image_task_ids": [],
        "pending_remote_image_credit_amount": 0,
        "active_remote_video_pay": 128,
        "active_remote_video_task_id": None,
        "pending_remote_video_task_count": 2,
        "pending_remote_video_task_ids": task_ids,
        "status": "CANONICAL_GAP_VIDEO_WAVE1_TWO_BOUND_PAY128",
    })
    queue.update({
        "updated_at": stamp,
        "target_slots": 2,
        "occupied_scope_count": 2,
        "real_active_handle_count": 2,
        "status": "ACTIVE_CANONICAL_GAP_VIDEOS_WAVE1_REMOTE",
        "updated_note_latest": "Three gap keyframes harvested: S01/S02 exact-SHA Q1 admitted, S04 isolated for registered action-state failure. Two admitted Seedance Fast I2V tasks passed 2/2 precheck, were transaction-first submitted, and are bound to real task_ids; batch Pay128.",
        "blocked_by": None,
        "next_action": "Harvest only the two bound canonical-gap video task_ids; completed items download once and enter registered Q2. Continue later distinct gap-shot preproduction in parallel; never duplicate POST or submit failed S04.",
        "latest_canonical_gap_video_wave1_state": MARKER,
    })
    task_lane = queue.setdefault("task_lane_scheduler", {})
    task_lane.update({
        "path": str(SCHEDULER.relative_to(ROOT)),
        "sha256": sha(SCHEDULER),
        "status": scheduler["status"],
        "real_active_handle_count": 2,
    })
    write(QUEUE, queue)
    print(json.dumps({"scheduler_sha256": sha(SCHEDULER), "work_queue_sha256": sha(QUEUE), "active": 2}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
