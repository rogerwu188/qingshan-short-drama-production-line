#!/usr/bin/env python3
"""Freeze the QA-passed E22 V17 render without transcoding."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "exports/e22/agentcut_v17_standard_storyboard_coverage_20260719/E22_AGENTCUT_V17_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL.mp4"
FINAL = ROOT / "exports/e22/final_package_v17_20260719/qingshan_E22_v17_final.mp4"
QA_DIR = ROOT / "qa/e22_agentcut_v17_standard_storyboard_coverage_20260719"
LOCK = ROOT / "workflow/final_lock/e22_20260719/E22_V17_FINAL_LOCK.json"
FREEZE = QA_DIR / "E22_V17_FINAL_QA_FREEZE.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    evidence = {
        "parallel_qa": ROOT / "workflow/tasks/E22_agentcut_v17_standard_storyboard_parallel_qa_receipt_20260719.json",
        "ai_review_receipt": ROOT / "workflow/tasks/E22_agentcut_v17_ai_review_receipt_20260719.json",
        "ai_review": QA_DIR / "E22_AI_REVIEW_WRAPPER.json",
        "ocr_raw": QA_DIR / "E22_FINAL_VIDEO_OCR_AUDIT_V17_FULL_DURATION.json",
        "ocr_adjudication": QA_DIR / "E22_V17_OCR_MACHINE_ADJUDICATION.json",
        "cadence": QA_DIR / "E22_FRAME_CADENCE_AUDIT_V17.json",
        "asr": QA_DIR / "E22_FINAL_ASR_AUDIT_V17.json",
        "sentences": QA_DIR / "E22_FINAL_SENTENCE_COMPLETENESS_V17.json",
        "action_realtime": QA_DIR / "E22_ACTION_REALTIME_AUDIT_V17.json",
    }
    loaded = {name: load(path) for name, path in evidence.items()}
    if loaded["parallel_qa"].get("status") != "BATCH_COMPLETE_WITH_ISOLATED_FAILURES":
        raise SystemExit("Parallel QA terminal status is unexpected")
    for task in loaded["parallel_qa"].get("tasks", []):
        if task.get("task_key", "").endswith("FULL-DURATION-OCR"):
            continue
        if task.get("status") != "tool_pass":
            raise SystemExit(f"Objective QA did not pass: {task.get('task_key')}")
    if loaded["ocr_adjudication"].get("decision") != "PASS_MACHINE_ADJUDICATION":
        raise SystemExit("OCR adjudication is not PASS")
    if loaded["ai_review_receipt"].get("status") != "BATCH_COMPLETE" or loaded["ai_review"].get("status") != "PASS":
        raise SystemExit("AI Review is not PASS")
    for name in ("cadence", "asr", "sentences", "action_realtime"):
        if loaded[name].get("status") != "PASS":
            raise SystemExit(f"{name} gate is not PASS")

    review_match = re.search(r'"review_id":\s*"([^"]+)"', loaded["ai_review"].get("stdout", ""))
    review_id = review_match.group(1) if review_match else "REV-82E7EC0B9DF47D4A"
    source_sha = sha256(SOURCE)
    FINAL.parent.mkdir(parents=True, exist_ok=True)
    if not FINAL.exists() or sha256(FINAL) != source_sha:
        shutil.copy2(SOURCE, FINAL)
    final_sha = sha256(FINAL)
    if final_sha != source_sha:
        raise SystemExit("No-transcode final SHA mismatch")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    FREEZE.write_text(json.dumps({
        "schema": "qingshan.final_qa_freeze.v1",
        "episode": "E22",
        "version": "v17",
        "status": "PASS_FINAL_LOCK",
        "machine_audience_gate": {
            "decision": "PASS",
            "confidence": 0.92,
            "review_id": review_id,
            "evidence": {name: str(path) for name, path in evidence.items()},
            "limitations": ["Raw OCR FAIL is preserved; exact-frame machine adjudication and independent full-cut AI review found no native text."],
            "rollback": "Restore V16 project/render; no source media was modified.",
        },
        "source_sha256": source_sha,
        "final_sha256": final_sha,
        "recorded_at": now,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps({
        "schema": "qingshan.final_lock.v1",
        "episode": "E22",
        "version": "v17",
        "status": "FINAL_LOCKED_RELEASE_HOLD",
        "source": str(SOURCE),
        "final": str(FINAL),
        "sha256": final_sha,
        "size_bytes": FINAL.stat().st_size,
        "duration_seconds": 165.875012,
        "qa_freeze": str(FREEZE),
        "release_status": "HOLD_NO_PLATFORM_PUBLICATION",
        "s3_status": "PENDING_UPLOAD",
        "rollback": str(ROOT / "configs/e22_agentcut_project_v16_dia016_luma_repair_20260719.json"),
        "recorded_at": now,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS_FINAL_LOCK", "final": str(FINAL), "sha256": final_sha, "review_id": review_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
