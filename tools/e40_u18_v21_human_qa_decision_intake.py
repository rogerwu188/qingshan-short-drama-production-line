#!/usr/bin/env python3
"""Validate local U18 dual-scale human decisions; emit only draft/proposal."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V7_HUMAN = (
    "qa/e40_preproduction_20260813/u18_v7_receipt_templates_v1/"
    "E40_U18_V7_HUMAN_QA_RECEIPT_TEMPLATE_V1.json",
    "22b207b140d8d94277efb745177da1eb36c5e2beaf29dcac5d86f2f499a7c864",
)
V19_RECEIPT = (
    "qa/e40_preproduction_20260813/u18_v19_human_qa_package_contract_v1/"
    "E40_U18_V19_HUMAN_QA_PACKAGE_CONTRACT_TEST_RECEIPT_V1.json",
    "d6a0b7586947f83907ef12e922aeb6d5ecc6d3dac6a546844c1ecd9f88ac263e",
)
EXPECTED = {
    "17939df6-4f2c-4148-91c3-38f26870b6dc": "9c30d6f2df49d060c554e84220ca2a7b3917086eaf0ac177e83a8cf0bf8f3dea",
    "bac46b24-b9a2-4a17-ab48-c2327b82b67a": "23efa6a39dfe8c7d79be2a6340da613909447fd9a708f3c997dca0f12da86adf",
}
SCALES = {"ORIGINAL_RESOLUTION", "AUDIENCE_SCALE_720X1280"}
HARD_GATES = {
    "17939df6-4f2c-4148-91c3-38f26870b6dc": {
        "EXACTLY_ONE_COMPLETE_ARROW", "TIP_LEFT_FLETCHING_RIGHT",
        "NO_CROP_OR_FORESHORTENING", "AUDIENCE_READABLE",
        "OCR_ZERO", "NO_WATERMARK", "EXTRACTION_EDGE_USABLE",
    },
    "bac46b24-b9a2-4a17-ab48-c2327b82b67a": {
        "ONE_IRREGULAR_TEAR", "VISIBLE_SOURCE_DEPTH", "NO_RECTANGULAR_PATCH",
        "AUDIENCE_READABLE", "OCR_ZERO", "NO_WATERMARK",
        "EXTRACTION_EDGE_USABLE",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None
    except ValueError:
        return False


def _base(status: str, failures: list[str], draft: dict | None, proposal: dict | None) -> dict:
    return {
        "schema": "qingshan.e40.u18.v21.human_qa_decision_intake_result.v1",
        "status": status,
        "scope": "U18_ONLY",
        "blocks_other_lanes": False,
        "failures": sorted(set(failures)),
        "failure_memory_draft": draft,
        "formal_failure_memory_write_performed": False,
        "asset_admission_proposal": proposal,
        "output_admission_permitted": False,
        "composite_permitted": False,
        "video_authorization_permitted": False,
        "authorization_required": True,
        "network_capability": False,
        "maximum_new_submissions": 0,
    }


def intake_decisions(
    manifest_path: Path,
    decisions_path: Path,
    project_root: Path = ROOT,
) -> dict:
    failures: list[str] = []
    if manifest_path.is_symlink() or decisions_path.is_symlink():
        failures.append("SYMLINK_INPUT_REJECTED")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        manifest = {}
        failures.append("V19_HUMAN_QA_MANIFEST_MISSING_OR_INVALID")
    try:
        decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    except Exception:
        decisions = {}
        failures.append("HUMAN_QA_DECISIONS_MISSING_OR_INVALID")

    manifest_sha = sha256(manifest_path) if manifest_path.is_file() else None
    if manifest.get("schema") != "qingshan.e40.u18.v19.human_qa_ready_manifest.v1" or manifest.get("status") != "READY_FOR_ORIGINAL_AND_720X1280_HUMAN_QA_NO_ADMISSION":
        failures.append("V19_HUMAN_QA_MANIFEST_NOT_READY")
    if any(manifest.get(key) is not False for key in ("output_admission_permitted", "composite_permitted", "video_authorization_permitted")):
        failures.append("V19_HUMAN_QA_MANIFEST_PERMISSION_FLAG_NOT_FALSE")
    if decisions.get("human_qa_manifest_sha256") != manifest_sha:
        failures.append("STALE_OR_WRONG_V19_HUMAN_QA_MANIFEST_SHA")

    for label, (relative, expected_sha) in {"V7_HUMAN": V7_HUMAN, "V19_RECEIPT": V19_RECEIPT}.items():
        path = project_root / relative
        if not path.is_file() or sha256(path) != expected_sha:
            failures.append(f"{label}_PHYSICAL_SHA_LOCK_FAILED")
        if decisions.get(label.lower() + "_sha256") != expected_sha:
            failures.append(f"{label}_DECLARED_SHA_LOCK_FAILED")

    reviewer = decisions.get("reviewer")
    reviewed_at = decisions.get("reviewed_at")
    if not isinstance(reviewer, str) or not reviewer.strip():
        failures.append("REVIEWER_MISSING")
    if not _valid_timestamp(reviewed_at):
        failures.append("REVIEWED_AT_MISSING_OR_INVALID")

    manifest_assets = {row.get("exact_task_id"): row for row in manifest.get("assets") or []}
    decision_assets = decisions.get("assets") or []
    seen: set[str] = set()
    normalized: list[dict] = []
    hard_failures: list[str] = []
    for decision in decision_assets:
        task_id = decision.get("exact_task_id")
        source = manifest_assets.get(task_id)
        expected_fp = EXPECTED.get(task_id)
        if not source or not expected_fp or task_id in seen:
            failures.append(f"DECISION_TASK_SET_OR_DUPLICATE_MISMATCH:{task_id}")
            continue
        seen.add(task_id)
        if decision.get("transaction_fingerprint") != expected_fp or source.get("transaction_fingerprint") != expected_fp:
            failures.append(f"FINGERPRINT_DRIFT:{task_id}")
        if decision.get("output_sha256") != source.get("output_sha256") or not source.get("output_sha256"):
            failures.append(f"OUTPUT_SHA_DRIFT:{task_id}")
        layers = decision.get("review_layers") or []
        by_name = {row.get("name"): row for row in layers if isinstance(row, dict)}
        if set(by_name) != SCALES or len(layers) != 2:
            failures.append(f"MISSING_OR_DUPLICATE_REVIEW_SCALE:{task_id}")
        normalized_layers = []
        for name in sorted(SCALES):
            layer = by_name.get(name) or {}
            score = layer.get("score")
            hard_gates = layer.get("hard_gate_results")
            decision_value = layer.get("decision")
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                failures.append(f"SCORE_MISSING:{task_id}:{name}")
            elif score < 80:
                hard_failures.append(f"SCORE_BELOW_80:{task_id}:{name}")
            if not isinstance(hard_gates, dict) or set(hard_gates) != HARD_GATES[task_id]:
                failures.append(f"HARD_GATE_SET_MISSING_OR_DRIFTED:{task_id}:{name}")
            elif any(value is not True for value in hard_gates.values()):
                hard_failures.append(f"HARD_GATE_FAIL:{task_id}:{name}")
            if decision_value != "PASS":
                hard_failures.append(f"LAYER_DECISION_NOT_PASS:{task_id}:{name}")
            normalized_layers.append({"name": name, "score": score, "hard_gate_results": hard_gates, "decision": decision_value})
        normalized.append({
            "exact_task_id": task_id,
            "transaction_fingerprint": expected_fp,
            "output_sha256": source.get("output_sha256"),
            "review_layers": normalized_layers,
        })
    if seen != set(EXPECTED) or set(manifest_assets) != set(EXPECTED):
        failures.append("EXACTLY_TWO_EXPECTED_ASSETS_AND_DECISIONS_REQUIRED")

    all_failures = sorted(set(failures + hard_failures))
    source_locks = {
        "human_qa_manifest_path": str(manifest_path),
        "human_qa_manifest_sha256": manifest_sha,
        "human_qa_decisions_path": str(decisions_path),
        "human_qa_decisions_sha256": sha256(decisions_path) if decisions_path.is_file() else None,
        "v7_human_template_sha256": V7_HUMAN[1],
        "v19_receipt_sha256": V19_RECEIPT[1],
    }
    if all_failures:
        draft = {
            "schema": "qingshan.e40.u18.v21.failure_memory_draft.v1",
            "status": "DRAFT_ONLY_NOT_WRITTEN_TO_FORMAL_MEMORY",
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "source_locks": source_locks,
            "failures": all_failures,
            "failed_asset_decisions": normalized,
            "retry_authorized": False,
            "formal_memory_update_permitted": False,
        }
        return _base("TASK_LOCAL_REMOTE_WAIT", all_failures, draft, None)

    proposal = {
        "schema": "qingshan.e40.u18.v21.asset_admission_proposal.v1",
        "status": "PROPOSED_PENDING_INDEPENDENT_AUTHORIZATION",
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "source_locks": source_locks,
        "assets": sorted(normalized, key=lambda row: row["exact_task_id"]),
        "output_admission_permitted": False,
        "composite_permitted": False,
        "video_authorization_permitted": False,
        "independent_authorization_required": True,
    }
    return _base("ASSET_ADMISSION_PROPOSAL_READY_PENDING_INDEPENDENT_AUTHORIZATION", [], None, proposal)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--human-qa-manifest", required=True, type=Path)
    parser.add_argument("--decisions", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = intake_decisions(args.human_qa_manifest, args.decisions)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if result["status"].startswith("ASSET_ADMISSION_PROPOSAL_READY") else 3


if __name__ == "__main__":
    raise SystemExit(main())
