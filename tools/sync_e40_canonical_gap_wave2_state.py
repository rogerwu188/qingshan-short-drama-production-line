#!/usr/bin/env python3
"""Idempotently add bound wave-two keyframes beside active E40 gap videos."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULER = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
SUBMISSION = ROOT / "qa/e40_remake_20260822/canonical_gap_keyframes_wave2_v1/E40_CANONICAL_GAP_KEYFRAMES_WAVE2_SUBMISSION_V1.json"
Q1 = ROOT / "qa/e40_remake_20260822/canonical_gap_keyframes_wave2_v1/q1_registered/E40_CANONICAL_GAP_KEYFRAMES_WAVE2_Q1_INDEX_V1.json"
MARKER = "E40_CANONICAL_GAP_KEYFRAMES_WAVE2_SUBMITTED_22"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    submission = json.loads(SUBMISSION.read_text(encoding="utf-8"))
    if submission.get("status") != "PASS" or submission.get("submitted") != 2:
        raise SystemExit("Wave-two submission is not fully task-id bound")
    now = datetime.now(timezone.utc)
    stamp = now.isoformat().replace("+00:00", "Z")
    scheduler = json.loads(SCHEDULER.read_text(encoding="utf-8"))
    by_id = {row.get("task_id"): row for row in scheduler.get("tasks") or []}
    for row in submission["results"]:
        payload = {
            "task_id": row["task_key"],
            "lane_id": row["task_key"].replace("-KEYFRAME-V1", "-KEYFRAME"),
            "state": "REMOTE_WAIT",
            "wait_scope": "TASK_LOCAL",
            "zero_cost": False,
            "deliverable_type": "CANONICAL_GAP_EXACT_SHA_KEYFRAME_FOR_FRESH_Q1",
            "priority": 241,
            "remote_task_id": row["task_id"],
            "provider": "giggle",
            "model": "gpt-image-2-pro",
            "liveness_role": "PRODUCING",
            "observation_only": False,
            "provider_post_allowed": False,
            "provider_query_allowed": True,
            "download_allowed": True,
            "maximum_new_submissions": 0,
            "transactions": 1,
            "credits": 11,
            "progress": "SUBMITTED_TASK_ID_BOUND",
            "last_progress_at": stamp,
            "next_action": f"Query only bound task_id {row['task_id']}; download once on completion and run exact-SHA registered Q1 before any video compile.",
            "lease_owner": "automation:e40",
            "lease_expires_at": (now + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
            "next_due_at": (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            "evidence_ref": str(SUBMISSION.relative_to(ROOT)),
            "evidence_sha256": sha(SUBMISSION),
        }
        if row["task_key"] in by_id:
            by_id[row["task_key"]].update(payload)
        else:
            scheduler.setdefault("tasks", []).append(payload)
    q1 = json.loads(Q1.read_text(encoding="utf-8")) if Q1.is_file() else None
    if q1 and len(q1.get("results") or []) == 2:
        decisions = {row["task_key"]: row for row in q1["results"]}
        for task in scheduler["tasks"]:
            decision = decisions.get(task.get("task_id"))
            if decision:
                task.update({
                    "state": "TERMINAL",
                    "wait_scope": "NONE_TERMINAL",
                    "progress": decision["downstream_status"],
                    "terminal_at": stamp,
                    "next_action": (
                        "Exact-SHA Q1 admitted; compile video independently under the video paid-entrypoint."
                        if decision["downstream_status"] == "ADMITTED_FOR_VIDEO_SUBMIT"
                        else "Exact-SHA Q1 failed; no video submit. Correct identity transport/compositing before retry-cap and episode-budget evaluation."
                    ),
                    "evidence_ref": decision["admission_result"],
                    "evidence_sha256": decision["admission_result_sha256"],
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "next_due_at": None,
                })
    for task in scheduler["tasks"]:
        if task.get("state") == "REMOTE_WAIT" and task.get("remote_task_id"):
            task["lease_owner"] = "automation:e40"
            task["lease_expires_at"] = (now + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
            task["next_due_at"] = (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
            task["last_progress_at"] = stamp
    active = [row for row in scheduler["tasks"] if row.get("state") in {"REMOTE_WAIT", "RUNNING", "QA"} and (row.get("remote_task_id") or row.get("executor_handle"))]
    scheduler.update({"updated_at": stamp, "recorded_at": stamp, "real_active_handle_count": len(active), "target_slots": len(active), "status": "ACTIVE_CANONICAL_GAP_VIDEO_AND_KEYFRAME_PARALLEL", "legal_blocker": None, "standby": False})
    write(SCHEDULER, scheduler)

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    credits = queue.setdefault("e40_credits", {})
    if queue.get("latest_canonical_gap_keyframe_wave2_state") != MARKER:
        credits["gross_pay"] = int(credits.get("gross_pay", 0)) + 22
        credits["net"] = int(credits.get("net", 0)) + 22
        credits["remaining"] = int(credits.get("cap", 10000)) - int(credits["net"])
        credits["image_pay"] = int(credits.get("image_pay", 0)) + 22
    image_ids = [row["task_id"] for row in submission["results"]]
    images_terminal = bool(q1 and len(q1.get("results") or []) == 2)
    admitted_count = int(q1.get("admitted_count") or 0) if q1 else 0
    credits.update({"active_remote_image_pay": 0 if images_terminal else 22, "pending_remote_image_task_count": 0 if images_terminal else 2, "pending_remote_image_task_ids": [] if images_terminal else image_ids, "pending_remote_image_credit_amount": 0 if images_terminal else 22, "status": "GAP_VIDEO_WAVE1_RUNNING_KEYFRAME_WAVE2_Q1_TERMINAL" if images_terminal else "GAP_VIDEO_WAVE1_PAY128_AND_KEYFRAME_WAVE2_PAY22_RUNNING"})
    queue.update({
        "updated_at": stamp,
        "target_slots": len(active),
        "occupied_scope_count": len(active),
        "real_active_handle_count": len(active),
        "status": "ACTIVE_CANONICAL_GAP_VIDEO_AND_KEYFRAME_PARALLEL",
        "updated_note_latest": f"Two canonical-gap videos remain provider-running. Two later keyframes completed and were terminalized by exact-SHA registered Q1: admitted={admitted_count}, failed={2 - admitted_count}. S03/S04 may not enter video while identity transport is unresolved.",
        "blocked_by": None,
        "next_action": "Harvest only the two bound video task_ids; completed videos enter registered Q2. Do not compile S03/S04 video: rebuild their keyframes only after identity-authoritative transport/compositing and retry-budget checks.",
        "latest_canonical_gap_keyframe_wave2_state": MARKER,
    })
    queue.setdefault("task_lane_scheduler", {}).update({"path": str(SCHEDULER.relative_to(ROOT)), "sha256": sha(SCHEDULER), "status": scheduler["status"], "real_active_handle_count": len(active)})
    write(QUEUE, queue)
    print(json.dumps({"active": len(active), "scheduler_sha256": sha(SCHEDULER), "work_queue_sha256": sha(QUEUE)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
