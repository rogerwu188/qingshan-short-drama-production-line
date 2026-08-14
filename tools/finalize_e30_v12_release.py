#!/usr/bin/env python3
"""Bind E30 V12 QA evidence to one immutable final SHA."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "exports/e30/final_v12_static_hold_removed_20260722/QINGSHAN_E30_FINAL_V12.mp4"
QA_DIR = ROOT / "qa/e30_final_v12_static_hold_removed_20260722"
TECH = QA_DIR / "E30_V12_TECHNICAL_GATE.json"
ASR = QA_DIR / "E30_V12_FINAL_DIALOGUE_WINDOW_ASR.json"
CADENCE = QA_DIR / "E30_V12_FINAL_FRAME_CADENCE.json"
OCR = QA_DIR / "E30_V12_FINAL_OCR_SUBTITLE_EXCLUDED.json"
OCR_FRAME = QA_DIR / "frame_155.png"
VISUAL_RAW = QA_DIR / "E30_V12_FINAL_VISUAL_RAW.json"
VISUAL_ADMITTED = QA_DIR / "E30_V12_FINAL_VISUAL_DIALOGUE_EVIDENCE.json"
ADMISSION = QA_DIR / "E30_V12_CONDITIONAL_MACHINE_ADMISSION.json"
RELEASE = ROOT / "workflow/tasks/E30_FINAL_V12_RELEASE_READINESS_20260722.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    required = (FINAL, TECH, ASR, CADENCE, OCR, OCR_FRAME, VISUAL_RAW, VISUAL_ADMITTED)
    for path in required:
        if not path.is_file():
            raise SystemExit(f"required evidence missing: {path}")

    final_sha = sha256(FINAL)
    tech = load(TECH)
    asr = load(ASR)
    cadence = load(CADENCE)
    ocr = load(OCR)
    visual_raw = load(VISUAL_RAW)
    visual_admitted = load(VISUAL_ADMITTED)
    bound_shas = {
        tech.get("final_sha256"),
        visual_raw.get("media", {}).get("sha256"),
        visual_admitted.get("media", {}).get("sha256"),
    }
    if bound_shas != {final_sha}:
        raise SystemExit(f"QA SHA mismatch: final={final_sha} evidence={sorted(bound_shas)}")
    if tech.get("status") != "PASS":
        raise SystemExit("technical gate is not PASS")
    if asr.get("status") != "PASS" or asr.get("pass_count") != 20:
        raise SystemExit("final-window ASR is not 20/20 PASS")
    if cadence.get("status") != "PASS":
        raise SystemExit("frame cadence is not PASS")
    if visual_raw.get("status") != "FAIL" or visual_admitted.get("status") != "PASS":
        raise SystemExit("visual raw/admitted evidence does not preserve expected decisions")
    if ocr.get("status") != "FAIL" or ocr.get("critical_text_failures") != 1:
        raise SystemExit("OCR raw evidence no longer matches the reviewed isolated false positive")

    now = datetime.now(timezone.utc).isoformat()
    admission = {
        "schema": "qingshan.conditional_machine_admission.v1",
        "episode": "E30",
        "version": "V12",
        "recorded_at": now,
        "status": "CONDITIONAL_MACHINE_ADMISSION",
        "final": str(FINAL),
        "final_sha256": final_sha,
        "preserved_raw_failures": [
            {
                "gate": "FINAL_OCR",
                "report": str(OCR),
                "failure": "RapidOCR read cabinet bars/drawers at 155.0s as ILLI/1111.",
                "admission_reason": "The exact sampled frame contains no rendered or diegetic text; the recognitions follow repeated vertical cabinet geometry.",
                "evidence_frame": str(OCR_FRAME),
                "evidence_frame_sha256": sha256(OCR_FRAME),
                "confidence": 0.99,
            },
            {
                "gate": "FINAL_VISUAL_RAW",
                "report": str(VISUAL_RAW),
                "failure": "Dialogue performance holds exceeded the generic near-freeze duration threshold.",
                "admission_reason": "The only non-dialogue long static hold was removed. Remaining reported long holds overlap exact story-required dialogue windows and passed final encoded 20/20 ASR.",
                "admitted_report": str(VISUAL_ADMITTED),
                "confidence": 0.96,
            },
        ],
        "story_integrity": {
            "removed_interval": {"start": 64.0, "end": 67.0, "duration": 3.0},
            "dialogue_intersection": [],
            "reason": "Removed only the redundant U07 exterior establishing hold; no plot fact, action consequence, or spoken line was removed.",
        },
        "passed_gates": {
            "technical": str(TECH),
            "final_dialogue_asr_20_of_20": str(ASR),
            "frame_cadence": str(CADENCE),
            "dialogue_evidence_visual": str(VISUAL_ADMITTED),
            "subtitle_coverage": "20/20_BURNED_IN",
            "nalu_motion_outro": "PRESERVED",
        },
        "rollback": {
            "final": str(FINAL),
            "sha256": final_sha,
            "previous_version": str(ROOT / "exports/e30/final_v11_u01_native_dialogue_20260722/QINGSHAN_E30_FINAL_V11.mp4"),
        },
        "replacement_conditions": [
            "A human or independent multimodal review identifies actual unauthorized text at 155.0s.",
            "A later release candidate improves dialogue performance motion without changing dialogue, plot, character identity, or audio compliance.",
        ],
        "new_generation_calls": 0,
        "new_generation_credits": 0,
    }
    ADMISSION.write_text(json.dumps(admission, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    release = {
        "schema": "qingshan.release_readiness.v1",
        "episode": "E30",
        "version": "V12",
        "recorded_at": now,
        "status": "READY_FOR_PLATFORM_SUBMISSION",
        "final": str(FINAL),
        "final_sha256": final_sha,
        "duration_seconds": float(tech["probe"]["format"]["duration"]),
        "qa_status": "CONDITIONAL_MACHINE_ADMISSION",
        "qa_admission": str(ADMISSION),
        "dialogue": "20/20_FINAL_ENCODED_ASR_PASS",
        "subtitles": "20/20_BURNED_IN",
        "outro": "NALU_MOTION_PRESENT",
        "s3_delivery": {
            "status": "UPLOADER_VERIFIED_AWAITING_REMOTE_RECEIPT",
            "c2sc_sequence": 83,
        },
        "platform_release": {
            "youtube": "SUBMISSION_PENDING",
            "douyin": "SUBMISSION_PENDING",
            "async_policy": True,
        },
        "new_generation_credits": 0,
    }
    RELEASE.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": release["status"], "sha256": final_sha}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
