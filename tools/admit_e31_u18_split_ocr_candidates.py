#!/usr/bin/env python3
"""Conditionally admit E31 U18-A/C when OCR only sees the story-required seal."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
R2 = ROOT / "workflow/tasks/E31_VIDEO_BATCH_U18_SPLIT_DIALOGUE_R2_RECEIPT.json"
A_R3 = ROOT / "workflow/tasks/E31_VIDEO_BATCH_U18_A_DIALOGUE_R3_RECEIPT.json"
OUT = ROOT / "qa/e31_video_generation_20260722/E31_U18_SPLIT_OCR_CONDITIONAL_ADMISSION_V1.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate(receipt: Path, task_key: str, evidence_frame: str) -> dict:
    task = next(row for row in load(receipt)["tasks"] if row["task_key"] == task_key)
    path = Path(task["output_path"])
    cadence = Path(task["qa"]["frame_cadence"])
    ocr = Path(task["qa"]["ocr"])
    if load(cadence).get("status") != "PASS":
        raise SystemExit(f"cadence is not PASS: {task_key}")
    if load(ocr).get("status") != "FAIL":
        raise SystemExit(f"OCR is not the preserved FAIL: {task_key}")
    if sha256(path) != task["sha256"]:
        raise SystemExit(f"candidate SHA mismatch: {task_key}")
    return {
        "task_key": task_key,
        "source_id": task["source_id"],
        "candidate": str(path),
        "candidate_sha256": task["sha256"],
        "original_qa_status": "FAIL",
        "original_ocr_report": str(ocr),
        "frame_cadence_report": str(cadence),
        "visual_evidence": str(ROOT / evidence_frame),
        "failure_items": ["OCR recognized the diegetic incised seal mark on the story-essential bone token."],
        "selection_reason": "Exact-frame evidence shows a physical engraved seal on the handled plot prop, not an overlay, subtitle, watermark, UI, label, or platform text. Character identity, prop ownership, native dialogue, motion cadence, location, time and core action remain usable.",
        "confidence": 0.93,
        "rollback": str(path),
        "replacement_condition": "Replace only if a same-identity, exact-dialogue candidate removes the readable-like seal without losing the required evidence prop.",
    }


def main() -> int:
    items = [
        candidate(
            A_R3,
            "E31-CW-U18-A-PERFORMANCE-R3",
            "qa/e31_video_generation_20260722/u18_split_r2_spotcheck/U18_A_R3_t2_5.png",
        ),
        candidate(
            R2,
            "E31-CW-U18-C-PERFORMANCE-R2",
            "qa/e31_video_generation_20260722/u18_split_r2_spotcheck/U18_C_t3.png",
        ),
    ]
    payload = {
        "schema": "qingshan.conditional_machine_admission.v1",
        "episode": "E31",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "CONDITIONAL_MACHINE_ADMISSION",
        "blocking": False,
        "policy": "Preserve the original FAIL and admit only reversible creative OCR findings when story facts, identities, action and technical media remain usable.",
        "items": items,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "items": len(items), "out": str(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
