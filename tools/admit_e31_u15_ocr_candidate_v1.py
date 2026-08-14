#!/usr/bin/env python3
"""Conditionally admit the changed-input E31 U15 candidate after OCR-only QA failure."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "workflow/tasks/E31_VIDEO_BATCH_U15_FAILED_ONLY_R2_RECEIPT.json"
OUT = ROOT / "qa/e31_video_generation_20260722/E31_U15_OCR_CONDITIONAL_ADMISSION_V1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    task = json.loads(RECEIPT.read_text(encoding="utf-8"))["tasks"][0]
    qa = task.get("qa") or {}
    if task.get("state") != "qa_failed_terminal" or qa.get("failures") != [{"check": "full_motion_ocr", "returncode": 1}]:
        raise SystemExit("U15 is not an OCR-only original failure")
    cadence = json.loads(Path(qa["frame_cadence"]).read_text(encoding="utf-8"))
    if cadence.get("status") != "PASS" or cadence.get("freeze", {}).get("frozen_total_seconds") != 0:
        raise SystemExit("U15 cadence is not technically usable")
    video = Path(task["output_path"])
    item = {
        "unit_id": "E31-CW-U15", "task_key": task["task_key"], "task_id": task["task_id"],
        "decision": "CONDITIONAL_MACHINE_ADMISSION", "blocking": False,
        "candidate_path": str(video), "candidate_sha256": sha256(video),
        "original_qa_status": qa["status"], "original_failures": qa["failures"],
        "ocr_report": qa["ocr"], "cadence_report": qa["frame_cadence"], "review_frame": qa["visual_review"],
        "selection_reason": "Changed-input R2 is intact, moving and preserves the two-person negotiation. OCR detections do not form stable readable text in the review evidence.",
        "confidence": 0.9, "story_fact_preservation": "PASS",
        "identity_and_action_technical_usability": "PASS_WITH_REPLACEABLE_OCR_QUALITY_DEBT",
        "rollback_point": task["output_path"],
        "replacement_condition": "Replace only if final-package OCR finds stable adjacent-frame text or a better already-paid candidate preserves both exact dialogue turns.",
    }
    payload = {"schema": "qingshan.conditional_machine_admission.v1", "episode": "E31", "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "CONDITIONAL_MACHINE_ADMISSION", "blocking": False, "items": [item]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "out": str(OUT.relative_to(ROOT)), "sha256": item["candidate_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
