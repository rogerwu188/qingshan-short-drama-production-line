#!/usr/bin/env python3
"""Compile a local-only, no-admission U18 human-QA package."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_GATE = (
    "tools/e40_u18_isolated_asset_output_gate.py",
    "82e7c945d5b3dbfe6f0bee8b02e8963006d744167259608ae29f56e4e075be95",
)
HUMAN_TEMPLATE = (
    "qa/e40_preproduction_20260813/u18_v7_receipt_templates_v1/"
    "E40_U18_V7_HUMAN_QA_RECEIPT_TEMPLATE_V1.json",
    "22b207b140d8d94277efb745177da1eb36c5e2beaf29dcac5d86f2f499a7c864",
)
EXPECTED = {
    "17939df6-4f2c-4148-91c3-38f26870b6dc": {
        "fingerprint": "9c30d6f2df49d060c554e84220ca2a7b3917086eaf0ac177e83a8cf0bf8f3dea",
        "asset_id": "E40-U18-ISO-LOW-AXIS-ARROW-V1",
        "review_asset_id": "E40-U18-ISO-LOW-AXIS-ARROW-V5-CN",
    },
    "bac46b24-b9a2-4a17-ab48-c2327b82b67a": {
        "fingerprint": "23efa6a39dfe8c7d79be2a6340da613909447fd9a708f3c997dca0f12da86adf",
        "asset_id": "E40-U18-ISO-TORN-CURTAIN-SOURCE-V1",
        "review_asset_id": "E40-U18-ISO-TORN-CURTAIN-SOURCE-V5-CN",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wait(failures: list[str]) -> dict:
    return {
        "schema": "qingshan.e40.u18.v19.human_qa_package_result.v1",
        "status": "TASK_LOCAL_REMOTE_WAIT",
        "scope": "U18_ONLY",
        "blocks_other_lanes": False,
        "failures": sorted(set(failures)),
        "human_qa_manifest": None,
        "output_admission_permitted": False,
        "composite_permitted": False,
        "video_authorization_permitted": False,
        "network_capability": False,
        "maximum_new_submissions": 0,
    }


def _safe_file(relative: object, project_root: Path, task_id: str, failures: list[str]) -> Path | None:
    if not isinstance(relative, str) or not relative:
        failures.append(f"OUTPUT_PATH_MISSING:{task_id}")
        return None
    path = project_root / relative
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(project_root.resolve(strict=True))
    except Exception:
        failures.append(f"OUTPUT_PATH_OUTSIDE_ROOT_OR_MISSING:{task_id}")
        return None
    if path.is_symlink() or not resolved.is_file():
        failures.append(f"OUTPUT_SYMLINK_OR_NOT_FILE:{task_id}")
        return None
    return resolved


def compile_human_qa_package(
    promotion_path: Path,
    machine_result_path: Path,
    project_root: Path = ROOT,
) -> dict:
    failures: list[str] = []
    if promotion_path.is_symlink() or machine_result_path.is_symlink():
        return _wait(["SYMLINK_INPUT_REJECTED"])
    try:
        promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
    except Exception:
        return _wait(["V17_PROMOTION_MISSING_OR_INVALID"])
    try:
        machine = json.loads(machine_result_path.read_text(encoding="utf-8"))
    except Exception:
        return _wait(["OUTPUT_MACHINE_RESULT_MISSING_OR_INVALID"])

    promotion_sha = sha256(promotion_path)
    machine_sha = sha256(machine_result_path)
    if promotion.get("schema") != "qingshan.e40.u18.v17.output_machine_promotion_manifest.v1":
        failures.append("V17_PROMOTION_SCHEMA_MISMATCH")
    if promotion.get("status") != "READY_FOR_EXISTING_U18_OUTPUT_MACHINE_QA_NO_ADMISSION":
        failures.append("V17_PROMOTION_NOT_READY")
    if promotion.get("output_admission_permitted") is not False:
        failures.append("V17_PROMOTION_ADMISSION_FLAG_NOT_FALSE")
    if promotion.get("assembly_permitted") is not False or promotion.get("video_authorization_permitted") is not False:
        failures.append("V17_PROMOTION_ASSEMBLY_OR_VIDEO_FLAG_NOT_FALSE")
    if machine.get("schema") != "qingshan.e40.u18.isolated_asset_output_gate.v1":
        failures.append("OUTPUT_MACHINE_RESULT_SCHEMA_MISMATCH")
    if machine.get("status") != "PASS_MACHINE_OUTPUT_GATE_REQUIRES_HUMAN_QA_NO_AUTO_ADMISSION":
        failures.append("OUTPUT_MACHINE_NOT_PASS")
    if machine.get("manifest_sha256") != promotion_sha:
        failures.append("OUTPUT_MACHINE_STALE_OR_WRONG_PROMOTION_SHA")
    if machine.get("failures") != [] or machine.get("automatic_admission") is not False:
        failures.append("OUTPUT_MACHINE_RESULT_NOT_CLEAN_NO_ADMISSION")
    if any(machine.get(key) != 0 for key in ("provider_calls", "transactions", "credits")):
        failures.append("OUTPUT_MACHINE_RESULT_SIDE_EFFECT_COUNTER_NONZERO_OR_MISSING")

    gate_path = project_root / OUTPUT_GATE[0]
    if not gate_path.is_file() or sha256(gate_path) != OUTPUT_GATE[1]:
        failures.append("EXISTING_OUTPUT_GATE_SHA_LOCK_FAILED")
    human_path = project_root / HUMAN_TEMPLATE[0]
    if not human_path.is_file() or sha256(human_path) != HUMAN_TEMPLATE[1]:
        failures.append("V7_HUMAN_TEMPLATE_SHA_LOCK_FAILED")
        human_template = {}
    else:
        try:
            human_template = json.loads(human_path.read_text(encoding="utf-8"))
        except Exception:
            human_template = {}
            failures.append("V7_HUMAN_TEMPLATE_INVALID_JSON")

    assets: list[dict] = []
    seen: set[str] = set()
    for asset in promotion.get("assets") or []:
        task_id = asset.get("exact_task_id")
        expected = EXPECTED.get(task_id)
        if not expected or task_id in seen:
            failures.append(f"EXACT_TASK_ID_SET_OR_DUPLICATE_MISMATCH:{task_id}")
            continue
        seen.add(task_id)
        if asset.get("asset_id") != expected["asset_id"]:
            failures.append(f"ASSET_ID_MISMATCH:{task_id}")
        if asset.get("transaction_fingerprint") != expected["fingerprint"]:
            failures.append(f"FINGERPRINT_MISMATCH:{task_id}")
        if not str(asset.get("provenance") or "").strip():
            failures.append(f"PROVENANCE_MISSING:{task_id}")
        if not str(asset.get("license_or_local_authorship") or "").strip():
            failures.append(f"RIGHTS_MISSING:{task_id}")
        output = _safe_file(asset.get("output_path"), project_root, task_id, failures)
        if output is not None and (not asset.get("output_sha256") or sha256(output) != asset.get("output_sha256")):
            failures.append(f"OUTPUT_SHA_MISMATCH:{task_id}")
        dimensions = asset.get("dimensions") or {}
        if not dimensions.get("width") or not dimensions.get("height"):
            failures.append(f"DIMENSIONS_MISSING:{task_id}")
        assets.append({
            "review_asset_id": expected["review_asset_id"],
            "exact_task_id": task_id,
            "transaction_fingerprint": expected["fingerprint"],
            "output_path": asset.get("output_path"),
            "output_sha256": asset.get("output_sha256"),
            "source_dimensions": dimensions,
            "provenance": asset.get("provenance"),
            "license_or_local_authorship": asset.get("license_or_local_authorship"),
            "review_layers": [
                {"name": "ORIGINAL_RESOLUTION", "source_path": asset.get("output_path"), "source_sha256": asset.get("output_sha256"), "minimum_score": 80},
                {"name": "AUDIENCE_SCALE_720X1280", "source_path": asset.get("output_path"), "source_sha256": asset.get("output_sha256"), "delivery_canvas": {"width": 720, "height": 1280}, "preview_generation_performed": False, "minimum_score": 80},
            ],
        })
    if seen != set(EXPECTED) or len(assets) != 2:
        failures.append("EXACTLY_TWO_EXPECTED_OUTPUTS_REQUIRED")
    if failures:
        return _wait(failures)

    manifest = {
        "schema": "qingshan.e40.u18.v19.human_qa_ready_manifest.v1",
        "status": "READY_FOR_ORIGINAL_AND_720X1280_HUMAN_QA_NO_ADMISSION",
        "scope": "U18_ONLY",
        "input_locks": {
            "v17_promotion_path": str(promotion_path),
            "v17_promotion_sha256": promotion_sha,
            "existing_output_gate_path": OUTPUT_GATE[0],
            "existing_output_gate_sha256": OUTPUT_GATE[1],
            "output_machine_result_path": str(machine_result_path),
            "output_machine_result_sha256": machine_sha,
            "v7_human_template_path": HUMAN_TEMPLATE[0],
            "v7_human_template_sha256": HUMAN_TEMPLATE[1],
        },
        "assets": sorted(assets, key=lambda row: row["exact_task_id"]),
        "review_policy": {
            "layers": human_template.get("review_layers"),
            "hard_gates": human_template.get("hard_gates"),
            "required_asset_rows": human_template.get("required_asset_rows"),
            "template_fill_allowed_only_after_machine_pass": True,
        },
        "human_decision": None,
        "output_admission_permitted": False,
        "composite_permitted": False,
        "video_authorization_permitted": False,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
        "maximum_new_submissions": 0,
    }
    return {
        "schema": "qingshan.e40.u18.v19.human_qa_package_result.v1",
        "status": "HUMAN_QA_PACKAGE_READY_NO_ADMISSION",
        "scope": "U18_ONLY",
        "blocks_other_lanes": False,
        "failures": [],
        "human_qa_manifest": manifest,
        "output_admission_permitted": False,
        "composite_permitted": False,
        "video_authorization_permitted": False,
        "network_capability": False,
        "maximum_new_submissions": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--promotion", required=True, type=Path)
    parser.add_argument("--machine-result", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = compile_human_qa_package(args.promotion, args.machine_result)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if result["status"] == "HUMAN_QA_PACKAGE_READY_NO_ADMISSION" else 3


if __name__ == "__main__":
    raise SystemExit(main())
