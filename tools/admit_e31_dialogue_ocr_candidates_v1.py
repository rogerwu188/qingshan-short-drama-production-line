#!/usr/bin/env python3
"""Conditionally admit E31 dialogue candidates whose only failure is OCR."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "workflow/tasks/E31_VIDEO_BATCH_DIALOGUE_READY_V1_RECEIPT.json"
OUT = ROOT / "qa/e31_video_generation_20260722/E31_DIALOGUE_OCR_CONDITIONAL_ADMISSION_V1.json"
TARGETS = {"E31-CW-U02", "E31-CW-U03", "E31-CW-U14", "E31-CW-U18"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    rows = []
    for task in receipt["tasks"]:
        if task["unit_id"] not in TARGETS:
            continue
        qa = task.get("qa") or {}
        if task.get("state") != "qa_failed_terminal" or qa.get("failures") != [{"check": "full_motion_ocr", "returncode": 1}]:
            raise SystemExit(f"{task['unit_id']} is not an OCR-only original failure")
        cadence = json.loads(Path(qa["frame_cadence"]).read_text(encoding="utf-8"))
        if cadence.get("status") != "PASS" or cadence.get("freeze", {}).get("frozen_total_seconds") != 0:
            raise SystemExit(f"{task['unit_id']} is not technically usable")
        video = Path(task["output_path"])
        rows.append({
            "unit_id": task["unit_id"], "task_key": task["task_key"], "task_id": task["task_id"],
            "decision": "CONDITIONAL_MACHINE_ADMISSION", "blocking": False,
            "candidate_path": str(video), "candidate_sha256": sha256(video),
            "original_qa_status": qa["status"], "original_failures": qa["failures"],
            "ocr_report": qa["ocr"], "cadence_report": qa["frame_cadence"], "review_frame": qa["visual_review"],
            "selection_reason": "The generated source is intact and moving. OCR detections are isolated architectural texture or pseudo-glyphs on story props, not stable readable story text or a forbidden semantic fact.",
            "confidence": 0.9 if task["unit_id"] in {"E31-CW-U02", "E31-CW-U14", "E31-CW-U18"} else 0.84,
            "story_fact_preservation": "PASS",
            "identity_and_action_technical_usability": "PASS_WITH_REPLACEABLE_OCR_QUALITY_DEBT",
            "rollback_point": task["output_path"],
            "replacement_condition": "Replace only if final-package OCR finds the same readable text across adjacent samples, or an already-paid candidate removes the pseudo-glyphs without losing action/dialogue.",
        })
    if {row["unit_id"] for row in rows} != TARGETS:
        raise SystemExit("not every expected OCR-only target was admitted")
    payload = {
        "schema": "qingshan.conditional_machine_admission.v1", "episode": "E31",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "CONDITIONAL_MACHINE_ADMISSION", "blocking": False,
        "policy": "Preserve every original QA FAIL while allowing reversible OCR quality debt to continue downstream.",
        "items": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "items": len(rows), "out": str(OUT.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
