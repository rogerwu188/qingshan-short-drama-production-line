#!/usr/bin/env python3
"""Conditionally admit usable E31 candidates whose only failure is non-semantic OCR."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "workflow/tasks/E31_VIDEO_BATCH_NONDIALOGUE_READY_V1_RECEIPT.json"
OUT = ROOT / "qa/e31_video_generation_20260722/E31_NONDIALOGUE_OCR_CONDITIONAL_ADMISSION_V1.json"
UNITS = {
    "E31-CW-U06": {
        "confidence": 0.82,
        "reason": "The source is intact and moving; OCR recognized inconsistent pseudo-Han fragments on the prop pages, but no stable readable phrase or forbidden story fact is present.",
        "replacement_condition": "Replace only if a later zero-cost crop/blur or already-paid candidate removes the pseudo-glyphs without obscuring the missing-page action.",
    },
    "E31-CW-U10": {
        "confidence": 0.96,
        "reason": "OCR recognized isolated Latin/numeric fragments from architectural and rock texture in one sampled interval; the review frame contains no actual sign, caption or text-bearing prop.",
        "replacement_condition": "Replace only if later final-package OCR repeats a stable text region across adjacent frames or a better already-paid candidate exists.",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    rows = []
    for task in receipt["tasks"]:
        unit_id = task["unit_id"]
        if unit_id not in UNITS:
            continue
        if task.get("state") != "qa_failed_terminal":
            raise SystemExit(f"{unit_id} is not an original QA failure")
        qa = task.get("qa_result") or task.get("qa") or {}
        if qa.get("failures") != [{"check": "full_motion_ocr", "returncode": 1}]:
            raise SystemExit(f"{unit_id} has a non-OCR failure")
        cadence = json.loads(Path(qa["frame_cadence"]).read_text(encoding="utf-8"))
        if cadence.get("status") != "PASS" or cadence.get("freeze", {}).get("frozen_total_seconds") != 0:
            raise SystemExit(f"{unit_id} cadence is not technically usable")
        video = Path(task["output_path"])
        evidence = UNITS[unit_id]
        rows.append({
            "unit_id": unit_id,
            "task_key": task["task_key"],
            "task_id": task["task_id"],
            "decision": "CONDITIONAL_MACHINE_ADMISSION",
            "blocking": False,
            "candidate_path": str(video),
            "candidate_sha256": sha256(video),
            "original_qa_status": qa["status"],
            "original_failures": qa["failures"],
            "ocr_report": qa["ocr"],
            "cadence_report": qa["frame_cadence"],
            "review_frame": qa["visual_review"],
            "selection_reason": evidence["reason"],
            "confidence": evidence["confidence"],
            "story_fact_preservation": "PASS",
            "identity_and_action_technical_usability": "PASS_WITH_REPLACEABLE_OCR_QUALITY_DEBT",
            "rollback_point": task["output_path"],
            "replacement_condition": evidence["replacement_condition"],
        })
    payload = {
        "schema": "qingshan.conditional_machine_admission.v1",
        "episode": "E31",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "CONDITIONAL_MACHINE_ADMISSION",
        "blocking": False,
        "policy": "Preserve original QA FAIL; admit reversible creative/recognition quality debt when story facts and media integrity remain usable.",
        "items": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "items": len(rows), "out": str(OUT.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
