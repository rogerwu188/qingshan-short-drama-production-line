#!/usr/bin/env python3
"""Preserve U17 local fallback failures and admit the corrected evidence insert."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa/e36_v2_stills_repair_20260729/u17_video_runtime"
ASSETS = ROOT / "working_assets/e36_v2_stills_20260728/u17_local_fallback"
V1 = ASSETS / "E36-CW-U17-LOCAL-HANDOFF-FROST-REVEAL-V1.mp4"
V2 = ASSETS / "E36-CW-U17-LOCAL-HANDOFF-FROST-REVEAL-V2.mp4"
V3 = ASSETS / "E36-CW-U17-LOCAL-HANDOFF-FROST-REVEAL-V3.mp4"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


expected = {
    V1: "ae10cefe4e0670f38595f7106e5c1a83358cf3495bf5e7f7b4534f17c3f7bbc7",
    V2: "6d7480170a843ca57201029f27f2568284f318463b68974797347b950eebc843",
    V3: "a72b589b77b85e07e399de7636cd0b19df766bfd5f302b020d80eecf8d6cf6cc",
}
for path, digest in expected.items():
    if sha(path) != digest:
        raise SystemExit(f"U17 local source changed: {path}")

v1_cadence = read(QA / "E36_U17_LOCAL_FALLBACK_FRAME_CADENCE_V1.json")
v1_ocr = read(QA / "E36_U17_LOCAL_FALLBACK_OCR_V1.json")
v2_cadence = read(QA / "E36_U17_LOCAL_FALLBACK_FRAME_CADENCE_V2.json")
v2_ocr = read(QA / "E36_U17_LOCAL_FALLBACK_OCR_V2.json")
v3_cadence = read(QA / "E36_U17_LOCAL_FALLBACK_FRAME_CADENCE_V3.json")
v3_ocr = read(QA / "E36_U17_LOCAL_FALLBACK_OCR_V3.json")
probe = read(QA / "E36_U17_LOCAL_FALLBACK_MEDIA_PROBE_V3.json")
if v1_cadence.get("status") != "FAIL" or v1_ocr.get("status") != "FAIL":
    raise SystemExit("U17 V1 failure evidence changed")
if v2_cadence.get("status") != "PASS" or v2_ocr.get("status") != "FAIL":
    raise SystemExit("U17 V2 mixed failure evidence changed")
if v3_cadence.get("status") != "PASS" or v3_ocr.get("status") != "PASS":
    raise SystemExit("U17 V3 automated gates did not pass")
if {s["codec_type"] for s in probe["streams"]} != {"video", "audio"}:
    raise SystemExit("U17 V3 media streams incomplete")

write(QA / "E36_U17_LOCAL_FALLBACK_FAILURE_LINEAGE_V1.json", {
    "schema": "qingshan.local_fallback_failure_lineage.v1",
    "episode": "E36", "unit_id": "U17", "status": "FAILURES_PRESERVED_SUPERSEDED_BY_V3",
    "generation_credits": 0,
    "failures": [
        {
            "version": "V1", "video": rel(V1), "sha256": sha(V1),
            "verdict": "FAIL_CADENCE_OCR_AND_VISUAL_FROST_MASK",
            "cadence_failures": v1_cadence["failures"],
            "ocr_failure": "Recurring 文家 misread and an unintegrated bright frost shape made the prop unreadable.",
            "contact_sheet": rel(QA / "E36_U17_LOCAL_FALLBACK_CONTACT_SHEET_V1.jpg"),
        },
        {
            "version": "V2", "video": rel(V2), "sha256": sha(V2),
            "verdict": "FAIL_TRANSITORY_PARTIAL_GLYPH_OCR",
            "cadence": "PASS",
            "ocr_failure": "At 2.5 seconds the slow partial reveal was read as 文家, which is not authorized prop text.",
            "contact_sheet": rel(QA / "E36_U17_LOCAL_FALLBACK_CONTACT_SHEET_V2.jpg"),
        },
    ],
    "unchanged_retry_allowed": False,
})

manual = {
    "schema": "qingshan.manual_source_video_qa.v1",
    "episode": "E36", "unit_id": "U17", "source_segment_id": "E36-CW-U17",
    "status": "PASS_ACCEPTED_U17_LOCAL_FALLBACK_ONLY",
    "accepted_video": rel(V3), "accepted_video_sha256": sha(V3),
    "generation_credits": 0, "dialogue_required": False,
    "canonical_beat": "Chenji takes the old ticket; attached frost moves left-to-right and reveals the exact 刘家 stamp while the messenger remains the preceding owner.",
    "review_evidence": {
        "contact_sheet": rel(QA / "E36_U17_LOCAL_FALLBACK_CONTACT_SHEET_V3.jpg"),
        "contact_sheet_sha256": sha(QA / "E36_U17_LOCAL_FALLBACK_CONTACT_SHEET_V3.jpg"),
        "full_duration_direct_review": "PASS",
    },
    "checks": {
        "predecessor_real_reach_motion": "PASS_FIRST_0P667_SECONDS_FROM_ACCEPTED_U16B",
        "cut_motivation": "PASS_EVIDENCE_DETAIL_MATCH_ACTION",
        "ticket_contact_and_ownership_read": "PASS_REACH_TO_BOTH_HAND_SUPPORT",
        "frost_attachment": "PASS_TICKET_SURFACE_ONLY_NO_FOG",
        "frost_direction": "PASS_LEFT_TO_RIGHT",
        "intermediate_state": "PASS_STAMP_MASKED_BEFORE_DECISIVE_SWEEP",
        "terminal_exact_text": "PASS_LIU_JIA_ONLY",
        "chenji_age17_continuity": "PASS_YOUNG_CHENJI_GREY_PERIOD_ROBE",
        "period_and_scene": "PASS_TAIPING_CLINIC_INTERIOR",
        "environment_life": "PASS_CANDLE_FLICKER_AND_ATTACHED_FROST_GRAIN",
        "frame_cadence": "PASS_NO_FREEZE_NO_PERIODIC_CHAIN",
        "ocr": "PASS_ONLY_AUTHORIZED_LIU_JIA",
        "audio": "PASS_MONO_48KHZ_ZERO_CREDIT_ROOM_TONE_NO_DIALOGUE",
        "modern_objects": "PASS_NONE",
    },
    "diagnostics_not_greenwash": {
        "motion_mean": v3_cadence["motion_mean"],
        "near_duplicate_ratio": v3_cadence["periodic_duplicates"]["near_duplicate_ratio"],
        "interpretation": "High near-duplicate density is retained as an honest diagnostic because U17 is a five-second evidence insert, not the U06/U07 fight climax. Admission rests on the real reach lead-in and visible frost/text state change, not a motion target.",
    },
    "limitations": [
        "The ownership transfer is conveyed by a motivated match-action cut from the accepted real reach into the two-hand evidence detail, not by a continuous wide shot.",
        "The exact 刘家 stamp is a deterministic local prop repair replacing model-rendered pseudo-glyphs; it may be used only for U17.",
    ],
}
write(QA / "E36_U17_LOCAL_FALLBACK_MANUAL_QA_V1.json", manual)

cap = {
    "schema": "qingshan.e36_cap_state.v2", "episode": "E36",
    "status": "PASS_U17_LOCAL_ACCEPTED_U06_U07_FALLBACK_QA_PENDING",
    "actual_credits": 5863, "actual_breakdown": {"image": 561, "video": 5292, "audio": 10},
    "budget_cap": 6000, "headroom": 137, "approval_required": False,
    "paid_coverage": "COMPLETE",
    "zero_credit_fallbacks": {
        "U17": {"status": "PASS_ACCEPTED", "video": rel(V3), "sha256": sha(V3), "new_credits": 0},
        "U06": {"status": "PENDING_BUILD_AND_CONTACT_QA", "new_credits": 0},
        "U07": {"status": "PENDING_BUILD_AND_CONTACT_QA", "new_credits": 0},
    },
    "release_gate": "U06_AND_U07_MUST_PASS_FIGHT_ACTION_READ_MOTION_CADENCE_OCR_AND_FULL_HUMAN_REVIEW_BEFORE_AGENTCUT",
    "active_remote_tasks": 0, "unknown_success_credits": 0, "e37_production_opened": False,
}
write(ROOT / "qa/e36_v2_stills_repair_20260729/E36_CAP_STATE_5863_AFTER_U17_LOCAL_V11.json", cap)

queue_path = ROOT / "workflow/work_queue.json"
queue = read(queue_path)
now = datetime.now().astimezone().isoformat(timespec="seconds")
note = ("U17 zero-credit local fallback V1 preserved FAIL for cadence/OCR and an unintegrated frost mask; V2 preserved FAIL because the slow partial reveal rendered an unauthorized 文家 reading. Materially corrected V3 uses the accepted U16B reach lead-in, a motivated evidence-detail match cut, deterministic exact 刘家 stamp repair, decisive left-to-right attached-frost reveal and non-dialogue room tone. V3 passed cadence, exact-text OCR, media and direct full-duration contact/reveal review and is accepted for U17 only at0 new credits. E36 remains5863/6000 with137 headroom and active tasks0. U06/U07 zero-credit fight fallbacks remain mandatory before AgentCut; E37 remains unopened.")
queue.update({"updated_at": now, "updated_note_latest": note, "status": "E36_PRODUCTION_ACTIVE_U06_U07_LOCAL_FALLBACK_QA_CAP_5863", "real_active_handle_count": 0})
line = queue["lines"]["E36"]
line.update({
    "status": "ACTIVE_CAP_5863_U17_LOCAL_ACCEPTED_U06_U07_LOCAL_FALLBACK_QA_PENDING",
    "current_phase": note, "blocked_by": None,
    "local_pid": None, "running_or_pending_task_ids": [],
    "next_action": "Build U06 and U07 zero-credit local fight candidates from accepted anchors. Require true contact/force-direction/terminal-state readability, first-frame motion, no freeze or periodic cadence, OCR, period/identity continuity and full human temporal review. Do not admit a static slideshow or advance AgentCut until both pass; keep E37 closed.",
    "latest_u17_evidence": "Paid remote task 8ea10d64 failed/refunded net0 and remains preserved. Zero-credit local V1/V2 failures are preserved. V3 accepted sha" + sha(V3)[:8] + " with accepted U16B reach lead-in, match-action ownership transfer, exact 刘家 frost reveal, cadence PASS, OCR PASS and direct review PASS. Actual5863; U06/U07 local fight fallbacks remain.",
})
write(queue_path, queue)

print(json.dumps({"status": manual["status"], "accepted_sha256": sha(V3), "actual_credits": 5863, "remaining_fallbacks": ["U06", "U07"]}, ensure_ascii=False))
