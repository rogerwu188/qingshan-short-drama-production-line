#!/usr/bin/env python3
"""Aggregate exact-SHA keyframe/video content evidence into honest admissions.

This is not a new quality gate.  It is a fail-closed aggregator for already
registered gates so advisory reports and technical decode checks cannot be
misrepresented as content admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "configs/GATE_REGISTRY_v3_20260716.json"
KEYFRAME_REQUIRED_GATES = (
    "CHARACTER-IDENTITY-ADMISSION",
    "SCENE-AUTHORITY-LOCK",
    "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
    "PERIOD-ANACHRONISM-LOCK",
)
VIDEO_REQUIRED_GATES = (*KEYFRAME_REQUIRED_GATES, "DEFECT-TIER-TOLERANCE")
ADVISORY_STATUSES = {"ADVISORY", "ADVISORY_NOT_A_GATE", "DIAGNOSTIC", "WARNING"}
PASS_STATUSES = {"PASS", "PASS_EXACT_SHA", "PASS_ORIGINAL_RESOLUTION"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(value: Any, root: Path) -> Path:
    path = Path(str(value or ""))
    return path if path.is_absolute() else root / path


def _registered_gate_ids(registry: dict[str, Any]) -> set[str]:
    return {str(row.get("gate_id")) for row in registry.get("gates") or [] if row.get("gate_id")}


def evaluate(
    admission: dict[str, Any], registry: dict[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    kind = str(admission.get("kind") or "").upper()
    failures: list[str] = []
    diagnostics: list[str] = []
    if kind not in {"KEYFRAME_VIDEO_SUBMIT", "VIDEO_ASSEMBLY"}:
        failures.append("admission_kind_invalid")
    required = KEYFRAME_REQUIRED_GATES if kind == "KEYFRAME_VIDEO_SUBMIT" else VIDEO_REQUIRED_GATES

    asset_path = _resolve(admission.get("asset_path"), root)
    declared_asset_sha = str(admission.get("asset_sha256") or "")
    actual_asset_sha = sha256_file(asset_path) if asset_path.is_file() else ""
    if not asset_path.is_file():
        failures.append(f"asset_missing:{asset_path}")
    elif not declared_asset_sha or declared_asset_sha != actual_asset_sha:
        failures.append("asset_sha256_mismatch")

    registered = _registered_gate_ids(registry)
    passing: set[str] = set()
    original_resolution_review = False
    evidence_rows = admission.get("evidence")
    if not isinstance(evidence_rows, list):
        evidence_rows = []
        failures.append("evidence_missing")
    for index, row in enumerate(evidence_rows, 1):
        gate_id = str(row.get("gate_id") or "")
        status = str(row.get("status") or "").upper()
        prefix = f"evidence_{index}:{gate_id or 'UNKNOWN'}"
        if gate_id not in registered:
            diagnostics.append(f"{prefix}:unregistered_gate_downgraded_to_diagnostic")
            continue
        if status in ADVISORY_STATUSES or row.get("advisory_only") is True:
            diagnostics.append(f"{prefix}:advisory_not_admission")
            continue
        reviewed_sha = str(row.get("reviewed_asset_sha256") or "")
        if reviewed_sha != declared_asset_sha:
            failures.append(f"{prefix}:reviewed_asset_sha256_mismatch")
            continue
        evidence_path = _resolve(row.get("evidence_path"), root)
        if not evidence_path.is_file():
            failures.append(f"{prefix}:evidence_file_missing")
            continue
        evidence_sha = str(row.get("evidence_sha256") or "")
        if not evidence_sha or evidence_sha != sha256_file(evidence_path):
            failures.append(f"{prefix}:evidence_sha256_mismatch")
            continue
        try:
            evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            failures.append(f"{prefix}:evidence_json_unreadable")
            continue
        declared_gate = str(evidence_payload.get("gate_id") or evidence_payload.get("registered_gate_id") or "")
        if declared_gate and declared_gate != gate_id:
            failures.append(f"{prefix}:evidence_gate_id_mismatch")
            continue
        declared_status = str(evidence_payload.get("status") or "").upper()
        if declared_status and declared_status not in PASS_STATUSES and status in PASS_STATUSES:
            failures.append(f"{prefix}:evidence_payload_not_pass:{declared_status}")
            continue
        if status in PASS_STATUSES:
            passing.add(gate_id)
        else:
            defect_tier = str(row.get("defect_tier") or "UNCLASSIFIED").upper()
            failures.append(f"{prefix}:registered_gate_not_pass:{status}:{defect_tier}")
        if row.get("original_resolution_review") is True and str(row.get("reviewer_type") or "").upper() in {
            "HUMAN", "AI_VISUAL", "HUMAN_AND_AI"
        }:
            original_resolution_review = True

    for gate_id in required:
        if gate_id not in passing:
            failures.append(f"required_registered_gate_not_pass:{gate_id}")
    if not original_resolution_review:
        failures.append("original_resolution_content_review_missing")

    technical = admission.get("technical_qa") or {}
    if kind == "VIDEO_ASSEMBLY":
        if technical.get("status") != "TECHNICAL_PASS_CONTENT_UNREVIEWED":
            failures.append("technical_qa_status_missing_or_dishonest")
        if str(technical.get("reviewed_asset_sha256") or "") != declared_asset_sha:
            failures.append("technical_qa_asset_sha256_mismatch")
    elif technical.get("status") in {"PASS", "QA_PASS", "ADMITTED_FOR_ASSEMBLY"}:
        failures.append("keyframe_technical_status_misrepresented_as_content_admission")

    admitted_status = (
        "ADMITTED_FOR_VIDEO_SUBMIT" if kind == "KEYFRAME_VIDEO_SUBMIT"
        else "ADMITTED_FOR_ASSEMBLY"
    )
    return {
        "schema": "qingshan.shot_media_admission.v1",
        "kind": kind,
        "asset_path": str(asset_path),
        "asset_sha256": declared_asset_sha,
        "status": admitted_status if not failures else "FAIL_NOT_ADMITTED",
        "required_registered_gates": list(required),
        "passing_registered_gates": sorted(passing),
        "original_resolution_content_review": original_resolution_review,
        "failures": failures,
        "diagnostics": diagnostics,
        "policy": {
            "technical_pass_is_not_content_pass": True,
            "advisory_is_not_admission": True,
            "unregistered_criteria_are_diagnostic_only": True,
            "exact_asset_sha_binding_required": True,
        },
    }


def evaluate_path(path: str | Path, root: Path = ROOT) -> dict[str, Any]:
    source = _resolve(path, root)
    registry = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    return evaluate(json.loads(source.read_text(encoding="utf-8")), registry, root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admission", required=True, type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(
        json.loads(args.admission.read_text(encoding="utf-8")),
        json.loads(args.registry.read_text(encoding="utf-8")),
        ROOT,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "failures": result["failures"]}, ensure_ascii=False))
    return 0 if result["status"].startswith("ADMITTED_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
