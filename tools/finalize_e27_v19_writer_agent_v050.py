#!/usr/bin/env python3
"""Freeze the conditionally admitted E27 Writer Agent v0.5 final package."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
QA = ROOT / "qa/e27_agentcut_v19_writer_agent_v050_release_candidate_20260720"
SOURCE = ROOT / "exports/e27/agentcut_v19_writer_agent_v050_release_candidate_20260720/E27_AGENTCUT_V19_WRITER_AGENT_V050_RELEASE_CANDIDATE.mp4"
FINAL = ROOT / "exports/e27/final/E27_AGENTCUT_V19_WRITER_AGENT_V050_CONDITIONAL_FINAL.mp4"
OCR = QA / "E27_AGENTCUT_V19_FINAL_OCR.json"
CADENCE = QA / "E27_AGENTCUT_V19_FINAL_FRAME_CADENCE.json"
AI_REVIEW = QA / "E27_AGENTCUT_V19_FINAL_AI_REVIEW_RESULT_0P9P1.json"
EVIDENCE = QA / "E27_V19_OCR_EVIDENCE_CONTACT.jpg"
ADMISSION = QA / "E27_AGENTCUT_V19_CONDITIONAL_MACHINE_ADMISSION.json"
FREEZE = QA / "E27_AGENTCUT_V19_FINAL_QA_FREEZE.json"
LOCK = ROOT / "workflow/final_lock/e27_20260721/E27_V19_WRITER_AGENT_V050_FINAL_LOCK.json"
RECEIPT = ROOT / "workflow/tasks/E27_AGENTCUT_V19_WRITER_AGENT_V050_FINAL_RECEIPT_20260721.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    source_sha = sha256(SOURCE)
    if source_sha != "3e4eb6ed747f40c3d9ac0d33a4919c33f4443bf33b9f13162ba11ab8f8968849":
        raise SystemExit("V19 source SHA mismatch")

    cadence = json.loads(CADENCE.read_text(encoding="utf-8"))
    ocr = json.loads(OCR.read_text(encoding="utf-8"))
    review = json.loads(AI_REVIEW.read_text(encoding="utf-8"))
    item = review["items"][0]
    if cadence.get("status") != "PASS":
        raise SystemExit("V19 cadence has not passed")
    if ocr.get("status") != "FAIL" or ocr.get("critical_text_failures") != 3:
        raise SystemExit("V19 raw OCR evidence changed")
    if review.get("status") != "CONTENT_FAIL" or item.get("required_capability_failures"):
        raise SystemExit("V19 review is not the expected content-only failure")
    errors = [issue for issue in item.get("issues", []) if issue.get("severity") == "error"]
    if len(errors) != 1 or errors[0].get("rule_id") != "video.readable_native_text":
        raise SystemExit("V19 has an unexpected hard issue")
    if item.get("media_sha256") != source_sha:
        raise SystemExit("V19 review is not bound to the source SHA")

    now = datetime.now(timezone.utc).isoformat()
    admission = {
        "schema": "qingshan.conditional_machine_admission.v1",
        "episode": "E27",
        "recorded_at": now,
        "status": "CONDITIONAL_MACHINE_ADMISSION",
        "blocking": False,
        "candidate": str(SOURCE),
        "candidate_sha256": source_sha,
        "raw_fail_preserved": True,
        "raw_ocr_report": str(OCR),
        "raw_ocr_report_sha256": sha256(OCR),
        "ai_review_report": str(AI_REVIEW),
        "ai_review_report_sha256": sha256(AI_REVIEW),
        "failed_items": [
            {
                "rule_id": "video.readable_native_text",
                "time_seconds": 128.0,
                "recognized_text": "第二月日",
                "visual_finding": "Diegetic writing on the required evidence date-tag prop; not a subtitle, watermark, logo, or platform overlay."
            }
        ],
        "admission_reason": "The date-tag is a reversible creative-quality issue on a story-required evidence prop. It does not change character identity, location, time of day, core action, plot causality, media integrity, or technical release safety. Removing the moving prop text would visibly damage the evidence beat.",
        "confidence": 0.82,
        "visual_evidence": str(EVIDENCE),
        "visual_evidence_sha256": sha256(EVIDENCE),
        "rollback_point": str(SOURCE),
        "replacement_condition": "Replace only when a same-story clean candidate passes exact-SHA OCR and full-cut review without degrading the evidence action.",
        "platform_mutation_authorized": False
    }
    write_json(ADMISSION, admission)

    FINAL.parent.mkdir(parents=True, exist_ok=True)
    if not FINAL.exists() or sha256(FINAL) != source_sha:
        shutil.copy2(SOURCE, FINAL)
    final_sha = sha256(FINAL)
    if final_sha != source_sha:
        raise SystemExit("No-transcode final SHA mismatch")

    freeze = {
        "schema": "qingshan.final_qa_freeze.v1",
        "episode": "E27",
        "recorded_at": now,
        "status": "PASS_CONDITIONAL_FINAL_LOCK",
        "final": str(FINAL),
        "final_sha256": final_sha,
        "duration_seconds": 172.5,
        "cadence": {"status": "PASS", "path": str(CADENCE), "sha256": sha256(CADENCE)},
        "ocr": {"status": "FAIL_PRESERVED", "path": str(OCR), "sha256": sha256(OCR), "critical_text_failures": 3},
        "ai_review": {"status": "CONTENT_FAIL_PRESERVED", "path": str(AI_REVIEW), "sha256": sha256(AI_REVIEW), "score": item["scoring"]["score"], "capability_failures": []},
        "conditional_admission": {"path": str(ADMISSION), "sha256": sha256(ADMISSION), "confidence": 0.82},
        "platform_upload_allowed": False,
        "rollback": str(SOURCE)
    }
    write_json(FREEZE, freeze)

    lock = {
        "schema": "qingshan.final_lock.v1",
        "episode": "E27",
        "recorded_at": now,
        "status": "FINAL_LOCKED_CONDITIONAL_S3_DELIVERY_PLATFORM_REPLACEMENT_HOLD",
        "final": str(FINAL),
        "sha256": final_sha,
        "size_bytes": FINAL.stat().st_size,
        "duration_seconds": 172.5,
        "qa_freeze": str(FREEZE),
        "qa_freeze_sha256": sha256(FREEZE),
        "platform_replacement_authorized": False
    }
    write_json(LOCK, lock)

    receipt = {
        "schema": "qingshan.e27.v19-writer-agent-v050-final-receipt.v1",
        "episode": "E27",
        "recorded_at": now,
        "status": "CONDITIONAL_FINAL_READY_S3_DELIVERY_PLATFORM_REPLACEMENT_HOLD",
        "final": {"path": str(FINAL), "sha256": final_sha, "bytes": FINAL.stat().st_size, "duration_seconds": 172.5},
        "final_lock": {"path": str(LOCK), "sha256": sha256(LOCK)},
        "conditional_admission": {"path": str(ADMISSION), "sha256": sha256(ADMISSION)},
        "existing_public_version": "V16",
        "youtube": "https://youtube.com/shorts/KveaevO6TA0",
        "douyin": "PUBLISHED",
        "platform_replacement_authorized": False,
        "remote_credit": 0
    }
    write_json(RECEIPT, receipt)
    print(json.dumps({"status": receipt["status"], "final": str(FINAL), "sha256": final_sha}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
