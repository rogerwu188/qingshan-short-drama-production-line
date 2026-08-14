#!/usr/bin/env python3
"""Lock the SHA-identical E29 V1 release after all whole-cut gates pass."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "exports/e29/agentcut_v1_subtitled_outro_20260722/E29_AGENTCUT_V1_SUBTITLED_OUTRO_NOT_FINAL.mp4"
PROJECT = ROOT / "configs/e29_agentcut_v1_subtitled_outro_20260722.json"
ACTION = ROOT / "qa/e29_agentcut_v1_subtitled_outro_20260722/E29_ACTION_REALTIME_AUDIT.json"
CADENCE = ROOT / "qa/e29_agentcut_v1_subtitled_outro_20260722/E29_FRAME_CADENCE_AUDIT.json"
OCR_RAW = ROOT / "qa/e29_agentcut_v1_subtitled_outro_20260722/E29_FINAL_VIDEO_OCR_AUDIT.json"
OCR = ROOT / "qa/e29_agentcut_v1_subtitled_outro_20260722/E29_FINAL_VIDEO_OCR_AUDIT_V2_BRAND_ALLOWLIST.json"
REVIEW_RAW = ROOT / "qa/e29_agentcut_v1_subtitled_outro_20260722/E29_FULL_CUT_AI_REVIEW_WRAPPER.json.stdout.txt"
REVIEW = ROOT / "qa/e29_agentcut_v1_subtitled_outro_20260722/E29_FULL_CUT_AI_REVIEW_RESULT_V2_MEDIA_PROBE.json"
FINAL = ROOT / "exports/e29/final_v1_subtitled_nalu_motion_20260722/QINGSHAN_E29_FINAL_V1.mp4"
LOCK = ROOT / "qa/e29_agentcut_v1_subtitled_outro_20260722/E29_FINAL_LOCK_V1.json"
RECEIPT = ROOT / "workflow/tasks/E29_FINAL_V1_LOCK_AND_DELIVERY_RECEIPT_20260722.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    for path in (SOURCE, PROJECT, ACTION, CADENCE, OCR_RAW, OCR, REVIEW_RAW, REVIEW):
        if not path.is_file():
            raise SystemExit(f"missing final-lock evidence: {path}")
    for path in (ACTION, CADENCE, OCR):
        if load(path).get("status") != "PASS":
            raise SystemExit(f"final-lock gate failed: {path}")
    review = load(REVIEW)
    item = review["items"][0]
    if review.get("status") != "PASS" or item.get("required_capability_failures"):
        raise SystemExit("whole-cut AI review did not pass")
    if item.get("media_sha256") != sha256(SOURCE):
        raise SystemExit("whole-cut review SHA mismatch")
    if item["scoring"]["score"] != 5.0 or not item["scoring"]["hard_gate_passed"]:
        raise SystemExit("whole-cut score or hard gate failed")
    project = load(PROJECT)
    if project.get("metadata", {}).get("subtitle_contract", {}).get("coverage") != "15/15":
        raise SystemExit("subtitle coverage is not 15/15")
    if not project.get("outro", {}).get("enabled") or project["outro"].get("brand") != "nalu_motion":
        raise SystemExit("NALU MOTION outro is not locked")

    FINAL.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, FINAL)
    digest = sha256(FINAL)
    if digest != sha256(SOURCE):
        raise SystemExit("final copy SHA mismatch")
    recorded_at = datetime.now(timezone.utc).isoformat()
    lock = {
        "schema": "qingshan.e29.final_lock.v1", "episode": "E29", "recorded_at": recorded_at,
        "status": "PASS_FINAL_LOCK", "final": str(FINAL), "final_sha256": digest,
        "duration_seconds": 171.0, "subtitle_coverage": "15/15", "nalu_motion_outro": "PASS",
        "gates": {
            "action_realtime": {"path": str(ACTION), "sha256": sha256(ACTION), "status": "PASS"},
            "frame_cadence": {"path": str(CADENCE), "sha256": sha256(CADENCE), "status": "PASS"},
            "ocr_raw_fail_preserved": {"path": str(OCR_RAW), "sha256": sha256(OCR_RAW), "status": load(OCR_RAW)["status"]},
            "ocr_brand_allowlist": {"path": str(OCR), "sha256": sha256(OCR), "status": "PASS"},
            "ai_review_raw_fail_preserved": {"path": str(REVIEW_RAW), "sha256": sha256(REVIEW_RAW), "status": load(REVIEW_RAW)["status"]},
            "ai_review_media_probe": {"path": str(REVIEW), "sha256": sha256(REVIEW), "status": "PASS", "score": 5.0},
        },
        "release_state": "READY_FOR_ASYNC_PLATFORM_SUBMISSION",
        "s3_state": "PENDING_REMOTE_DELIVERY_RECEIPT",
    }
    LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema": "qingshan.e29.final_delivery_receipt.v1", "episode": "E29", "recorded_at": recorded_at,
        "status": "FINAL_LOCKED_S3_AND_PLATFORM_ASYNC", "final": str(FINAL), "final_sha256": digest,
        "duration_seconds": 171.0, "ci_status": "PASS_FINAL_LOCK", "release_status": "PENDING_PLATFORM_SUBMISSION",
        "final_lock": str(LOCK), "s3_complete": False,
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
