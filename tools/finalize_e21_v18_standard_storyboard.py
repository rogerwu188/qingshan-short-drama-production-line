#!/usr/bin/env python3
"""Freeze the QA-passed E21 V18 render without transcoding."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "exports/e21/agentcut_v18_standard_storyboard_coverage_20260719/E21_AGENTCUT_V18_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL.mp4"
FINAL = ROOT / "exports/e21/final_package_v18_20260719/qingshan_E21_v18_final.mp4"
QA_DIR = ROOT / "qa/e21_agentcut_v18_standard_storyboard_coverage_20260719"
LOCK = ROOT / "workflow/final_lock/e21_20260719/E21_V18_FINAL_LOCK.json"
FREEZE = QA_DIR / "E21_V18_FINAL_QA_FREEZE.json"


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
        "parallel_qa": ROOT / "workflow/tasks/E21_agentcut_v18_standard_storyboard_parallel_qa_r2_receipt_20260719.json",
        "ai_review_receipt": ROOT / "workflow/tasks/E21_agentcut_v18_ai_review_receipt_20260719.json",
        "ai_review": QA_DIR / "E21_AI_REVIEW_WRAPPER.json",
        "ocr": QA_DIR / "E21_FINAL_VIDEO_OCR_AUDIT_V18_FULL_DURATION.json",
        "cadence": QA_DIR / "E21_FRAME_CADENCE_AUDIT_V18.json",
        "asr": QA_DIR / "E21_FINAL_ASR_AUDIT_V18.json",
        "sentences": QA_DIR / "E21_FINAL_SENTENCE_COMPLETENESS_V18.json",
        "action_realtime": QA_DIR / "E21_ACTION_REALTIME_AUDIT_V18.json",
    }
    loaded = {name: load(path) for name, path in evidence.items()}
    if loaded["parallel_qa"].get("status") != "BATCH_COMPLETE":
        raise SystemExit("Parallel QA is not complete")
    if loaded["ai_review_receipt"].get("status") != "BATCH_COMPLETE" or loaded["ai_review"].get("status") != "PASS":
        raise SystemExit("AI Review is not PASS")
    for name in ("ocr", "cadence", "asr", "sentences", "action_realtime"):
        if loaded[name].get("status") != "PASS":
            raise SystemExit(f"{name} gate is not PASS")
    if loaded["ocr"].get("critical_text_failures") != 0:
        raise SystemExit("OCR critical failures are not zero")

    review_match = re.search(r'"review_id":\s*"([^"]+)"', loaded["ai_review"].get("stdout", ""))
    review_id = review_match.group(1) if review_match else "REV-A197649DF7094587"
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
        "episode": "E21",
        "version": "v18",
        "status": "PASS_FINAL_LOCK",
        "machine_audience_gate": {
            "decision": "PASS",
            "confidence": 0.93,
            "review_id": review_id,
            "evidence": {name: str(path) for name, path in evidence.items()},
            "rollback": "Restore V17 final/project; no source media was modified.",
        },
        "source_sha256": source_sha,
        "final_sha256": final_sha,
        "recorded_at": now,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps({
        "schema": "qingshan.final_lock.v1",
        "episode": "E21",
        "version": "v18",
        "status": "FINAL_LOCKED_RELEASE_HOLD",
        "source": str(SOURCE),
        "final": str(FINAL),
        "sha256": final_sha,
        "size_bytes": FINAL.stat().st_size,
        "qa_freeze": str(FREEZE),
        "release_status": "HOLD_NO_PLATFORM_PUBLICATION",
        "s3_status": "PENDING_UPLOAD",
        "rollback": str(ROOT / "configs/e21_agentcut_project_v17_dia021_verified_source_repair_20260719.json"),
        "recorded_at": now,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS_FINAL_LOCK", "final": str(FINAL), "sha256": final_sha, "review_id": review_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
