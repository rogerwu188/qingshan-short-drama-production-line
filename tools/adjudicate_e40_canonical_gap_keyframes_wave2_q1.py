#!/usr/bin/env python3
"""Persist exact-SHA registered Q1 decisions for E40 gap keyframe wave two."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from shot_media_admission_gate import evaluate


ROOT = Path(__file__).resolve().parents[1]
HARVEST = ROOT / "qa/e40_remake_20260822/canonical_gap_keyframes_wave2_v1/E40_CANONICAL_GAP_KEYFRAMES_WAVE2_HARVEST_V2.json"
REGISTRY = ROOT / "configs/GATE_REGISTRY_v3_20260716.json"
OUT = ROOT / "qa/e40_remake_20260822/canonical_gap_keyframes_wave2_v1/q1_registered"
FINDINGS = {
    "E40-13-2-S03-KEYFRAME-V1": {
        "CHARACTER-IDENTITY-ADMISSION": "FAIL P0: the generated face is a newly synthesized identity and does not preserve the exact Chenji native-registry facial identity carried by the task. A reference attachment is not output identity verification.",
        "SCENE-AUTHORITY-LOCK": "PASS: Chenji remains outside the long gauze curtain while the fan-holder remains behind it; table, candle and curtain depth preserve the registered Wangfu hall axis.",
        "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF": "PASS: Chenji's lifted gaze and the still-open fan provide an executable pre-closure state; the fan can close in one visible beat without spatial reset. The wider opening than the preferred one-finger gap is P2 framing variation, not a registered canonical-state contradiction.",
        "PERIOD-ANACHRONISM-LOCK": "PASS: No modern object, text, logo, watermark or contemporary fastening is visible.",
    },
    "E40-13-2-S04-KEYFRAME-V1": {
        "CHARACTER-IDENTITY-ADMISSION": "FAIL P0: the generated face is a newly synthesized identity and does not preserve the exact Chenji native-registry facial identity carried by the task. A reference attachment is not output identity verification.",
        "SCENE-AUTHORITY-LOCK": "PASS: the long table, gauze depth plane, candlelight and background figure retain the registered front-hall arrangement.",
        "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF": "FAIL P0: the locked prompt required only Chenji's two fingers and grey sleeve with no visible face; the output instead introduces his full upper body, visible face and an additional background figure, changing the canonical framing and entity state.",
        "PERIOD-ANACHRONISM-LOCK": "PASS: No modern object, text, logo or watermark is visible.",
    },
}

FAIL_GATES = {
    "E40-13-2-S03-KEYFRAME-V1": {"CHARACTER-IDENTITY-ADMISSION"},
    "E40-13-2-S04-KEYFRAME-V1": {
        "CHARACTER-IDENTITY-ADMISSION",
        "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
    },
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def portable(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    harvest = json.loads(HARVEST.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    index = []
    for row in harvest["results"]:
        key = row["task_key"]
        asset = Path(row["output_path"])
        if sha(asset) != row["sha256"]:
            raise ValueError(f"{key} asset SHA mismatch")
        findings = FINDINGS[key]
        unit_dir = OUT / key
        review = {
            "schema": "qingshan.registered_visual_evidence_bundle.v1",
            "episode": "E40",
            "task_key": key,
            "unit_id": key.removesuffix("-KEYFRAME-V1"),
            "reviewed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reviewer_type": "HUMAN_AND_AI",
            "reviewed_asset_path": portable(asset),
            "reviewed_asset_sha256": row["sha256"],
            "original_resolution_review": True,
            "registered_gate_findings": findings,
            "decision": "FAIL_NOT_ADMITTED",
            "automatic_retry_allowed": False,
            "paid_attempt_ordinal": 1,
            "failure_attribution": "MISSING_REFERENCE_ANCHOR",
            "failure_attribution_detail": "Native bytes were attached, but the provider transport discarded role/identity authority and reduced the anchor to a soft flat reference.",
            "required_remedy": "Do not submit video. Rebuild through an identity-authoritative transport/compositing strategy, then run output-vs-native identity verification on the exact output SHA.",
        }
        review_path = unit_dir / "original_resolution_review.json"
        write(review_path, review)
        evidence = [{
            "gate_id": gate_id,
            "status": "FAIL_ORIGINAL_RESOLUTION" if gate_id in FAIL_GATES[key] else "PASS_ORIGINAL_RESOLUTION",
            "reviewed_asset_sha256": row["sha256"],
            "evidence_path": portable(review_path),
            "evidence_sha256": sha(review_path),
            "original_resolution_review": True,
            "reviewer_type": "HUMAN_AND_AI",
            "defect_tier": "P0" if gate_id in FAIL_GATES[key] else None,
            "finding": finding,
        } for gate_id, finding in findings.items()]
        request = {
            "schema": "qingshan.shot_media_admission_request.v2",
            "kind": "KEYFRAME_VIDEO_SUBMIT",
            "episode": "E40",
            "unit_id": key.removesuffix("-KEYFRAME-V1"),
            "task_key": key,
            "asset_path": portable(asset),
            "asset_sha256": row["sha256"],
            "evidence": evidence,
            "technical_qa": {"status": "TECHNICAL_PASS_CONTENT_REVIEWED"},
        }
        request_path = unit_dir / "admission_request.json"
        write(request_path, request)
        result = evaluate(request, registry, ROOT)
        if result.get("downstream_status") != "FAIL_NOT_ADMITTED":
            raise ValueError(f"{key}: expected FAIL_NOT_ADMITTED, got {result.get('downstream_status')}")
        result_path = unit_dir / "admission_result.json"
        write(result_path, result)
        index.append({
            "task_key": key,
            "task_id": row["task_id"],
            "asset_path": portable(asset),
            "asset_sha256": row["sha256"],
            "downstream_status": result["downstream_status"],
            "admission_result": portable(result_path),
            "admission_result_sha256": sha(result_path),
        })
    admitted = sum(row["downstream_status"] == "ADMITTED_FOR_VIDEO_SUBMIT" for row in index)
    failed = len(index) - admitted
    payload = {
        "schema": "qingshan.e40.canonical_gap_keyframes_wave2_q1_index.v1",
        "episode": "E40",
        "status": "ADMITTED_0_FAILED_2",
        "admitted_count": admitted,
        "failed_count": failed,
        "results": index,
        "video_submission_allowed_task_keys": [row["task_key"] for row in index if row["downstream_status"] == "ADMITTED_FOR_VIDEO_SUBMIT"],
        "next_action": "No video submit. Correct the identity-reference transport/compositing route before any paid retry; do not treat attached input references as output identity admission.",
    }
    out = OUT / "E40_CANONICAL_GAP_KEYFRAMES_WAVE2_Q1_INDEX_V1.json"
    write(out, payload)
    print(json.dumps({"status": payload["status"], "admitted": admitted, "failed": failed, "index": portable(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
