#!/usr/bin/env python3
"""Freeze the fully QA-passed E26 V6 render without transcoding."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "exports/e26/agentcut_v6_human_gate_source_repair_20260720/E26_AGENTCUT_V6_HUMAN_GATE_SOURCE_REPAIR_NOT_FINAL.mp4"
FINAL = ROOT / "exports/e26/final_package_v6_20260720/qingshan_E26_v6_final.mp4"
QA_DIR = ROOT / "qa/e26_agentcut_v6_human_gate_source_repair_20260720"
LOCK = ROOT / "workflow/final_lock/e26_20260720/E26_V6_FINAL_LOCK.json"
FREEZE = QA_DIR / "E26_V6_FINAL_QA_FREEZE.json"


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
        "regression_ci": QA_DIR / "E26_FINAL_REGRESSION_CI.json",
        "human_viewing": QA_DIR / "E26_MACHINE_HUMAN_VIEWING_GATE.json",
        "ocr": QA_DIR / "E26_FINAL_VIDEO_OCR_NORMALIZED_DECISION.json",
        "cadence": QA_DIR / "E26_FRAME_CADENCE_AUDIT.json",
        "asr": QA_DIR / "E26_FINAL_ASR_AUDIT.json",
        "sentences": QA_DIR / "E26_FINAL_SENTENCE_COMPLETENESS.json",
        "action_realtime": QA_DIR / "E26_ACTION_REALTIME_AUDIT.json",
        "brightness": QA_DIR / "E26_SCENE_BRIGHTNESS_AUDIT.json",
    }
    loaded = {name: load(path) for name, path in evidence.items()}
    for name, report in loaded.items():
        if name == "brightness":
            continue
        if report.get("status") != "PASS":
            raise SystemExit(f"{name} gate is not PASS")
    if loaded["regression_ci"].get("failures"):
        raise SystemExit("regression CI still has failures")
    if loaded["regression_ci"].get("scene_brightness", {}).get("status") != "PASS":
        raise SystemExit("regression CI scene brightness gate is not PASS")
    if loaded["ocr"].get("critical_text_failures") != 0:
        raise SystemExit("OCR critical failures are not zero")
    source_sha = sha256(SOURCE)
    if loaded["human_viewing"].get("source_sha256") != source_sha:
        raise SystemExit("human viewing evidence is not bound to the source SHA")
    FINAL.parent.mkdir(parents=True, exist_ok=True)
    if not FINAL.exists() or sha256(FINAL) != source_sha:
        shutil.copy2(SOURCE, FINAL)
    final_sha = sha256(FINAL)
    if final_sha != source_sha:
        raise SystemExit("no-transcode final SHA mismatch")
    recorded_at = datetime.now().astimezone().isoformat(timespec="seconds")
    FREEZE.write_text(json.dumps({
        "schema": "qingshan.final_qa_freeze.v1",
        "episode": "E26",
        "version": "v6",
        "status": "PASS_FINAL_LOCK",
        "machine_audience_gate": {
            "decision": "PASS",
            "confidence": loaded["human_viewing"].get("confidence"),
            "review_mode": loaded["human_viewing"].get("review_mode"),
            "evidence": {name: str(path) for name, path in evidence.items()},
            "rollback": loaded["human_viewing"].get("rollback"),
        },
        "source_sha256": source_sha,
        "final_sha256": final_sha,
        "recorded_at": recorded_at,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps({
        "schema": "qingshan.final_lock.v1",
        "episode": "E26",
        "version": "v6",
        "status": "FINAL_LOCKED_READY_FOR_ORDERED_RELEASE",
        "source": str(SOURCE),
        "final": str(FINAL),
        "sha256": final_sha,
        "size_bytes": FINAL.stat().st_size,
        "duration_seconds": loaded["regression_ci"].get("runtime_seconds"),
        "qa_freeze": str(FREEZE),
        "release_status": "READY_YOUTUBE_THEN_DOUYIN",
        "s3_status": "PENDING_UPLOAD",
        "rollback": "Restore E26 V5 and its final-lock evidence; source media was not modified.",
        "recorded_at": recorded_at,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS_FINAL_LOCK", "final": str(FINAL), "sha256": final_sha}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
