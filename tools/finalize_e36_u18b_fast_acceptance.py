#!/usr/bin/env python3
"""Record U18B raw failure, text-free acceptance, ledger, and U18C handoff."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
QA = ROOT / "qa/e36_v2_stills_repair_20260729"
U18_QA = QA / "u18_video_runtime"
RAW = PROD / "video_repair_v2_outputs/E36_E36-CW-U18B-VIDEO-V1-FAST_ef02d6e9-050d-4d37-a626-11d27d03f78f.mp4"
ACCEPTED = PROD / "video_repair_v2_outputs/E36_E36-CW-U18B-VIDEO-V1-FAST_ef02d6e9-050d-4d37-a626-11d27d03f78f_TEXTFREE_CROP.mp4"
ANCHOR = ROOT / "working_assets/e36_v2_stills_20260728/u18_local_repairs/E36-CW-U18C-A1-U18B-TERMINAL-CHENJI-CROP-V2.jpg"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


raw_fail = {
    "schema": "qingshan.manual_source_video_qa.v1", "episode": "E36", "unit": "U18B",
    "source_task_id": "ef02d6e9-050d-4d37-a626-11d27d03f78f", "status": "FAIL_PRESERVED_REPAIR_REQUIRED",
    "source_video": rel(RAW), "source_video_sha256": sha(RAW),
    "failures": ["UNAUTHORIZED_READABLE_PAPER_OCCUPIES_LOWER_FRAME_THROUGH_FULL_DURATION"],
    "machine_qa_note": "Automated cadence, OCR lexicon and dialogue gates passed, but direct 2fps full-duration review overrides because the rendered paper visibly carries multiple written lines.",
    "contact_sheet": rel(U18_QA / "E36_U18B_CONTACT_SHEET_2FPS.jpg"),
    "repair_policy": "Preserve the paid raw source unchanged; admit only a zero-credit fixed crop after independent cadence, OCR, native-dialogue and full-duration visual checks.",
}
write(U18_QA / "E36_U18B_RAW_MANUAL_QA_FAIL_V1.json", raw_fail)

accepted = {
    "schema": "qingshan.manual_source_video_qa.v1", "episode": "E36", "unit": "U18B",
    "source_task_id": "ef02d6e9-050d-4d37-a626-11d27d03f78f", "status": "PASS_ACCEPTED_U18B_ONLY",
    "accepted_video": rel(ACCEPTED), "accepted_video_sha256": sha(ACCEPTED),
    "source_fail": rel(U18_QA / "E36_U18B_RAW_MANUAL_QA_FAIL_V1.json"),
    "repair": {"method": "FIXED_9_BY_16_CROP_AND_SCALE", "crop": "405:720:170:0", "scale": "720:1280", "audio": "STREAM_COPY_UNCHANGED", "new_generation_credits": 0},
    "checks": {"age17_yunyang_identity": "PASS", "age17_chenji_identity": "PASS_PARTIAL_SILENT_LISTENER_EDGE", "messenger_identity": "PASS_BACKGROUND",
        "yunyang_only_visible_speaker": "PASS", "native_mandarin_exact_recall": "PASS_1_0", "visible_lip_breath_expression_sync": "PASS_BY_2FPS_FULL_DURATION_REVIEW",
        "first_frame_continuation": "PASS_FROM_U18A_TERMINAL", "paper_and_visible_text_absent": "PASS_AFTER_CROP", "period_continuity": "PASS",
        "environment_life": "PASS_BACKGROUND_MICROMOTION", "frame_cadence": "PASS", "ocr": "PASS_ZERO_RECOGNITIONS",
        "canonical_information": "PASS_SECOND_U18_YUNYANG_LINE_ONLY", "u18c_continuity": "PASS_TERMINAL_REFRAMED_FOR_CHENJI"},
    "contact_sheet": rel(U18_QA / "E36_U18B_TEXTFREE_CROP_CONTACT_SHEET_2FPS.jpg"),
    "machine_qa": {"cadence": rel(U18_QA / "E36_U18B_TEXTFREE_CROP_FRAME_CADENCE.json"), "ocr": rel(U18_QA / "E36_U18B_TEXTFREE_CROP_OCR.json"), "native_dialogue": rel(U18_QA / "E36_U18B_TEXTFREE_CROP_NATIVE_DIALOGUE.json")},
    "remaining_coverage": ["U18 first Chenji line", "U18 second Chenji line"],
}
write(U18_QA / "E36_U18B_TEXTFREE_CROP_MANUAL_QA_V1.json", accepted)

anchor_qa = {
    "schema": "qingshan.image_qa.v1", "episode": "E36", "unit": "U18C", "status": "PASS_CONTINUATION_AUTHORITY",
    "asset": rel(ANCHOR), "asset_sha256": sha(ANCHOR), "source_video": rel(RAW), "source_time_seconds": 5.95,
    "derivation": {"method": "ZERO_CREDIT_TERMINAL_FRAME_CROP", "crop": "506:900:0:0", "scale": "720:1280"},
    "checks": {"media_integrity": "PASS", "aspect_ratio_9_16": "PASS", "age17_chenji_identity": "PASS_LEFT_PROFILE_VISIBLE_WITH_MOUTH",
        "age17_yunyang_identity": "PASS_RIGHT_REACTION", "messenger_identity": "PASS_BACKGROUND", "chenji_mouth_available_for_next_native_line": "PASS",
        "paper_and_readable_text_absent": "PASS", "ocr": "PASS_ZERO_RECOGNITIONS", "period": "PASS", "scene_space": "PASS", "ambient_life_seed": "PASS"},
    "ocr_report": rel(U18_QA / "E36_U18C_TERMINAL_ANCHOR_OCR_V1.json"), "new_credits": 0,
}
write(U18_QA / "E36_U18C_TERMINAL_ANCHOR_IMAGE_QA_V1.json", anchor_qa)

credit = {
    "schema": "qingshan.actual_credit_spend_audit.v7", "episode": "E36", "status": "PASS_EXACT_COMPLETE",
    "net_actual_credits": 5687, "gross_pay_credits": 6387, "refund_credits": 700,
    "breakdown": {"image_generation": 561, "video_generation": 5116, "audio_generation": 10},
    "new_since_5589": [
        {"task_id": "f1210223-85e4-41c1-84ac-30554e9bce62", "type": "U18B_exact_dialogue_reference", "exact_pay": 2},
        {"task_id": "ef02d6e9-050d-4d37-a626-11d27d03f78f", "type": "U18B_fast_video", "exact_pay": 96}],
    "zero_credit_postproduction": ["U18B_video_text_removal_by_fixed_9_by_16_crop", "U18C_terminal_anchor_extraction_and_textfree_crop"],
    "unknown_success_credits": 0, "active_remote_tasks": 0, "episode_limit": 6000, "remaining_runway": 313, "approval_required": False,
}
write(QA / "E36_ACTUAL_CREDIT_SPEND_AUDIT_5687_V7.json", credit)

cap = {
    "schema": "qingshan.e36_capfit_plan.v2", "episode": "E36", "status": "PASS_CONDITIONAL_ZERO_CREDIT_FALLBACKS",
    "actual_credits": 5687, "actual_breakdown": {"image": 561, "video": 5116, "audio": 10}, "budget_cap": 6000, "remaining_runway": 313,
    "live_fast_billing_evidence": {"task_id": "ef02d6e9-050d-4d37-a626-11d27d03f78f", "duration_seconds": 6, "exact_charge": 96, "observed_credits_per_second": 16},
    "remaining_paid_plan": [
        {"segment": "U18C", "duration_seconds": 5, "model": "seedance-2.0-fast", "projected_credits": 80},
        {"segment": "U18D", "duration_seconds": 5, "model": "seedance-2.0-fast", "projected_credits": 80}],
    "remaining_zero_credit_plan": [
        {"segment": "U06_FALLBACK", "method": "LOCAL_ANCHOR_SEQUENCE_MOTION_COMPOSITE_AND_QA", "projected_credits": 0},
        {"segment": "U07_FALLBACK", "method": "LOCAL_ANCHOR_SEQUENCE_MOTION_COMPOSITE_AND_QA", "projected_credits": 0},
        {"segment": "U17_FALLBACK", "method": "LOCAL_CONTINUATION_MOTION_COMPOSITE_AND_QA", "projected_credits": 0}],
    "projected_additional_credits": 160, "projected_episode_total": 5847, "headroom": 153,
    "hard_gate": "PASS_ONLY_IF_U06_U07_U17_ZERO_CREDIT_FALLBACKS_PASS_QA; OTHERWISE_DO_NOT_EXCEED_6000",
    "notes": ["The earlier 5808 projection is superseded: current Fast billing is 96 credits for six seconds, not the historical 105-for-fifteen observation.",
        "U18C and U18D retain conservative five-second native Chenji dialogue slots.", "Any live billing variance stops the following paid submission for exact ledger recomputation."]}
write(QA / "E36_CAPFIT_REPLAN_5847_AFTER_U18B_V8.json", cap)

queue_path = ROOT / "workflow/work_queue.json"
queue = read(queue_path)
timestamp = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
queue["updated_at"] = timestamp
queue["updated_note_latest"] = "U18B exact Yunyang audio Pay2 and real Seedance Fast video Pay96 completed. Direct 2fps review preserved the raw source as FAIL because written paper occupied the lower frame. A zero-credit fixed 9:16 crop removed all paper/text while preserving visible Yunyang speech, age-17 continuity, messenger, period and environment life; cadence PASS, OCR zero recognitions and native Mandarin recall1.0. U18B is accepted only for its second canonical line. Actual ledger is5687/6000 (image561, video5116, audio10), active tasks0. A text-free U18C Chenji-profile continuation anchor was extracted and image-QA/OCR passed. Current Fast billing is96 for6s, so only U18C/U18D remain paid in the5847 projection; U06/U07/U17 require zero-credit local fallback QA or production stops before6000. E37 remains unopened."
    
queue["status"] = "E36_PRODUCTION_ACTIVE_U18C_PREPRODUCTION_CAPFIT_5847"
queue["real_active_handle_count"] = 0
line = queue["lines"]["E36"]
line["status"] = "ACTIVE_CAPFIT_5847_U18C_PREPRODUCTION_U06_U07_U17_LOCAL_FALLBACK_PENDING"
line["current_phase"] = queue["updated_note_latest"]
line["blocked_by"] = None
line["e36_paid_credits"] = "5687/6000 verified episode total; images561, videos5116, audio10; U18B audio Pay2; U18B Fast video Pay96; unknown0; active tasks0"
line["running_or_pending_task_ids"] = []
line["next_action"] = "Build and precheck U18C from the accepted text-free Chenji-profile terminal; submit one five-second Fast native-dialogue unit only while exact projection remains <=6000, reconcile exact billing, then U18D. In parallel make U06/U07/U17 zero-credit local fallback candidates and require full QA; preserve all FAILs and keep E37 closed."
line["latest_u18b_evidence"] = "Exact-audio task f1210223 Pay2 recall1.0; Fast video task ef02d6e9 Pay96. Raw sha b8486788 preserved FAIL for written paper. Text-free crop sha a0eb4719 accepted U18B only with cadence PASS, OCR zero, native dialogue recall1.0. U18C anchor sha25ca244a image QA/OCR PASS. Actual5687, projected5847 with only U18C/U18D paid."
write(queue_path, queue)
print(U18_QA / "E36_U18B_TEXTFREE_CROP_MANUAL_QA_V1.json")
