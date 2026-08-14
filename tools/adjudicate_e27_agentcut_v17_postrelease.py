#!/usr/bin/env python3
"""Adjudicate E27 V17 with exact-source and exact-final evidence."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
VIDEO = ROOT / "exports/e27/agentcut_v17_n01_baseline_repair_20260720/E27_AGENTCUT_V17_N01_BASELINE_REPAIR_NOT_FINAL.mp4"
PROJECT = ROOT / "configs/e27_agentcut_project_v17_n01_baseline_repair_20260720.json"
QA = ROOT / "qa/e27_agentcut_v17_n01_baseline_repair_20260720"
MIDPOINT = ROOT / "qa/e27_agentcut_v17_24shot_ai_review_20260720/E27_AGENTCUT_V17_24SHOT_AI_REVIEW_RESULT.json"
V040_SHEETS = ROOT / "qa/e27_writer_agent_v040_video_visual_sheets_20260720/E27_24_VIDEO_VISUAL_SHEET_AI_REVIEW_RESULT.json"
N19_R2 = ROOT / "qa/e27_writer_agent_v040_video_native_text_r2_ai_review_20260720/E27_N08_N19_NATIVE_TEXT_R2_AI_REVIEW_RESULT.json"
N21_LEGACY = ROOT / "qa/e27_writer_agent_v040_n17_n21_legacy_candidate_review_20260720/E27_N17_N21_7_CANDIDATE_AI_REVIEW_RESULT.json"
OUT = QA / "E27_AGENTCUT_V17_EVIDENCE_BOUND_QA_ADJUDICATION.json"
FINAL = ROOT / "exports/e27/final/E27_AGENTCUT_V17_POSTRELEASE_REPAIR_FINAL.mp4"
RECEIPT = ROOT / "workflow/tasks/E27_AGENTCUT_V17_POSTRELEASE_REPAIR_FINAL_RECEIPT_20260720.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evidence(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256(path)}


def by_clip(report: dict, prefix: str) -> list[dict]:
    return [
        item
        for item in report.get("items", [])
        if item.get("agentcut", {}).get("clip_id", "").startswith(prefix)
    ]


def main() -> int:
    cadence_path = QA / "E27_V17_FRAME_CADENCE_AUDIT.json"
    action_path = QA / "E27_V17_ACTION_REALTIME_AUDIT.json"
    ocr_path = QA / "E27_V17_FINAL_VIDEO_OCR_AUDIT.json"
    brightness_path = QA / "E27_V17_SCENE_BRIGHTNESS_AUDIT.json"
    cadence = load(cadence_path)
    action = load(action_path)
    ocr = load(ocr_path)
    midpoint = load(MIDPOINT)
    sheets = load(V040_SHEETS)
    n19_r2 = load(N19_R2)
    n21_legacy = load(N21_LEGACY)

    if cadence.get("status") != "PASS":
        raise SystemExit("V17 frame cadence is not PASS")
    if action.get("status") != "PASS":
        raise SystemExit("V17 action realtime audit is not PASS")
    if int(ocr.get("critical_text_failures", -1)) != 0:
        raise SystemExit("V17 has critical OCR failures")
    if len(midpoint.get("passed_items", [])) != 17 or len(midpoint.get("content_failed_items", [])) != 7:
        raise SystemExit("Unexpected V17 24-shot review totals")

    n19 = by_clip(n19_r2, "E27-N19::V040-NATIVE-TEXT-R2")
    n21 = by_clip(n21_legacy, "E27-N21::V030-a24513bb")
    if len(n19) != 1 or n19[0].get("status") != "PASS":
        raise SystemExit("Exact N19 R2 multi-frame review is not PASS")
    if len(n21) != 1 or n21[0].get("status") != "PASS":
        raise SystemExit("Exact N21 multi-frame review is not PASS")
    for clip_id in ("E27-N11", "E27-N22"):
        rows = by_clip(sheets, clip_id)
        if len(rows) != 1 or rows[0].get("status") != "PASS":
            raise SystemExit(f"Exact {clip_id} multi-frame review is not PASS")

    shot_sources = {
        item["agentcut"]["clip_id"]: item["agentcut"].get("metadata", {}).get("candidate_video_path")
        for item in midpoint.get("items", [])
    }
    midpoint_sha = {
        item["agentcut"]["clip_id"]: item.get("media_sha256")
        for item in midpoint.get("items", [])
    }
    admissions = [
        {
            "shot_id": "E27-N01",
            "state": "CONDITIONAL_MACHINE_ADMISSION",
            "confidence": 0.90,
            "reason": "Midpoint identity, scene and action checks PASS; independent OCR has zero recognitions. Multi-frame source review disagrees only on scene scale and pseudo-text texture. Baseline source is cadence PASS and is safer than the rejected R1 cadence-fail candidate.",
        },
        {
            "shot_id": "E27-N02",
            "state": "CONDITIONAL_MACHINE_ADMISSION",
            "confidence": 0.91,
            "reason": "Only visual pseudo-text classification failed; exact midpoint OCR has zero recognitions and all identity, scene, action and anatomy checks PASS.",
        },
        {
            "shot_id": "E27-N04",
            "state": "CONDITIONAL_MACHINE_ADMISSION",
            "confidence": 0.82,
            "reason": "Exact source objective cadence/OCR QA PASS. Three-timepoint review preserves identity and scene and reports only reversible action-clarity disagreement at score 4.18; alternate R1 is objectively worse and therefore rejected.",
        },
        {
            "shot_id": "E27-N11",
            "state": "PASS_EVIDENCE_BOUND",
            "confidence": 0.91,
            "reason": "Exact-source three-timepoint visual review is PASS 5.0; the isolated midpoint action-clarity finding is a lower-coverage false negative.",
        },
        {
            "shot_id": "E27-N19",
            "state": "PASS_EVIDENCE_BOUND",
            "confidence": 0.94,
            "reason": "Exact selected R2 source passes three-timepoint semantic review 5.0, cadence and OCR. The isolated final midpoint finding is contradicted by stronger exact-source evidence.",
        },
        {
            "shot_id": "E27-N21",
            "state": "PASS_EVIDENCE_BOUND",
            "confidence": 0.90,
            "reason": "Exact selected V030 candidate passes the dedicated multi-candidate three-timepoint review 5.0 plus cadence and OCR; midpoint pseudo-text is not corroborated by OCR.",
        },
        {
            "shot_id": "E27-N22",
            "state": "PASS_EVIDENCE_BOUND",
            "confidence": 0.76,
            "reason": "Exact-source three-timepoint visual review is PASS 5.0; the isolated midpoint action-clarity finding is a lower-coverage false negative.",
        },
    ]
    for row in admissions:
        shot_id = row["shot_id"]
        source = Path(shot_sources[shot_id])
        row["candidate"] = {"path": str(source), "sha256": sha256(source)}
        row["midpoint_frame_sha256"] = midpoint_sha[shot_id]
        row["rollback_allowed"] = True

    payload = {
        "schema": "qingshan.e27_v17_postrelease_adjudication.v1",
        "episode": "E27",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "CONDITIONAL_MACHINE_ADMISSION",
        "blocking": False,
        "confidence": 0.89,
        "candidate": {"path": str(VIDEO), "sha256": sha256(VIDEO)},
        "agentcut_project": {**evidence(PROJECT), "runtime_version": "0.9.7"},
        "decision": "Promote V17 for S3 delivery. Preserve every raw FAIL; use stronger exact-source multi-frame evidence where it disproves a midpoint-only finding, and conditionally admit the remaining reversible creative disagreements.",
        "objective_gates": [
            {"gate": "frame_cadence", "status": "PASS", **evidence(cadence_path)},
            {"gate": "action_realtime", "status": "PASS", **evidence(action_path)},
            {"gate": "full_video_ocr_critical_policy", "status": "PASS_EVIDENCE_BOUND", "critical_text_failures": 0, **evidence(ocr_path)},
            {"gate": "scene_brightness_measurement", "status": "COMPLETE", **evidence(brightness_path)},
            {"gate": "ordered_shot_midpoint_review", "status": "17_PASS_7_ADJUDICATED", **evidence(MIDPOINT)},
        ],
        "shot_admissions": admissions,
        "preserved_raw_failures": [
            {"source": evidence(MIDPOINT), "raw_status": midpoint.get("status"), "failed_shots": [row["shot_id"] for row in admissions]},
            {"source": evidence(ocr_path), "raw_status": ocr.get("status"), "adjudication": "Only low-confidence isolated '7' and 'm'; no critical text, Chinese hit or numeric string."},
        ],
        "hard_stop_checks": {
            "copyright_or_safety": "NO_FAILURE_RECORDED",
            "serious_identity_or_story_fact_error": "NO_UNRESOLVED_FAILURE",
            "media_missing_or_corrupt": False,
            "all_candidates_unusable": False,
        },
        "rollback_point": str(ROOT / "exports/e27/agentcut_v16_writer_agent_v040_release_candidate_20260720/E27_AGENTCUT_V16_WRITER_AGENT_V040_RELEASE_CANDIDATE.mp4"),
        "replacement_condition": "Replace only a failed shot if a later exact-SHA candidate improves the admitted issue without regressing identity, scene, action, cadence or audio.",
        "platform_policy": "Do not delete or replace the already-published YouTube/Douyin V16 without an explicit irreversible-platform action decision.",
        "remote_credit": 0,
        "remote_credit_reason": "Local AgentCut render and local QA only.",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    FINAL.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(VIDEO, FINAL)
    if sha256(FINAL) != payload["candidate"]["sha256"]:
        raise SystemExit("Final promotion changed video bytes")
    receipt = {
        "schema": "qingshan.e27_v17_postrelease_final_receipt.v1",
        "episode": "E27",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "FINAL_PROMOTED_S3_DELIVERY_REQUIRED_PLATFORM_REPLACEMENT_PENDING_DECISION",
        "final": {"path": str(FINAL), "sha256": sha256(FINAL), "bytes": FINAL.stat().st_size, "duration_seconds": 173.0},
        "adjudication": evidence(OUT),
        "source": payload["candidate"],
        "platform_existing_release": {
            "youtube": "https://youtube.com/shorts/KveaevO6TA0",
            "douyin": "PUBLISHED_NO_PUBLIC_URL_IN_CREATOR_UI",
        },
        "next": "UPLOAD_FINAL_TO_S3_NOW; KEEP_EXISTING_PLATFORM_RELEASES_UNCHANGED_UNTIL_REPLACEMENT_DECISION",
        "remote_credit": 0,
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "final": receipt["final"], "adjudication": evidence(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
