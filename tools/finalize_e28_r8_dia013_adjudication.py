#!/usr/bin/env python3
"""Promote E28 DIA-013 after SHA-bound OCR adjudication and AI review."""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "workflow/tasks/E28_STANDARD_STORYBOARD_V1_SHEETBOUND_FAILED_ONLY_R8_DIA013_MOTION_REPAIR_RECEIPT_20260720.json"
OCR = ROOT / "qa/e28_standard_storyboard_v1_sheetbound_failed_only_r8_dia013_motion_repair_20260720/E28-DIA-013-VIDEO_ocr_normalized_decision.json"
AI_REVIEW = ROOT / "qa/e28_standard_storyboard_v1_sheetbound_failed_only_r8_dia013_motion_repair_20260720/E28_DIA013_AI_REVIEW_RESULT.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write_atomic(path: Path, payload: dict) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> int:
    receipt = load(RECEIPT)
    task = receipt["tasks"][0]
    source = Path(task["output_path"])
    source_sha = digest(source)
    ocr = load(OCR)
    review = load(AI_REVIEW)
    cadence = load(Path(task["qa"]["frame_cadence"]))
    if source_sha != task.get("sha256") or source_sha != ocr.get("source_sha256"):
        raise SystemExit("DIA-013 adjudication is not bound to the harvested SHA")
    if ocr.get("status") != "PASS" or ocr.get("critical_text_failures") != 0:
        raise SystemExit("normalized OCR gate is not PASS")
    if cadence.get("status") != "PASS":
        raise SystemExit("cadence gate is not PASS")
    if review.get("status") != "PASS" or review.get("summary", {}).get("failed") != 0:
        raise SystemExit("AI review is not PASS")
    recorded_at = datetime.now().astimezone().isoformat(timespec="seconds")
    task["state"] = "qa_pass"
    task["status"] = "QA_PASS_AFTER_SHA_BOUND_MACHINE_ADJUDICATION"
    task["qa"] = {
        "status": "PASS",
        "raw_ocr": task["qa"]["ocr"],
        "normalized_ocr": str(OCR),
        "frame_cadence": task["qa"]["frame_cadence"],
        "ai_review": str(AI_REVIEW),
        "visual_review": task["qa"]["visual_review"],
        "confidence": 0.99,
        "recorded_at": recorded_at,
    }
    task["failure_evidence"] = []
    task["settled_at"] = recorded_at
    receipt["status"] = "BATCH_COMPLETE"
    receipt["active_task_ids"] = []
    receipt["active_task_count"] = 0
    receipt["completed_at"] = recorded_at
    receipt["last_action_at"] = recorded_at
    receipt["last_action"] = "dia013_sha_bound_ocr_and_ai_review_pass_all_36_sources_ready"
    receipt["retained_pass_count"] = 35
    receipt["current_batch_pass_count"] = 1
    receipt["episode_source_pass_count"] = 36
    receipt["episode_source_expected_count"] = 36
    receipt["next_action"] = "COMPILE_UNIQUE_SOURCE_MANIFEST_AND_START_AGENTCUT"
    write_atomic(RECEIPT, receipt)
    print(json.dumps({"status": "BATCH_COMPLETE", "episode_source_pass_count": 36, "source_sha256": source_sha}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
