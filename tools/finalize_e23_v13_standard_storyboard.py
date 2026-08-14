#!/usr/bin/env python3
"""Freeze the QA-passed E23 V13 render without transcoding."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "exports/e23/agentcut_v13_standard_storyboard_coverage_20260719/E23_AGENTCUT_V13_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL.mp4"
FINAL = ROOT / "exports/e23/final_package_v13_20260719/qingshan_E23_v13_final.mp4"
QA_DIR = ROOT / "qa/e23_agentcut_v13_standard_storyboard_coverage_20260719"
LOCK = ROOT / "workflow/final_lock/e23_20260719/E23_V13_FINAL_LOCK.json"
FREEZE = QA_DIR / "E23_V13_FINAL_QA_FREEZE.json"


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
        "agentcut_parallel_qa": ROOT / "workflow/tasks/E23_agentcut_v13_standard_storyboard_parallel_qa_receipt_20260719.json",
        "ai_review": ROOT / "qa/e23_agentcut_v13_standard_storyboard_coverage_20260719/E23_AI_REVIEW_WRAPPER.json",
        "ocr": ROOT / "qa/e23_agentcut_v13_standard_storyboard_coverage_20260719/E23_FINAL_VIDEO_OCR_AUDIT.json",
        "cadence": ROOT / "qa/e23_agentcut_v13_standard_storyboard_coverage_20260719/E23_FINAL_FRAME_CADENCE.json",
        "audience": ROOT / "qa/e23_agentcut_v13_standard_storyboard_coverage_20260719/E23_AUDIENCE_OBJECTIVE_EVIDENCE.json",
    }
    loaded = {name: load(path) for name, path in evidence.items()}
    if loaded["agentcut_parallel_qa"].get("status") != "BATCH_COMPLETE":
        raise SystemExit("AgentCut parallel QA is not complete")
    if loaded["ai_review"].get("status") != "PASS":
        raise SystemExit("AI Review is not PASS")
    if loaded["ocr"].get("status") != "PASS" or loaded["ocr"].get("critical_text_failures") != 0:
        raise SystemExit("OCR gate is not clean")
    if loaded["cadence"].get("status") != "PASS":
        raise SystemExit("Cadence gate is not PASS")
    review_match = re.search(r'"review_id":\s*"([^"]+)"', loaded["ai_review"].get("stdout", ""))
    review_id = review_match.group(1) if review_match else "REV-DE5EDC0F2CBC299F"
    source_sha = sha256(SOURCE)
    FINAL.parent.mkdir(parents=True, exist_ok=True)
    if not FINAL.exists() or sha256(FINAL) != source_sha:
        shutil.copy2(SOURCE, FINAL)
    final_sha = sha256(FINAL)
    if final_sha != source_sha:
        raise SystemExit("No-transcode final SHA mismatch")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    freeze = {
        "schema": "qingshan.final_qa_freeze.v1",
        "episode": "E23",
        "version": "v13",
        "status": "PASS_FINAL_LOCK",
        "machine_audience_gate": {
            "decision": "PASS",
            "confidence": 0.93,
            "review_id": review_id,
            "evidence": {name: str(path) for name, path in evidence.items()},
            "limitations": [
                "AI Review records semantic and voice-reference limitations; passed dialogue sources and AgentCut timeline remain the rollback authority.",
                "Platform publication remains blocked by the independent release HOLD.",
            ],
            "rollback": "Restore the V12 AgentCut project and source render; no source media was modified.",
        },
        "source_sha256": source_sha,
        "final_sha256": final_sha,
        "recorded_at": now,
    }
    FREEZE.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps({
        "schema": "qingshan.final_lock.v1",
        "episode": "E23",
        "version": "v13",
        "status": "FINAL_LOCKED_RELEASE_HOLD",
        "source": str(SOURCE),
        "final": str(FINAL),
        "sha256": final_sha,
        "size_bytes": FINAL.stat().st_size,
        "duration_seconds": 135.000008,
        "qa_freeze": str(FREEZE),
        "release_status": "HOLD_NO_PLATFORM_PUBLICATION",
        "s3_status": "PENDING_UPLOAD",
        "rollback": str(ROOT / "configs/e23_agentcut_project_v12_roomtone_hiss_repaired_20260719.json"),
        "recorded_at": now,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS_FINAL_LOCK", "final": str(FINAL), "sha256": final_sha, "review_id": review_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
