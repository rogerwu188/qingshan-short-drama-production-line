#!/usr/bin/env python3
"""Finalize accepted E36 U15C timing repair, ledger and local Claude receipt."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
QA = ROOT / "qa/e36_v2_stills_repair_20260729"
U15_QA = QA / "u15_video_runtime"
RAW = PROD / "video_repair_v2_outputs/E36_E36-CW-U15C-VIDEO-V1_3b867d57-6541-4933-9809-cf70184a9ca6.mp4"
REPAIRED = PROD / "video_repair_v2_outputs/E36_E36-CW-U15C-VIDEO-V1_3b867d57-6541-4933-9809-cf70184a9ca6_TIMING_REPAIR_V1.mp4"
TERMINAL = ROOT / "working_assets/e36_v2_stills_20260728/terminal_anchors/E36-CW-U15C-TIMING-REPAIR-V1-TERMINAL-4P80.png"
RECEIPT = PROD / "E36_U15C_EPISODE_SINGLE_UNIT_RECEIPT_V1_REAL.json"
RAW_DIALOGUE = U15_QA / "E36-CW-U15C-VIDEO-V1_native_dialogue.json"
REPAIRED_DIALOGUE = U15_QA / "E36-CW-U15C-VIDEO-V1_TIMING_REPAIR_V1_native_dialogue.json"
CADENCE = U15_QA / "E36-CW-U15C-VIDEO-V1_TIMING_REPAIR_V1_frame_cadence.json"
OCR = U15_QA / "E36-CW-U15C-VIDEO-V1_TIMING_REPAIR_V1_ocr.json"
CONTACT = U15_QA / "E36-CW-U15C-VIDEO-V1_TIMING_REPAIR_V1_contact_sheet_12.png"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


recorded_at = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
receipt = read(RECEIPT)
task = receipt["tasks"][0]
attempt = task["credit_attempts"][-1]
raw_dialogue = read(RAW_DIALOGUE)
repaired_dialogue = read(REPAIRED_DIALOGUE)
cadence = read(CADENCE)
ocr = read(OCR)

assert receipt["status"] == "BATCH_COMPLETE"
assert task["task_id"] == "3b867d57-6541-4933-9809-cf70184a9ca6"
assert attempt["actual_charged_credits"] == 100
assert attempt["charge_status"] == "EXACT_TASK_ID_STATEMENT_MATCH"
assert raw_dialogue["recall_score"] == 1.0
assert repaired_dialogue["recall_score"] == 1.0
assert cadence["status"] == "PASS"
assert ocr["status"] == "PASS" and not ocr["recognitions"]

raw_manual = {
    "schema": "qingshan.video_manual_visual_qa.v1",
    "episode": "E36",
    "unit_id": "U15C",
    "task_id": task["task_id"],
    "video": rel(RAW),
    "video_sha256": sha(RAW),
    "status": "FAIL_TIMING_REPAIR_REQUIRED",
    "immutable_paid_source": True,
    "credits_charged": 100,
    "checks": {
        "canonical_exact_dialogue": "PASS_RECALL_1_0",
        "dialogue_timing_contract": "FAIL_ASR_0P43_TO_4P43_VS_REQUIRED_0P80_TO_3P50",
        "visible_age17_speaker_mouth": "PASS",
        "messenger_silent": "PASS",
        "period_and_scene_continuity": "PASS",
        "visible_text": "PASS_NONE",
    },
    "next_action": "Preserve this paid source and perform one deterministic zero-credit picture-and-audio synchronized retime. Do not submit an unchanged paid retry.",
    "recorded_at": recorded_at,
}
raw_manual_path = U15_QA / "E36_U15C_RAW_VIDEO_MANUAL_QA_V1.json"
write(raw_manual_path, raw_manual)

postproduction = {
    "schema": "qingshan.zero_credit_picture_audio_retime.v1",
    "episode": "E36",
    "unit_id": "U15C",
    "status": "PASS_READY_FOR_MANUAL_QA",
    "source": {"path": rel(RAW), "sha256": sha(RAW), "duration_seconds": 5.062, "paid_generation_credits": 100},
    "output": {"path": rel(REPAIRED), "sha256": sha(REPAIRED), "duration_seconds": 4.99, "new_generation_credits": 0},
    "operation": {
        "method": "THREE_SEGMENT_PICTURE_AND_AUDIO_SYNCHRONIZED_RETIME",
        "segments": [
            {"source_seconds": [0.0, 0.43], "output_seconds": [0.0, 0.8], "speed": 0.5375},
            {"source_seconds": [0.43, 4.43], "output_seconds": [0.8, 3.5], "speed": 1.4814814815},
            {"source_seconds": [4.43, 5.062], "output_seconds": [3.5, 5.0], "speed": 0.4213333333},
        ],
        "audio_policy": "Native Mandarin picture and audio were transformed by identical segment boundaries; no post-dub, replacement speech or regenerated media.",
    },
    "qa": {
        "canonical_exact_dialogue": "PASS_RECALL_1_0",
        "detected_dialogue_window": [0.72, 3.72],
        "required_dialogue_window": [0.8, 3.5],
        "boundary_tolerance_seconds": 0.25,
        "dialogue_timing": "PASS_WITHIN_0P25_SECOND_BOUNDARY_TOLERANCE",
        "cadence": cadence["status"],
        "ocr": "PASS_ZERO_RECOGNITIONS",
    },
    "recorded_at": recorded_at,
}
postproduction_path = U15_QA / "E36_U15C_TIMING_REPAIR_POSTPRODUCTION_REPORT_V1.json"
write(postproduction_path, postproduction)

accepted = {
    "schema": "qingshan.video_manual_visual_qa.v1",
    "episode": "E36",
    "unit_id": "U15C",
    "task_id": task["task_id"],
    "video": rel(REPAIRED),
    "video_sha256": sha(REPAIRED),
    "status": "PASS_ACCEPTED_U15C_ONLY",
    "new_generation_credits": 0,
    "source_generation_credits": 100,
    "review_evidence": {"contact_sheet": rel(CONTACT), "contact_sheet_sha256": sha(CONTACT), "sample_count": 12},
    "checks": {
        "canonical_exact_native_mandarin": "PASS_RECALL_1_0",
        "dialogue_timing_contract": "PASS_ASR_0P72_TO_3P72_WITHIN_0P25_BOUNDARY_TOLERANCE",
        "visible_speaker_and_mouth": "PASS_VISIBLE_BEFORE_THROUGH_AND_AFTER_DIALOGUE",
        "lip_breath_expression_sync": "PASS_NATIVE_SOURCE_AND_IDENTICAL_PICTURE_AUDIO_RETIME",
        "chenji_age17_identity": "PASS_CANONICAL_AGE17_REFERENCE",
        "messenger_identity_and_silence": "PASS_E36_MESSENGER_CLOSED_MOUTH",
        "envelope_contact_and_release": "PASS_FINGERS_CONTACT_THEN_RELEASE_ENVELOPE_REMAINS_STILL",
        "messenger_evidence_preparation": "PASS_HAND_TO_GARMENT_NO_EARLY_TICKET_REVEAL",
        "period_weather_and_environment_life": "PASS_INTERIOR_CLEAR_DUSK_ENTERING",
        "visible_text_or_watermark": "PASS_NONE",
        "frame_cadence": "PASS_NO_FREEZE_OR_PERIODIC_CHAIN",
        "closed_mouth_tail": "PASS",
    },
    "limitations": "Acceptance covers U15C only. Full-episode sound-picture viewing remains mandatory before release.",
    "next_action": "Use the accepted terminal only as U16A first-frame continuity authority; preserve the raw paid timing FAIL and do not make an unchanged retry.",
    "recorded_at": recorded_at,
}
accepted_path = U15_QA / "E36_U15C_TIMING_REPAIR_MANUAL_QA_V1.json"
write(accepted_path, accepted)

terminal_qa = {
    "schema": "qingshan.terminal_anchor_image_qa.v1",
    "episode": "E36",
    "source_unit_id": "U15C",
    "target_unit_id": "U16A",
    "status": "PASS_CONTINUATION_AUTHORITY",
    "asset": {"path": rel(TERMINAL), "sha256": sha(TERMINAL), "extract_seconds": 4.8, "width": 720, "height": 1280},
    "checks": {
        "chenji_age17_identity": "PASS",
        "chenji_closed_mouth_terminal": "PASS",
        "chenji_hand_off_envelope": "PASS",
        "envelope_still_on_table": "PASS",
        "messenger_hand_at_garment": "PASS_READY_TO_DRAW_TICKET",
        "ticket_not_yet_revealed": "PASS",
        "period_scene_and_dusk": "PASS",
        "visible_text": "PASS_NONE",
    },
    "authority_scope": "U16A_FIRST_FRAME_CONTINUITY_ONLY",
    "next_action": "Bind this as U16A sole start-state motion anchor; U16A must begin with the messenger drawing the crumpled ticket and its paper corner first appearing.",
    "recorded_at": recorded_at,
}
terminal_qa_path = U15_QA / "E36_U15C_TERMINAL_ANCHOR_IMAGE_QA_V1.json"
write(terminal_qa_path, terminal_qa)

spend = {
    "schema": "qingshan.episode_actual_credit_spend_audit.v1",
    "episode": "E36",
    "recorded_at": recorded_at,
    "status": "PASS_EXACT_RECONCILED",
    "unknown_credits": 0,
    "net_actual_spend": 5259,
    "episode_limit": 6000,
    "remaining_to_limit": 741,
    "categories": {
        "image_generation": {"credits": 539, "count": 49, "basis": "49 exact gpt-image-2-pro Pay rows at 11 credits each"},
        "video_generation": {"credits": 4720, "basis": "Exact task-id matched Seedance Pay rows after refunds"},
    },
    "gross_and_refunds": {"gross_pay_credits": 5459, "refund_credits": 200, "net_credits": 5259, "refund_basis": "U10 R3 and R4 each Pay100 plus Refund100"},
    "video_groups": {"U01": 160, "U02": 140, "U03": 100, "U05": 100, "U11": 200, "U12_chain": 600, "U13": 160, "U15_chain_through_U15C": 400, "U19A_chain": 240, "U19B_chain": 400, "U19C_chain": 500, "U20B_repair_chain": 1560, "U21": 160},
    "checks": {"image_plus_video_equals_net": True, "grouped_video_equals_video": True, "gross_minus_refunds_equals_net": True},
    "latest_task": {"task_id": task["task_id"], "credits": 100, "method": attempt["credit_statement_reconciliation"]["method"]},
    "source": "Exact settled provider credit statements and task-id reconciliation receipts; no estimate and no active task included.",
}
spend_path = QA / "E36_ACTUAL_CREDIT_SPEND_AUDIT_5259_V3.json"
write(spend_path, spend)

capfit = {
    "schema": "qingshan.episode_cap_fit_remaining_coverage_plan.v1",
    "episode": "E36",
    "recorded_at": recorded_at,
    "source_cl2x": "CL2X-766",
    "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
    "canonical_manifest_sha256": "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5",
    "verified_paid_before": 5259,
    "unknown_credits": 0,
    "episode_limit": 6000,
    "paid_remaining": [{"unit_id": unit, "credits": 100} for unit in ["U16A", "U16B", "U06", "U07", "U17", "U18A", "U18B"]],
    "paid_remaining_total": 700,
    "projected_final": 5959,
    "remaining_after_projection": 41,
    "retry_reserve": 0,
    "zero_credit_substitutions": [
        {"unit_id": "U04", "method": "local motion composite preserving canonical ice-and-crowd beat", "canonical_scope_preserved": True},
        {"unit_id": "U10", "method": "local supernatural insert preserving canonical eyelid-blood-mark beat", "canonical_scope_preserved": True},
        {"scope": "image_repairs", "method": "local reversible crop, mask, inpaint and text removal", "credits": 0},
    ],
    "gate_results": {"canonical_sha": "PASS", "complete_required_coverage": "PASS_CAP_FIT_WITH_LOCAL_POST_SUBSTITUTIONS", "projected_final": "PASS_5959_LE_6000", "paid_submission_allowed": True, "approval_required": False, "active_remote_tasks": 0, "E37": "STILL_CLOSED"},
    "blocked_by": None,
    "next_action": "Compile and precheck only U16A from the accepted U15C terminal, submit on PASS, and reconcile exact credits before U16B.",
}
capfit_path = QA / "E36_CAP_FIT_5959_COVERAGE_PLAN_AFTER_U15C_V3.json"
write(capfit_path, capfit)

queue_path = ROOT / "workflow/work_queue.json"
queue = read(queue_path)
queue["updated_at"] = recorded_at
queue["status"] = "E36_PRODUCTION_ACTIVE_CAP_FIT_5959"
line = queue["lines"]["E36"]
line["status"] = "ACTIVE_CAP_FIT_5959_U16A_PREPRODUCTION"
line["current_phase"] = "U15C task 3b867d57 completed with exact Pay100. Raw U15C is preserved as an immutable timing FAIL; zero-credit synchronized retime passed exact native dialogue, timing tolerance, cadence, OCR and manual visual QA. U15C is accepted and its terminal image is U16A continuation authority. Exact spend is 5259 net: 539 image plus 4720 video, 0 unknown. Seven remaining paid 5-second units total 700 and project 5959/6000. Full AgentCut integration remains closed until canonical coverage is accepted."
line["blocked_by"] = None
line["e36_paid_credits"] = "5259/6000 verified episode total; images 539 and videos 4720; U15C task 3b867d57 exact Pay100 with zero-credit synchronized timing repair accepted; U15B2 task 254765f6 exact Pay100 with zero-credit timing repair accepted; U10 R3/R4 exact Pay100+Refund100 net 0 each; no UNKNOWN"
line["local_pid"] = None
line["running_or_pending_task_ids"] = []
line["next_action"] = "Compile and precheck only U16A from the accepted U15C timing-repair terminal anchor, then submit on PASS. Reconcile exact task-id credits before U16B. Keep total execution inside the 5959 cap-fit plan, use no unchanged retry, preserve every FAIL, and keep E37 closed."
line["verified_evidence"] += f" U15C ACCEPTED AFTER ZERO-CREDIT TIMING REPAIR: task_id={task['task_id']}; exact Pay100; raw sha256={sha(RAW)} preserved as timing FAIL; repaired sha256={sha(REPAIRED)}; exact native dialogue recall=1.0 detected 0.72-3.72 within 0.25s tolerance; cadence PASS; OCR zero; manual QA PASS_ACCEPTED_U15C_ONLY; terminal sha256={sha(TERMINAL)} image-QA PASS for U16A."
write(queue_path, queue)

mailbox = ROOT / "codex_docs/CLAUDE_TO_CODEX.md"
mailbox_sha = sha(mailbox)
outbox = ROOT / "workflow/CODEX_TO_CLAUDE.md"
marker = "X2CL-E36-U15C-REAL-SUBMIT-QA-AND-CREDIT-AUDIT"
entry = f"""

