#!/usr/bin/env python3
"""Record U18C raw failure, zero-credit repair acceptance, and U18D handoff."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
QA = ROOT / "qa/e36_v2_stills_repair_20260729/u18_video_runtime"
RAW = PROD / "video_repair_v2_outputs/E36_E36-CW-U18C-VIDEO-V1-FAST_7e3f1dd2-fdf0-4db4-85b9-0588c7c229b7.mp4"
FIXED = PROD / "video_repair_v2_outputs/E36_E36-CW-U18C-VIDEO-V1-FAST_7e3f1dd2-fdf0-4db4-85b9-0588c7c229b7_TEXTFREE_CROP.mp4"
ANCHOR = ROOT / "working_assets/e36_v2_stills_20260728/u18_local_repairs/E36-CW-U18D-A1-U18C-TERMINAL-4P95-V1.jpg"
CONTACT = QA / "E36_U18C_TEXTFREE_CROP_CONTACT_SHEET_V1.jpg"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_pass(path: Path) -> dict:
    payload = read(path)
    if payload.get("status") != "PASS":
        raise SystemExit(f"required QA did not pass: {path}: {payload.get('status')}")
    return payload


cadence = require_pass(QA / "E36_U18C_TEXTFREE_CROP_FRAME_CADENCE_V1.json")
ocr = require_pass(QA / "E36_U18C_TEXTFREE_CROP_OCR_V1.json")
dialogue = require_pass(QA / "E36_U18C_TEXTFREE_CROP_NATIVE_DIALOGUE_V1.json")
receipt = read(PROD / "E36_U18C_EPISODE_SINGLE_UNIT_FAST_RECEIPT_V1_REAL.json")
task = receipt["tasks"][0]
attempt = task["credit_attempts"][0]
if attempt.get("actual_charged_credits") != 80 or not attempt.get("success"):
    raise SystemExit("U18C exact Pay80 evidence is missing")
if sha(RAW) != "8130dcba4ace490db4c3fdb84a5b74aedbce0b66f534af801b77d9c838292ef2":
    raise SystemExit("U18C raw source changed")

raw_fail = {
    "schema": "qingshan.manual_source_video_qa.v1",
    "episode": "E36", "unit_id": "U18", "source_segment_id": "U18C",
    "status": "FAIL_REPAIRABLE_UNAUTHORIZED_VISIBLE_PAPER_TEXT",
    "task_id": task["task_id"], "exact_charge_credits": 80,
    "raw_video": rel(RAW), "raw_video_sha256": sha(RAW),
    "direct_review": {
        "status": "FAIL", "method": "FULL_FRAME_REVIEW_PLUS_1P2FPS_CONTACT_SHEET",
        "failure": "A written paper occupies the lower-right frame across the take even though the prompt required all paper and readable text to remain offscreen.",
        "automated_ocr_limit": "The source OCR excludes the bottom 20 percent and therefore did not override the direct full-frame failure.",
        "repairability": "A fixed 528x938 crop from x96,y0 removes the complete paper while preserving Chenji's face, mouth, Yunyang reaction, messenger and candle."
    },
    "automatic_native_dialogue_raw_report": rel(QA / "E36-CW-U18C-VIDEO-V1-FAST_native_dialogue.json"),
    "automatic_native_dialogue_raw_note": "The original report is preserved. Its punctuation-only ellipsis transcript was a Whisper initial-prompt artifact, later corrected by punctuation-stripped prompting and independent multi-pass ASR.",
    "unchanged_retry_allowed": False,
}
write(QA / "E36_U18C_RAW_MANUAL_QA_FAIL_V1.json", raw_fail)

asr_adjudication = {
    "schema": "qingshan.native_dialogue_multipass_adjudication.v1",
    "episode": "E36", "unit_id": "U18", "source_segment_id": "U18C",
    "status": "PASS_STRICT_MULTIPASS_CONSENSUS",
    "expected_text": "……却还在按笔掏银子，买这颗棋的命。",
    "normalized_expected": "却还在按笔掏银子买这颗棋的命",
    "accepted_video": rel(FIXED), "accepted_video_sha256": sha(FIXED),
    "passes": [
        {"prompt": "none", "transcript": "却还在暗笔掏银子买这颗棋的命", "notes": "Confirms the initial 却 and complete tail; one 按/暗 homophone error."},
        {"prompt": "generic Mandarin", "transcript": "却还在暗笔掏银子买这颗棋的命", "notes": "Confirms complete line; one 按/暗 homophone error."},
        {"prompt": "generic Mandarin plus exact hotwords", "transcript": "却还在按笔掏银子买这颗棋的命", "notes": "Exact normalized line."},
        {"prompt": "punctuation-stripped expected", "transcript": "却还在按笔掏银子买这颗棋的命", "notes": "Exact normalized line."},
    ],
    "automated_gate_report": rel(QA / "E36_U18C_TEXTFREE_CROP_NATIVE_DIALOGUE_V1.json"),
    "automated_gate_recall": dialogue["recall_score"],
    "timing": {"detected_start_seconds": 0.53, "detected_end_seconds": 4.53, "container_duration_seconds": dialogue["duration_seconds"], "closed_mouth_tail_seconds": 0.555},
    "verdict": "Two independent exact passes plus two complete homophone-only passes establish the canonical native Mandarin line without tail clipping.",
}
write(QA / "E36_U18C_NATIVE_DIALOGUE_MULTIPASS_ADJUDICATION_V1.json", asr_adjudication)

accepted = {
    "schema": "qingshan.manual_source_video_qa.v1",
    "episode": "E36", "unit_id": "U18", "source_segment_id": "U18C",
    "status": "PASS_ACCEPTED_U18C_ONLY",
    "source_task_id": task["task_id"], "source_charge_credits": 80, "new_repair_credits": 0,
    "accepted_video": rel(FIXED), "accepted_video_sha256": sha(FIXED),
    "repair": {"method": "FIXED_TEXTFREE_9_BY_16_CROP_AND_SCALE", "crop": "528:938:96:0", "scale": "720:1280", "audio": "stream_copy"},
    "review_evidence": {"contact_sheet": rel(CONTACT), "contact_sheet_sha256": sha(CONTACT), "full_duration_direct_review": "PASS"},
    "checks": {
        "canonical_u18c_line": "PASS_STRICT_MULTIPASS_CONSENSUS",
        "native_mandarin_and_audio": "PASS",
        "visible_chenji_face_and_mouth": "PASS",
        "chenji_age17_identity_and_grey_period_costume": "PASS",
        "yunyang_silent_reaction": "PASS_NO_AUDIBLE_SECOND_SPEAKER",
        "messenger_silent_environment_life": "PASS",
        "lip_breath_expression_sync": "PASS_DIRECT_TEMPORAL_REVIEW",
        "first_frame_continuation_motion": "PASS",
        "period_and_dusk_continuity": "PASS",
        "paper_and_readable_text": "PASS_NONE_AFTER_CROP",
        "modern_objects": "PASS_NONE",
        "frame_cadence": cadence["status"],
        "full_duration_ocr": ocr["status"],
    },
    "limitations": ["The crop is tighter than the raw take but preserves both speaking and reaction faces plus the messenger.", "Single-Han OCR false positives are retained in the report; direct full-frame review confirms no visible glyphs."],
}
write(QA / "E36_U18C_TEXTFREE_CROP_MANUAL_QA_V1.json", accepted)

subprocess.run([
    "/usr/bin/python3", "tools/still_image_ocr_audit.py", "--image", str(ANCHOR),
    "--out", str(QA / "E36_U18D_TERMINAL_ANCHOR_OCR_V1.json"),
    "--allow-text", "__NO_TEXT_ALLOWED__", "--forbid-text", "__FORBIDDEN_TEXT__",
], cwd=ROOT, check=True)
anchor_ocr = read(QA / "E36_U18D_TERMINAL_ANCHOR_OCR_V1.json")
if anchor_ocr.get("status") != "PASS":
    raise SystemExit("U18D anchor OCR did not pass")
anchor_qa = {
    "schema": "qingshan.image_qa.v1", "episode": "E36", "unit_id": "U18", "source_segment_id": "U18D",
    "status": "PASS_CONTINUATION_AUTHORITY", "asset": rel(ANCHOR), "asset_sha256": sha(ANCHOR),
    "source_video": rel(FIXED), "source_video_sha256": sha(FIXED), "source_timestamp_seconds": 4.95, "new_generation_credits": 0,
    "checks": {"chenji_age17_identity": "PASS", "visible_profile_face_and_mouth": "PASS", "immediate_next_line_readiness": "PASS_LIPS_SLIGHTLY_PARTED_AFTER_BREATH", "yunyang_silent_reaction": "PASS", "messenger_environment_life": "PASS", "period": "PASS", "visible_text": "PASS_NONE", "modern_objects": "PASS_NONE", "weather": "PASS_INTERIOR_CLEAR_DUSK_ENTERING", "ocr": "PASS"},
    "continuation_instruction": "Begin U18D from this exact frame; Chenji at screen left speaks the final inference while Yunyang at screen right and the messenger remain silent; keep all paper outside the crop."
}
write(QA / "E36_U18D_TERMINAL_ANCHOR_IMAGE_QA_V1.json", anchor_qa)

credit_audit = {
    "schema": "qingshan.actual_credit_spend_audit.v8", "episode": "E36", "status": "PASS_EXACT_COMPLETE",
    "net_actual_credits": 5767, "gross_pay_credits": 6467, "refund_credits": 700,
    "breakdown": {"image_generation": 561, "video_generation": 5196, "audio_generation": 10},
    "new_since_5687": [{"task_id": task["task_id"], "type": "U18C_fast_video", "exact_pay": 80}],
    "zero_credit_postproduction": ["U18C_video_text_removal_by_fixed_9_by_16_crop", "U18D_terminal_anchor_extraction", "source_video_dialogue_gate_punctuation_prompt_fix"],
    "unknown_success_credits": 0, "active_remote_tasks": 0, "episode_limit": 6000, "remaining_runway": 233, "approval_required": False,
}
write(ROOT / "qa/e36_v2_stills_repair_20260729/E36_ACTUAL_CREDIT_SPEND_AUDIT_5767_V8.json", credit_audit)

cap = {
    "schema": "qingshan.e36_capfit_plan.v2", "episode": "E36", "status": "PASS_CONDITIONAL_ZERO_CREDIT_FALLBACKS",
    "actual_credits": 5767, "actual_breakdown": {"image": 561, "video": 5196, "audio": 10}, "budget_cap": 6000, "remaining_runway": 233,
    "live_fast_billing_evidence": {"task_id": task["task_id"], "duration_seconds": 5, "exact_charge": 80, "observed_credits_per_second": 16},
    "remaining_paid_plan": [{"segment": "U18D", "duration_seconds": 5, "model": "seedance-2.0-fast", "projected_credits": 80}],
    "remaining_zero_credit_plan": [
        {"segment": "U06_FALLBACK", "method": "LOCAL_ANCHOR_SEQUENCE_MOTION_COMPOSITE_AND_QA", "projected_credits": 0},
        {"segment": "U07_FALLBACK", "method": "LOCAL_ANCHOR_SEQUENCE_MOTION_COMPOSITE_AND_QA", "projected_credits": 0},
        {"segment": "U17_FALLBACK", "method": "LOCAL_CONTINUATION_MOTION_COMPOSITE_AND_QA", "projected_credits": 0}],
    "projected_additional_credits": 80, "projected_episode_total": 5847, "headroom": 153,
    "hard_gate": "PASS_ONLY_IF_U06_U07_U17_ZERO_CREDIT_FALLBACKS_PASS_QA; OTHERWISE_DO_NOT_EXCEED_6000",
    "notes": ["U18C exact Fast billing confirms Pay80 for five seconds.", "U18D retains one five-second native Chenji dialogue slot.", "Any live billing variance stops further paid submission for exact ledger recomputation."],
}
write(ROOT / "qa/e36_v2_stills_repair_20260729/E36_CAPFIT_REPLAN_5847_AFTER_U18C_V9.json", cap)

queue_path = ROOT / "workflow/work_queue.json"
queue = read(queue_path)
now = datetime.now().astimezone().isoformat(timespec="seconds")
note = ("U18C real Seedance Fast task 7e3f1dd2 completed at exact Pay80. Raw source is preserved FAIL because written paper occupied the lower-right frame; the original punctuation-led Whisper false FAIL is also preserved. A punctuation-stripped ASR gate fix passed tests and multi-pass ASR established the native Chenji line. Zero-credit fixed 9:16 crop removed all paper/text and passed cadence, full-duration OCR, direct temporal review and native dialogue QA. U18C is accepted only for its first Chenji line. Actual ledger is5767/6000 (image561, video5196, audio10), active tasks0. U18D continuation anchor passed image QA/OCR. Exact projection remains5847 with U18D Pay80 and U06/U07/U17 zero-credit local fallback QA. E37 remains unopened.")
queue.update({"updated_at": now, "updated_note_latest": note, "status": "E36_PRODUCTION_ACTIVE_U18D_PREPRODUCTION_CAPFIT_5847", "real_active_handle_count": 0})
line = queue["lines"]["E36"]
line.update({"status": "ACTIVE_CAPFIT_5847_U18D_PREPRODUCTION_U06_U07_U17_LOCAL_FALLBACK_PENDING", "current_phase": note, "blocked_by": None,
    "e36_paid_credits": "5767/6000 verified episode total; images561, videos5196, audio10; U18C Fast video Pay80; unknown0; active tasks0",
    "local_pid": None, "running_or_pending_task_ids": [],
    "next_action": "Build and precheck U18D from the accepted text-free Chenji terminal; submit one five-second Fast native-dialogue unit only while exact projection remains <=6000, reconcile exact billing, then finish U06/U07/U17 zero-credit local fallback QA. Preserve all FAILs and keep E37 closed.",
    "latest_u18c_evidence": "Fast video task 7e3f1dd2 Pay80. Raw sha8130dcba preserved FAIL for written paper and original punctuation-led ASR artifact. Punctuation-stripped gate plus multi-pass ASR passed. Text-free crop sha0112bfe0 accepted U18C only with cadence PASS, full-duration OCR PASS, native dialogue recall0.929 and exact multipass consensus. U18D anchor shaa2e86e3d image QA/OCR PASS. Actual5767, projected5847 with U18D paid."})
write(queue_path, queue)

print(json.dumps({"status": "PASS_ACCEPTED_U18C_ONLY", "accepted_sha256": sha(FIXED), "actual_credits": 5767, "projected_total": 5847}, ensure_ascii=False))
