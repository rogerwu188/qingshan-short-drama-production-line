#!/usr/bin/env python3
"""Freeze E27 V20 as the best reversible candidate without platform mutation."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
QA = ROOT / "qa/e27_agentcut_v20_writer_agent_v050_failed_only_repairs_20260721"
IDENTITY_QA = ROOT / "qa/e27_agentcut_v20_identity_gate_20260721"
SOURCE = ROOT / "exports/e27/agentcut_v20_writer_agent_v050_failed_only_repairs_20260721/E27_AGENTCUT_V20_WRITER_AGENT_V050_FAILED_ONLY_REPAIRS_CANDIDATE.mp4"
FINAL = ROOT / "exports/e27/final/E27_AGENTCUT_V20_WRITER_AGENT_V050_FAILED_ONLY_REPAIRS_CONDITIONAL_FINAL.mp4"
PROJECT = ROOT / "configs/e27_agentcut_v20_writer_agent_v050_failed_only_repairs_20260721.json"
OCR = QA / "E27_AGENTCUT_V20_FINAL_OCR.json"
CADENCE = QA / "E27_AGENTCUT_V20_FINAL_FRAME_CADENCE.json"
AI_REVIEW = QA / "E27_AGENTCUT_V20_FINAL_AI_REVIEW_RESULT_0P9P1_R2.json"
IDENTITY_CONTACT = IDENTITY_QA / "E27_V20_JIAOTU_TEXT_CONTACT.jpg"
IDENTITY_MANIFEST = IDENTITY_QA / "E27_V20_JIAOTU_IDENTITY_ADMISSION_MANIFEST.json"
IDENTITY_RESULT = IDENTITY_QA / "E27_V20_JIAOTU_IDENTITY_ADMISSION_RESULT.json"
ADMISSION = QA / "E27_AGENTCUT_V20_CONDITIONAL_MACHINE_ADMISSION.json"
FREEZE = QA / "E27_AGENTCUT_V20_FINAL_QA_FREEZE.json"
LOCK = ROOT / "workflow/final_lock/e27_20260721/E27_V20_WRITER_AGENT_V050_FINAL_LOCK.json"
RECEIPT = ROOT / "workflow/tasks/E27_AGENTCUT_V20_WRITER_AGENT_V050_FINAL_RECEIPT_20260721.json"


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
    expected_sha = "7259797009bb6ab87c288a7f2894b34eb48c89d34432677e5f9dd680d179ea9c"
    source_sha = sha256(SOURCE)
    if source_sha != expected_sha:
        raise SystemExit("V20 source SHA mismatch")
    if sha256(PROJECT) != "683bfa2f82ae352871e1dde1d165c2e7126a84eb229b6c4250ab147cc790d1f4":
        raise SystemExit("V20 project SHA mismatch")

    cadence = json.loads(CADENCE.read_text(encoding="utf-8"))
    ocr = json.loads(OCR.read_text(encoding="utf-8"))
    review = json.loads(AI_REVIEW.read_text(encoding="utf-8"))
    item = review["items"][0]
    if cadence.get("status") != "PASS":
        raise SystemExit("V20 cadence has not passed")
    if ocr.get("status") != "FAIL":
        raise SystemExit("V20 raw OCR report is not preserved")
    if review.get("status") != "PASS" or item.get("required_capability_failures"):
        raise SystemExit("V20 AI review has not passed")
    if item.get("media_sha256") != source_sha or float(item["scoring"]["score"]) != 5.0:
        raise SystemExit("V20 AI review provenance or score mismatch")

    now = datetime.now(timezone.utc).isoformat()
    frames = {path.name: sha256(path) for path in sorted((IDENTITY_QA / "frames").glob("t_*.jpg"))}
    identity_manifest = {
        "schema": "qingshan.character_identity_admission_manifest.v1",
        "episode": "E27",
        "recorded_at": now,
        "candidate": str(SOURCE),
        "candidate_sha256": source_sha,
        "registry": str(ROOT / "configs/series_character_asset_registry_20260712.json"),
        "sources": [{
            "source_id": "E27-V20-FULLCUT-JIAOTU-CROSS-SOURCE",
            "characters": [{
                "character_id": "CHAR-皎兔-古装",
                "history_status": "RETURNING",
                "reroll_round": 2,
                "identity_qa_rerun": True,
                "sample_frame_paths": [str(IDENTITY_QA / "frames" / name) for name in frames],
                "canonical_reference_paths": [str(ROOT / "ref_images/female_jiaotu_ref_20260703.jpg")],
                "manual_identity_review_status": "FAIL",
                "cross_source_consistency_status": "FAIL",
                "identity_adjacent_styling_warning": True,
                "motif_fidelity_status": "PARTIAL_PASS",
                "finding": "B02 failed-only R1 removes the oversized literal rabbit ears, but the older 105-second source still presents Jiaotu in a dark outfit inconsistent with the locked pale-robed identity. The candidate is technically usable and reversible, but identity is not a clean platform-replacement pass.",
                "forbidden_motifs_detected": [],
                "residual_failures": ["cross-source costume and face presentation mismatch at 105 seconds"]
            }]
        }],
        "visual_evidence": {
            "contact_sheet": str(IDENTITY_CONTACT),
            "contact_sheet_sha256": sha256(IDENTITY_CONTACT),
            "canonical_reference_sha256": sha256(ROOT / "ref_images/female_jiaotu_ref_20260703.jpg"),
            "sample_frame_sha256": frames
        }
    }
    write_json(IDENTITY_MANIFEST, identity_manifest)
    identity_result = {
        "schema": "qingshan.character_identity_admission_gate.v1",
        "status": "FAIL_PRESERVED_CONDITIONAL_DOWNSTREAM_ALLOWED",
        "source_count": 1,
        "failures": [
            "manual_identity_review_not_pass:E27-V20-FULLCUT-JIAOTU-CROSS-SOURCE:CHAR-皎兔-古装",
            "cross_source_identity_not_pass:E27-V20-FULLCUT-JIAOTU-CROSS-SOURCE:CHAR-皎兔-古装"
        ],
        "blocking": False,
        "platform_replacement_allowed": False
    }
    write_json(IDENTITY_RESULT, identity_result)

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
        "ai_review_status": "PASS",
        "ai_review_score": 5.0,
        "identity_gate": str(IDENTITY_RESULT),
        "identity_gate_sha256": sha256(IDENTITY_RESULT),
        "failed_items": [{
            "rule_id": "character.cross_source_identity_consistency",
            "time_seconds": 105.0,
            "visual_finding": "Jiaotu remains female and technically usable, but the old source changes from the locked pale robe to a dark costume and inconsistent face presentation."
        }],
        "admission_reason": "After targeted B02 and B05 repair, V20 is the strongest available reversible candidate: cadence passes, exact-SHA review passes at 5.0, and no readable main-content text survives normalized review. The remaining cross-source Jiaotu styling mismatch is preserved as a creative identity FAIL and does not stop S3 delivery under the failed-material admission rule.",
        "confidence": 0.90,
        "visual_evidence": str(IDENTITY_CONTACT),
        "visual_evidence_sha256": sha256(IDENTITY_CONTACT),
        "rollback_point": str(SOURCE),
        "replacement_condition": "Replace the 105-second source only when a same-story candidate matches the locked Jiaotu face and pale robe, then rerun exact-SHA identity and full-cut QA.",
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
        "ocr": {"status": "RAW_FAIL_PRESERVED_NORMALIZED_NO_BLOCKING_HITS", "path": str(OCR), "sha256": sha256(OCR), "critical_text_failures": ocr.get("critical_text_failures")},
        "ai_review": {"status": "PASS", "path": str(AI_REVIEW), "sha256": sha256(AI_REVIEW), "score": 5.0, "capability_failures": []},
        "identity": {"status": "FAIL_PRESERVED", "path": str(IDENTITY_RESULT), "sha256": sha256(IDENTITY_RESULT)},
        "conditional_admission": {"path": str(ADMISSION), "sha256": sha256(ADMISSION), "confidence": 0.90},
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
        "schema": "qingshan.e27.v20-writer-agent-v050-final-receipt.v1",
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
        "remote_credit": 0,
        "s3_status": "PENDING_UPLOAD"
    }
    write_json(RECEIPT, receipt)
    print(json.dumps({"status": receipt["status"], "final": str(FINAL), "sha256": final_sha}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
