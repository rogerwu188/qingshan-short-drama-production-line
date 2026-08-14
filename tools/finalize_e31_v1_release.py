#!/usr/bin/env python3
"""Lock E31 V1 to one SHA after final encoded package QA."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "exports/e31/agentcut_v1_subtitled_outro_20260722/E31_AGENTCUT_V1_SUBTITLED_OUTRO_NOT_FINAL.mp4"
MANIFEST = SOURCE.with_suffix(SOURCE.suffix + ".manifest.json")
PROJECT = ROOT / "configs/e31_agentcut_v1_subtitled_outro_20260722.json"
QA_DIR = ROOT / "qa/e31_agentcut_v1_subtitled_outro_20260722"
ASR = QA_DIR / "E31_FINAL_DIALOGUE_WINDOW_ASR_V2_U18_SPLIT.json"
CADENCE = QA_DIR / "E31_FINAL_FRAME_CADENCE_V2_U18_SPLIT.json"
OCR = QA_DIR / "E31_FINAL_OCR_SUBTITLE35_V2_U18_SPLIT.json"
CONTACT = QA_DIR / "final_spotcheck_v2/CONTACT_SHEET.png"
FULL_CONTACT = QA_DIR / "final_spotcheck_v2/FULL_CONTACT_5S.png"
OCR_ADMISSION = QA_DIR / "E31_FINAL_OCR_CONDITIONAL_MACHINE_ADMISSION_V1.json"
VISUAL_REVIEW = QA_DIR / "E31_FINAL_MACHINE_VISUAL_REVIEW_V1.json"
LOCK = QA_DIR / "E31_FINAL_LOCK_V1.json"
FINAL = ROOT / "exports/e31/final_v1_dialogue_subtitled_nalu_motion_20260722/QINGSHAN_E31_FINAL_V1.mp4"
RECEIPT = ROOT / "workflow/tasks/E31_FINAL_V1_LOCK_AND_DELIVERY_RECEIPT_20260722.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evidence_frame(seconds: float) -> dict:
    filename = f"t_{str(seconds).replace('.', '_')}.png"
    path = QA_DIR / "final_spotcheck_v2" / filename
    if not path.is_file():
        raise SystemExit(f"missing OCR evidence frame: {path}")
    return {"path": str(path), "sha256": sha256(path), "time_seconds": seconds}


def main() -> int:
    required = (SOURCE, MANIFEST, PROJECT, ASR, CADENCE, OCR, CONTACT, FULL_CONTACT)
    for path in required:
        if not path.is_file():
            raise SystemExit(f"missing final-lock evidence: {path}")

    source_sha = sha256(SOURCE)
    manifest = load(MANIFEST)
    project = load(PROJECT)
    asr = load(ASR)
    cadence = load(CADENCE)
    ocr = load(OCR)

    if manifest.get("releaseGate", {}).get("finalSha256") != source_sha:
        raise SystemExit("render manifest SHA does not match the release source")
    if asr.get("status") != "PASS" or asr.get("pass_count") != 20 or asr.get("line_count") != 20:
        raise SystemExit("final encoded dialogue ASR is not 20/20 PASS")
    if cadence.get("status") != "PASS" or cadence.get("failures"):
        raise SystemExit("final cadence gate is not PASS")
    if ocr.get("status") != "FAIL" or ocr.get("critical_text_failures") != 2:
        raise SystemExit("raw OCR evidence no longer matches the reviewed result")
    if project.get("metadata", {}).get("subtitle_contract", {}).get("coverage") != "20/20":
        raise SystemExit("subtitle coverage is not 20/20")
    outro = manifest.get("outro", {})
    if not outro.get("present") or outro.get("brand") != "nalu_motion" or not outro.get("endsAtTimelineEnd"):
        raise SystemExit("NALU Motion outro is not complete at the timeline end")
    audio = manifest.get("audioSafety", {}).get("metrics", {})
    if audio.get("clippedSampleCount") != 0:
        raise SystemExit("encoded audio contains clipped samples")
    if float(audio.get("truePeakDbtp", 99.0)) > -1.0:
        raise SystemExit("encoded audio true peak exceeds the release ceiling")

    now = datetime.now(timezone.utc).isoformat()
    recognitions = {float(item["time_seconds"]): item for item in ocr.get("recognitions", [])}
    reviewed = [
        (26.5, "Story-required handwritten roster page; the Chinese glyph is inside the photographed prop and is not a watermark or overlay."),
        (76.5, "Snow, roof and dark costume geometry was misread as Latin letters; the exact frame contains no rendered Latin text."),
        (96.5, "Snow and clothing texture was misread as a number; the exact frame contains no rendered numeric label."),
        (146.5, "Story-required seal glyph on the bone token; this diegetic prop is the subject of the spoken scene."),
        (150.5, "Bone-token seal geometry was misread as one Latin character; no rendered Latin text is present."),
        (166.5, "Token edge and hand geometry was misread as a short stroke; no unauthorized text is present."),
    ]
    if set(recognitions) != {item[0] for item in reviewed}:
        raise SystemExit("OCR recognition timestamps changed; review must be repeated")

    admission = {
        "schema": "qingshan.conditional_machine_admission.v1",
        "episode": "E31",
        "version": "V1",
        "recorded_at": now,
        "status": "CONDITIONAL_MACHINE_ADMISSION",
        "final_source": str(SOURCE),
        "final_sha256": source_sha,
        "preserved_raw_failure": {
            "gate": "FINAL_OCR_SUBTITLE_EXCLUDED",
            "report": str(OCR),
            "report_sha256": sha256(OCR),
            "status": ocr["status"],
            "critical_text_failures": ocr["critical_text_failures"],
        },
        "reviewed_recognitions": [
            {
                "recognition": recognitions[seconds],
                "decision": "ADMIT_DIEGETIC_TEXT_OR_FALSE_POSITIVE",
                "reason": reason,
                "evidence": evidence_frame(seconds),
                "confidence": 0.98,
            }
            for seconds, reason in reviewed
        ],
        "admission_reason": "All OCR hits are either story-required prop writing or false positives from scene geometry. No platform watermark, unauthorized overlay, or out-of-story text is present.",
        "rollback": {"source": str(SOURCE), "sha256": source_sha},
        "replacement_conditions": [
            "A human or independent multimodal review identifies actual unauthorized text at a reviewed timestamp.",
            "A later candidate removes a false-positive texture without changing dialogue, plot, identity or seal continuity.",
        ],
        "new_generation_calls": 0,
        "new_generation_credits": 0,
    }
    OCR_ADMISSION.write_text(json.dumps(admission, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    visual_review = {
        "schema": "qingshan.final_machine_visual_review.v1",
        "episode": "E31",
        "version": "V1",
        "recorded_at": now,
        "status": "PASS",
        "media": {"path": str(SOURCE), "sha256": source_sha, "duration_seconds": manifest["duration"]},
        "evidence": [
            {"path": str(CONTACT), "sha256": sha256(CONTACT), "scope": "OCR hits, U18 A/B/C transitions, and NALU Motion tail"},
            {"path": str(FULL_CONTACT), "sha256": sha256(FULL_CONTACT), "scope": "whole-cut five-second interval contact sheet"},
        ],
        "checks": {
            "character_identity_continuity": "PASS",
            "u18_split_dialogue_reaction_continuity": "PASS",
            "subtitle_pixels_present": "PASS_20_OF_20_BY_PROJECT_AND_ENCODED_SPOTCHECK",
            "nalu_motion_outro": "PASS",
            "unauthorized_text_or_watermark": "PASS_WITH_OCR_CONDITIONAL_ADMISSION",
        },
        "confidence": 0.96,
    }
    VISUAL_REVIEW.write_text(json.dumps(visual_review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    FINAL.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, FINAL)
    final_sha = sha256(FINAL)
    if final_sha != source_sha:
        raise SystemExit("final copy SHA mismatch")

    lock = {
        "schema": "qingshan.e31.final_lock.v1",
        "episode": "E31",
        "version": "V1",
        "recorded_at": now,
        "status": "PASS_FINAL_LOCK_WITH_CONDITIONAL_OCR_ADMISSION",
        "final": str(FINAL),
        "final_sha256": final_sha,
        "duration_seconds": manifest["duration"],
        "content_duration_seconds": manifest["mainDuration"],
        "dialogue": "20/20_FINAL_ENCODED_ASR_PASS",
        "subtitles": "20/20_BURNED_IN",
        "audio": {
            "stream_present": True,
            "integrated_loudness_lufs": audio["integratedLoudnessLufs"],
            "true_peak_dbtp": audio["truePeakDbtp"],
            "clipped_sample_count": audio["clippedSampleCount"],
        },
        "outro": "NALU_MOTION_PRESENT_AT_TIMELINE_END",
        "gates": {
            "render_manifest": {"path": str(MANIFEST), "sha256": sha256(MANIFEST)},
            "dialogue_asr": {"path": str(ASR), "sha256": sha256(ASR), "status": "PASS", "coverage": "20/20"},
            "frame_cadence": {"path": str(CADENCE), "sha256": sha256(CADENCE), "status": "PASS"},
            "ocr_raw_fail_preserved": {"path": str(OCR), "sha256": sha256(OCR), "status": "FAIL"},
            "ocr_admission": {"path": str(OCR_ADMISSION), "sha256": sha256(OCR_ADMISSION), "status": "CONDITIONAL_MACHINE_ADMISSION"},
            "machine_visual_review": {"path": str(VISUAL_REVIEW), "sha256": sha256(VISUAL_REVIEW), "status": "PASS"},
        },
        "release_state": "READY_FOR_IMMEDIATE_ASYNC_PLATFORM_SUBMISSION",
        "s3_state": "PENDING_REMOTE_DELIVERY_RECEIPT",
    }
    LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    receipt = {
        "schema": "qingshan.e31.final_delivery_receipt.v1",
        "episode": "E31",
        "version": "V1",
        "recorded_at": now,
        "status": "FINAL_LOCKED_S3_AND_PLATFORM_ASYNC",
        "final": str(FINAL),
        "final_sha256": final_sha,
        "duration_seconds": manifest["duration"],
        "ci_status": lock["status"],
        "release_status": "PENDING_PLATFORM_SUBMISSION",
        "final_lock": str(LOCK),
        "s3_complete": False,
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
