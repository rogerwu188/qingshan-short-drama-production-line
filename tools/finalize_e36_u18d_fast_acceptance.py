#!/usr/bin/env python3
"""Record U18D raw failures, zero-credit repairs, and the E36 fallback handoff."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
QA = ROOT / "qa/e36_v2_stills_repair_20260729/u18_video_runtime"
RAW = PROD / "video_repair_v2_outputs/E36_E36-CW-U18D-VIDEO-V1-FAST_4454e3c5-9600-4339-afa0-00a4e40d8b0e.mp4"
DEDUP = PROD / "video_repair_v2_outputs/E36_E36-CW-U18D-VIDEO-V1-FAST_4454e3c5-9600-4339-afa0-00a4e40d8b0e_DEDUP_FRAMES.mp4"
FIXED = PROD / "video_repair_v2_outputs/E36_E36-CW-U18D-VIDEO-V1-FAST_4454e3c5-9600-4339-afa0-00a4e40d8b0e_DEDUP_FRAMES_TEXTFREE_CROP.mp4"
CONTACT = QA / "E36_U18D_DEDUP_TEXTFREE_CROP_CONTACT_SHEET_V1.jpg"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_status(path: Path, status: str) -> dict:
    payload = read(path)
    if payload.get("status") != status:
        raise SystemExit(f"required status missing: {path}: {payload.get('status')} != {status}")
    return payload


raw_cadence = require_status(QA / "E36-CW-U18D-VIDEO-V1-FAST_frame_cadence.json", "FAIL")
dedup_cadence = require_status(QA / "E36-CW-U18D-VIDEO-V1-FAST_DEDUP_FRAMES_frame_cadence.json", "PASS")
cadence = require_status(QA / "E36_U18D_DEDUP_TEXTFREE_CROP_FRAME_CADENCE_V1.json", "PASS")
ocr = require_status(QA / "E36_U18D_DEDUP_TEXTFREE_CROP_OCR_V1.json", "PASS")
dialogue = require_status(QA / "E36_U18D_DEDUP_TEXTFREE_CROP_NATIVE_DIALOGUE_V1.json", "PASS")
repair = read(QA / "E36-CW-U18D-VIDEO-V1-FAST_DEDUP_FRAMES_REPAIR.json")
receipt = read(PROD / "E36_U18D_EPISODE_SINGLE_UNIT_FAST_RECEIPT_V1_REAL.json")
task = receipt["tasks"][0]
attempt = task["credit_attempts"][0]
if attempt.get("actual_charged_credits") != 96 or not attempt.get("success"):
    raise SystemExit("U18D exact Pay96 evidence is missing")
if sha(RAW) != "837a1b4aa81be2c516fd0967d429d994c1517dfc4e34af6b42cf845e87ad57b9":
    raise SystemExit("U18D raw source changed")
if sha(DEDUP) != "3210f44b06ce70033dd59c78dac93f7f657c8fbcaa68b8ed0e2626031c8e98f4":
    raise SystemExit("U18D dedup source changed")
if dialogue.get("recall_score") != 1.0:
    raise SystemExit("U18D exact dialogue recall is not 1.0")

write(QA / "E36_U18D_RAW_CADENCE_QA_FAIL_V1.json", {
    "schema": "qingshan.manual_source_video_qa.v1",
    "episode": "E36", "unit_id": "U18", "source_segment_id": "U18D",
    "status": "FAIL_REPAIRABLE_PERIODIC_DUPLICATE_CADENCE",
    "task_id": task["task_id"], "exact_charge_credits": 96,
    "raw_video": rel(RAW), "raw_video_sha256": sha(RAW),
    "cadence_report": rel(QA / "E36-CW-U18D-VIDEO-V1-FAST_frame_cadence.json"),
    "cadence_failures": raw_cadence["failures"],
    "confirmed_periodic_chain_count": raw_cadence["periodic_duplicates"]["periodic_chain_count"],
    "repairability": "Delete only mpdecimate-confirmed duplicate video frames and the matching audio intervals; do not interpolate, slow, pad, or regenerate.",
    "unchanged_paid_retry_allowed": False,
})

write(QA / "E36_U18D_DEDUP_MANUAL_QA_FAIL_V1.json", {
    "schema": "qingshan.manual_source_video_qa.v1",
    "episode": "E36", "unit_id": "U18", "source_segment_id": "U18D",
    "status": "FAIL_REPAIRABLE_UNAUTHORIZED_VISIBLE_PAPER_TEXT",
    "source_task_id": task["task_id"], "new_repair_credits": 0,
    "dedup_video": rel(DEDUP), "dedup_video_sha256": sha(DEDUP),
    "cadence_repair_report": rel(QA / "E36-CW-U18D-VIDEO-V1-FAST_DEDUP_FRAMES_REPAIR.json"),
    "cadence_repair_result": dedup_cadence["status"],
    "direct_review": {
        "status": "FAIL",
        "method": "FULL_FRAME_REVIEW_PLUS_REVIEW_IMAGE",
        "failure": "A written ticket with multiple visible Chinese glyphs occupies the lower frame despite the no-paper/no-text contract.",
        "automated_ocr_limit": "The source OCR excludes the bottom 20 percent and cannot override the direct full-frame finding.",
        "repairability": "A fixed 528x938 crop from x96,y0 removes the complete ticket while preserving both faces, the messenger, candle and period room.",
    },
    "unchanged_paid_retry_allowed": False,
})

write(QA / "E36_U18D_DEDUP_TEXTFREE_CROP_MANUAL_QA_V1.json", {
    "schema": "qingshan.manual_source_video_qa.v1",
    "episode": "E36", "unit_id": "U18", "source_segment_id": "U18D",
    "status": "PASS_ACCEPTED_U18D_ONLY",
    "source_task_id": task["task_id"], "source_charge_credits": 96, "new_repair_credits": 0,
    "accepted_video": rel(FIXED), "accepted_video_sha256": sha(FIXED),
    "canonical_dialogue": "死案不会付钱。付钱的，是替死人管账的活人。",
    "native_dialogue_transcript": dialogue["transcript"],
    "native_dialogue_recall": dialogue["recall_score"],
    "detected_dialogue_seconds": [dialogue["segments"][0]["start"], dialogue["segments"][0]["end"]],
    "container_duration_seconds": dialogue["duration_seconds"],
    "repair_chain": [
        {"method": repair["method"], "removed_confirmed_duplicate_frames": repair["removed_frame_count"], "new_credits": 0},
        {"method": "FIXED_TEXTFREE_9_BY_16_CROP_AND_SCALE", "crop": "528:938:96:0", "scale": "720:1280", "new_credits": 0},
    ],
    "review_evidence": {
        "contact_sheet": rel(CONTACT), "contact_sheet_sha256": sha(CONTACT),
        "full_duration_direct_review": "PASS",
        "full_frame_text_review": "PASS_NONE_VISIBLE_AFTER_CROP",
    },
    "checks": {
        "canonical_u18d_line": "PASS_EXACT_RECALL_1_0",
        "native_mandarin": "PASS",
        "visible_chenji_face_and_mouth": "PASS",
        "chenji_age17_identity_and_period_costume": "PASS",
        "yunyang_silent_reaction": "PASS_NO_AUDIBLE_SECOND_SPEAKER",
        "messenger_environment_life": "PASS",
        "lip_breath_expression_sync": "PASS_DIRECT_TEMPORAL_REVIEW",
        "first_frame_continuation_motion": "PASS",
        "period_and_dusk_continuity": "PASS",
        "paper_and_readable_text": "PASS_NONE_AFTER_CROP",
        "modern_objects": "PASS_NONE",
        "frame_cadence": cadence["status"],
        "full_duration_ocr": ocr["status"],
    },
    "limitations": ["The deterministic dedup repair shortens the source to 4.97 seconds while preserving the complete line and 0.729-second closed-mouth tail.", "The crop is tighter than the generated frame but retains both foreground faces and the living background layer."],
})

credit_audit = {
    "schema": "qingshan.actual_credit_spend_audit.v9", "episode": "E36", "status": "PASS_EXACT_COMPLETE",
    "net_actual_credits": 5863, "gross_pay_credits": 6563, "refund_credits": 700,
    "breakdown": {"image_generation": 561, "video_generation": 5292, "audio_generation": 10},
    "new_since_5767": [{"task_id": task["task_id"], "type": "U18D_fast_video", "exact_pay": 96}],
    "zero_credit_postproduction": ["U18D_confirmed_duplicate_frame_and_matching_audio_interval_removal", "U18D_fixed_textfree_9_by_16_crop"],
    "unknown_success_credits": 0, "active_remote_tasks": 0,
    "episode_limit": 6000, "remaining_runway": 137, "approval_required": False,
}
write(ROOT / "qa/e36_v2_stills_repair_20260729/E36_ACTUAL_CREDIT_SPEND_AUDIT_5863_V9.json", credit_audit)

write(ROOT / "qa/e36_v2_stills_repair_20260729/E36_CAP_STATE_5863_AFTER_U18D_V10.json", {
    "schema": "qingshan.e36_cap_state.v1", "episode": "E36",
    "status": "PASS_PAID_COVERAGE_COMPLETE_ZERO_CREDIT_FALLBACK_QA_PENDING",
    "actual_credits": 5863, "actual_breakdown": {"image": 561, "video": 5292, "audio": 10},
    "budget_cap": 6000, "headroom": 137, "approval_required": False,
    "remaining_paid_plan": [],
    "paid_u18_coverage": "COMPLETE_U18A_U18B_U18C_U18D_ACCEPTED",
    "remaining_zero_credit_plan": [
        {"segment": "U06_FALLBACK", "method": "LOCAL_ANCHOR_SEQUENCE_MOTION_COMPOSITE_AND_FULL_QA", "projected_credits": 0},
        {"segment": "U07_FALLBACK", "method": "LOCAL_ANCHOR_SEQUENCE_MOTION_COMPOSITE_AND_FULL_QA", "projected_credits": 0},
        {"segment": "U17_FALLBACK", "method": "LOCAL_CONTINUATION_MOTION_COMPOSITE_AND_FULL_QA", "projected_credits": 0},
    ],
    "release_gate": "U06_U07_U17_LOCAL_CANDIDATES_MUST_PASS_MOTION_CADENCE_OCR_DIALOGUE_IF_ANY_AND_FULL_HUMAN_REVIEW_BEFORE_AGENTCUT",
    "paid_retry_policy": "No paid retry is planned inside the remaining 137-credit headroom; replan before any additional charge.",
    "active_remote_tasks": 0, "unknown_success_credits": 0, "e37_production_opened": False,
})

queue_path = ROOT / "workflow/work_queue.json"
queue = read(queue_path)
now = datetime.now().astimezone().isoformat(timespec="seconds")
note = ("U18D real Seedance Fast task 4454e3c5 completed at exact Pay96. Raw source cadence FAIL is preserved; zero-credit confirmed-frame/audio-interval dedup repaired cadence. The dedup source manual visual FAIL is also preserved because a written ticket occupied the lower frame. A second zero-credit fixed 9:16 crop removed all paper/text and passed cadence, full-duration OCR, exact native dialogue recall1.0 and direct temporal review. U18D is accepted only for its final Chenji line. Paid E36 coverage is complete at5863/6000 (image561, video5292, audio10), active tasks0, headroom137. Only mandatory U06/U07/U17 zero-credit local fallback QA remains before AgentCut. E37 remains unopened.")
queue.update({"updated_at": now, "updated_note_latest": note, "status": "E36_PRODUCTION_ACTIVE_U06_U07_U17_LOCAL_FALLBACK_QA_CAP_5863", "real_active_handle_count": 0})
line = queue["lines"]["E36"]
line.update({
    "status": "ACTIVE_CAP_5863_U18D_ACCEPTED_U06_U07_U17_LOCAL_FALLBACK_QA_PENDING",
    "current_phase": note, "blocked_by": None,
    "e36_paid_credits": "5863/6000 verified episode total; images561, videos5292, audio10; U18D Fast video Pay96; unknown0; active tasks0",
    "local_pid": None, "running_or_pending_task_ids": [],
    "next_action": "Build U06/U07/U17 zero-credit local motion-composite candidates from their accepted anchors, then require motion/cadence, OCR, dialogue-if-any and full human temporal QA before AgentCut. Preserve every paid and local FAIL, make no paid retry inside the 137-credit headroom, and keep E37 closed.",
    "latest_u18d_evidence": "Fast video task 4454e3c5 Pay96. Raw sha837a1b4a preserved cadence FAIL. Confirmed duplicate-frame/audio-interval removal produced sha3210f44b with cadence PASS but manual FAIL for written ticket. Text-free crop accepted sha" + sha(FIXED)[:8] + " with cadence PASS, OCR zero, exact native Chenji line recall1.0 and direct temporal QA PASS. Actual5863, paid U18 coverage complete, only U06/U07/U17 zero-credit fallback QA remains.",
})
write(queue_path, queue)

print(json.dumps({"status": "PASS_ACCEPTED_U18D_ONLY", "accepted_sha256": sha(FIXED), "actual_credits": 5863, "remaining_runway": 137}, ensure_ascii=False))