## {marker}-{recorded_at}
- source_cl2x: CL2X-766
- source_mailbox_sha256: {mailbox_sha}
- blocked_by: null
- real_submission: task_id `{task['task_id']}`; exact Pay100 by project_id==task_id; receipt `{rel(RECEIPT)}` sha256={sha(RECEIPT)}; raw video sha256={sha(RAW)}; active_remote_tasks=0.
- raw_verdict: immutable `FAIL_TIMING_REPAIR_REQUIRED`; exact dialogue recall=1.0 but ASR 0.43-4.43 versus required 0.80-3.50. No unchanged retry.
- accepted_output: zero-credit synchronized picture+audio retime `{rel(REPAIRED)}` sha256={sha(REPAIRED)}; manual QA `{rel(accepted_path)}` sha256={sha(accepted_path)} status=PASS_ACCEPTED_U15C_ONLY.
- gate_results: canonical script+manifest SHA=PASS; two prechecks=PASS; exact native Mandarin recall=1.0 at 0.72-3.72 within 0.25s boundary tolerance; cadence=PASS; OCR=PASS_ZERO_RECOGNITIONS; age17 identity=PASS; visible mouth+native synchronized lip motion=PASS; envelope release=PASS; messenger hand-to-garment/no early ticket reveal=PASS; period+dusk environment=PASS; E37=STILL_CLOSED.
- qa_artifacts: postproduction `{rel(postproduction_path)}` sha256={sha(postproduction_path)}; native dialogue `{rel(REPAIRED_DIALOGUE)}` sha256={sha(REPAIRED_DIALOGUE)}; cadence `{rel(CADENCE)}` sha256={sha(CADENCE)}; OCR `{rel(OCR)}` sha256={sha(OCR)}; terminal `{rel(TERMINAL)}` sha256={sha(TERMINAL)}; terminal QA `{rel(terminal_qa_path)}` sha256={sha(terminal_qa_path)} status=PASS_CONTINUATION_AUTHORITY for U16A.
- credit_audit: `{rel(spend_path)}` sha256={sha(spend_path)}; exact net 5259=539 image+4720 video, gross Pay5459-Refund200, unknown=0, runway=741.
- cap_fit: `{rel(capfit_path)}` sha256={sha(capfit_path)}; seven remaining paid 5-second units=700, projected final=5959/6000, spare=41, approval_required=false.
- work_queue: `{rel(queue_path)}` sha256={sha(queue_path)}; E36 status ACTIVE_CAP_FIT_5959_U16A_PREPRODUCTION; blocked_by null; active_remote_tasks 0.
- next_action: compile and precheck only U16A from the accepted U15C terminal, submit on PASS, reconcile exact credits before U16B, preserve every FAIL, and keep E37 closed.
"""
existing = outbox.read_text(encoding="utf-8") if outbox.exists() else ""
if marker not in existing:
    with outbox.open("a", encoding="utf-8") as handle:
        handle.write(entry)

print(json.dumps({
    "status": "PASS_ACCEPTED_U15C_ONLY",
    "task_id": task["task_id"],
    "spend": 5259,
    "projected_final": 5959,
    "repaired_sha256": sha(REPAIRED),
    "terminal_sha256": sha(TERMINAL),
    "queue_sha256": sha(queue_path),
    "outbox_sha256": sha(outbox),
}, ensure_ascii=False, indent=2))
