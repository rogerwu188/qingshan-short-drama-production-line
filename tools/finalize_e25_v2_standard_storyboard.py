#!/usr/bin/env python3
"""Freeze the fully QA-passed E25 V2 render without transcoding."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "exports/e25/agentcut_v2_standard_storyboard_coverage_20260719/E25_AGENTCUT_V2_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL.mp4"
FINAL = ROOT / "exports/e25/final_package_v2_20260719/qingshan_E25_v2_final.mp4"
QA_DIR = ROOT / "qa/e25_agentcut_v2_standard_storyboard_coverage_20260719"
LOCK = ROOT / "workflow/final_lock/e25_20260719/E25_V2_FINAL_LOCK.json"
FREEZE = QA_DIR / "E25_V2_FINAL_QA_FREEZE.json"


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
        "parallel_qa": ROOT / "workflow/tasks/E25_AGENTCUT_V2_STANDARD_STORYBOARD_PARALLEL_QA_R1_RECEIPT_20260719.json",
        "ai_review": QA_DIR / "E25_AI_REVIEW_WRAPPER.json",
        "ocr": QA_DIR / "E25_FINAL_VIDEO_OCR_AUDIT_V2.json",
        "cadence": QA_DIR / "E25_FRAME_CADENCE_AUDIT_V2.json",
        "asr": QA_DIR / "E25_FINAL_ASR_AUDIT_V2.json",
        "sentences": QA_DIR / "E25_FINAL_SENTENCE_COMPLETENESS_V2.json",
        "action_realtime": QA_DIR / "E25_ACTION_REALTIME_AUDIT_V2.json",
    }
    loaded = {name: load(path) for name, path in evidence.items()}
    if loaded["parallel_qa"].get("status") != "BATCH_COMPLETE":
        raise SystemExit("Parallel QA is not complete")
    if loaded["ai_review"].get("status") != "PASS":
        raise SystemExit("AI Review is not PASS")
    for name in ("ocr", "cadence", "asr", "sentences", "action_realtime"):
        if loaded[name].get("status") != "PASS":
            raise SystemExit(f"{name} gate is not PASS")
    if loaded["ocr"].get("critical_text_failures") != 0:
        raise SystemExit("OCR critical failures are not zero")
    review_match = re.search(r'"review_id":\s*"([^"]+)"', loaded["ai_review"].get("stdout", ""))
    review_id = review_match.group(1) if review_match else "MISSING_REVIEW_ID"
    if review_id == "MISSING_REVIEW_ID":
        raise SystemExit("AI Review ID missing")
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
        "episode": "E25",
        "version": "v2",
        "status": "PASS_FINAL_LOCK",
        "machine_audience_gate": {
            "decision": "PASS",
            "confidence": 0.93,
            "review_id": review_id,
            "evidence": {name: str(path) for name, path in evidence.items()},
            "rollback": "Restore E25 V1 project/render; no source media was modified."
        },
        "source_sha256": source_sha,
        "final_sha256": final_sha,
        "recorded_at": now,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps({
        "schema": "qingshan.final_lock.v1",
        "episode": "E25",
        "version": "v2",
        "status": "FINAL_LOCKED_READY_FOR_ORDERED_RELEASE",
        "source": str(SOURCE),
        "final": str(FINAL),
        "sha256": final_sha,
        "size_bytes": FINAL.stat().st_size,
        "qa_freeze": str(FREEZE),
        "release_status": "READY_YOUTUBE_THEN_DOUYIN",
        "s3_status": "PENDING_UPLOAD",
        "rollback": str(ROOT / "configs/e25_agentcut_project_v1_full_dialogue_20260719.json"),
        "recorded_at": now,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS_FINAL_LOCK", "final": str(FINAL), "sha256": final_sha, "review_id": review_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
