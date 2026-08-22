#!/usr/bin/env python3
"""Persist exact-SHA registered Q1 decisions for E40 canonical-gap wave 1."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from shot_media_admission_gate import evaluate


ROOT = Path(__file__).resolve().parents[1]
HARVEST = ROOT / "qa/e40_remake_20260822/canonical_gap_keyframes_wave1_v1/E40_CANONICAL_GAP_KEYFRAMES_WAVE1_HARVEST_V2.json"
REGISTRY = ROOT / "configs/GATE_REGISTRY_v3_20260716.json"
OUT = ROOT / "qa/e40_remake_20260822/canonical_gap_keyframes_wave1_v1/q1_registered"

FINDINGS = {
    "E40-13-1-S01-KEYFRAME-V1": {
        "CHARACTER-IDENTITY-ADMISSION": "PASS: Chenji's locked white robe, young male silhouette and tied hair are preserved in the authored back-view entry composition; Baili remains the locked veiled white-clad narrow silhouette. No conflicting face is exposed.",
        "SCENE-AUTHORITY-LOCK": "PASS: Wangfu hall entrance, threshold, candlelit inner hall, long gauze curtain and curtain-side standing zone retain the registered hall/subspace relation.",
        "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF": "PASS: Chenji is caught mid-threshold step, Baili remains still at curtain side, and the veiled seated figure is separated behind the curtain; this is an in-progress entry state rather than a settled tableau.",
        "PERIOD-ANACHRONISM-LOCK": "PASS: No modern object, text, logo, watermark, synthetic fixture or contemporary fastening is visible.",
    },
    "E40-13-1-S04-KEYFRAME-V1": {
        "CHARACTER-IDENTITY-ADMISSION": "PASS: the visible face, age, facial proportions, hair and white robe match the locked Chenji native-registry reference without character substitution.",
        "SCENE-AUTHORITY-LOCK": "PASS: the close shot remains inside the registered Wangfu hall lighting and curtain/column spatial family.",
        "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF": "FAIL: the frost has formed a completed crystalline ring around the finger instead of a single thin frost line halfway crawling onto the finger and about to recede; the required in-progress state is not available for video handoff.",
        "PERIOD-ANACHRONISM-LOCK": "PASS: No modern object, text, logo or watermark is visible.",
    },
    "E40-13-2-S02-KEYFRAME-V1": {
        "CHARACTER-IDENTITY-ADMISSION": "PASS: Chenji's visible face, hair, age and white robe match the locked native reference; Baili remains veiled and white-clad in the curtain-side depth plane.",
        "SCENE-AUTHORITY-LOCK": "PASS: the long table, curtain-side depth plane, candlelight and hall axis preserve the registered front-hall subspace.",
        "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF": "PASS: exactly four frost marks are visibly countable, no fifth mark exists, and Chenji's finger is suspended over the empty area rather than resting on a completed fifth position.",
        "PERIOD-ANACHRONISM-LOCK": "PASS: No modern object, text, logo or watermark is visible.",
    },
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def portable(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    harvest = json.loads(HARVEST.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    index = []
    for row in harvest["results"]:
        task_key = row["task_key"]
        asset = Path(row["output_path"])
        if sha(asset) != row["sha256"]:
            raise ValueError(f"{task_key} harvested asset SHA mismatch")
        findings = FINDINGS[task_key]
        unit_dir = OUT / task_key
        failed_gates = [gate_id for gate_id, finding in findings.items() if finding.startswith("FAIL:")]
        decision = "FAIL_NOT_ADMITTED" if failed_gates else "ADMITTED_FOR_VIDEO_SUBMIT"
        review = {
            "schema": "qingshan.registered_visual_evidence_bundle.v1",
            "episode": "E40",
            "task_key": task_key,
            "unit_id": task_key.removesuffix("-KEYFRAME-V1"),
            "reviewed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reviewer_type": "HUMAN_AND_AI",
            "reviewed_asset_path": portable(asset),
            "reviewed_asset_sha256": row["sha256"],
            "original_resolution_review": True,
            "registered_gate_findings": findings,
            "decision": decision,
            "automatic_retry_allowed": False,
            "paid_attempt_ordinal": 1,
        }
        review_path = unit_dir / "original_resolution_review.json"
        write_json(review_path, review)
        evidence = []
        for gate_id, finding in findings.items():
            failed = gate_id in failed_gates
            evidence.append({
                "gate_id": gate_id,
                "status": "FAIL_NOT_ADMITTED" if failed else "PASS_ORIGINAL_RESOLUTION",
                "reviewed_asset_sha256": row["sha256"],
                "evidence_path": portable(review_path),
                "evidence_sha256": sha(review_path),
                "original_resolution_review": True,
                "reviewer_type": "HUMAN_AND_AI",
                "defect_tier": "P1" if failed else None,
                "finding": finding,
            })
        request = {
            "schema": "qingshan.shot_media_admission_request.v2",
            "kind": "KEYFRAME_VIDEO_SUBMIT",
            "episode": "E40",
            "unit_id": task_key.removesuffix("-KEYFRAME-V1"),
            "task_key": task_key,
            "asset_path": portable(asset),
            "asset_sha256": row["sha256"],
            "evidence": evidence,
            "technical_qa": {"status": "TECHNICAL_PASS_CONTENT_REVIEWED"},
        }
        request_path = unit_dir / "admission_request.json"
        write_json(request_path, request)
        result = evaluate(request, registry, ROOT)
        result_path = unit_dir / "admission_result.json"
        write_json(result_path, result)
        expected = "FAIL_NOT_ADMITTED" if failed_gates else "ADMITTED_FOR_VIDEO_SUBMIT"
        if result.get("downstream_status") != expected:
            raise ValueError(f"{task_key}: expected {expected}, got {result.get('downstream_status')}")
        index.append({
            "task_key": task_key,
            "task_id": row["task_id"],
            "asset_path": portable(asset),
            "asset_sha256": row["sha256"],
            "downstream_status": result["downstream_status"],
            "admission_result": portable(result_path),
            "admission_result_sha256": sha(result_path),
        })
    admitted = [item for item in index if item["downstream_status"] == "ADMITTED_FOR_VIDEO_SUBMIT"]
    failed = [item for item in index if item["downstream_status"] == "FAIL_NOT_ADMITTED"]
    payload = {
        "schema": "qingshan.e40.canonical_gap_keyframes_wave1_q1_index.v1",
        "episode": "E40",
        "status": f"ADMITTED_{len(admitted)}_FAILED_{len(failed)}",
        "results": index,
        "video_submission_allowed_task_keys": [item["task_key"] for item in admitted],
        "failed_task_keys": [item["task_key"] for item in failed],
        "next_action": "Compile Seedance Fast video tasks only from admitted exact SHAs; isolate the failed frost-ring SHA.",
    }
    out = OUT / "E40_CANONICAL_GAP_KEYFRAMES_WAVE1_Q1_INDEX_V1.json"
    write_json(out, payload)
    print(json.dumps({"status": payload["status"], "index": portable(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
