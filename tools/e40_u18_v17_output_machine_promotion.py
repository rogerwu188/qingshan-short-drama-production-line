#!/usr/bin/env python3
"""Compile a local-only, no-admission U18 output-machine promotion manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tools.e40_u18_v9_offline_snapshot_ingest import EXPECTED, TEMPLATES, validate

ROOT = Path(__file__).resolve().parents[1]
RESULT_NAMES = {
    task_id: f"result_{task_id}.json" for task_id in EXPECTED
}
CREDIT_NAME = "credit_authoritative_exact_two.json"
V7_FILES = {
    "download": (
        "qa/e40_preproduction_20260813/u18_v7_receipt_templates_v1/"
        "E40_U18_V7_EXACT_DOWNLOAD_RECEIPT_TEMPLATE_V1.json",
        "2a524d738a51dbde381eef8aee020a9c6209fc22fd06fcccf35d87f75e7d9544",
    ),
    "credit": (
        "qa/e40_preproduction_20260813/u18_v7_receipt_templates_v1/"
        "E40_U18_V7_CREDIT_CLASSIFICATION_RECEIPT_TEMPLATE_V1.json",
        "6971b3048cbd37669bb2ec36907eb3f6bd72705cb1ebd24733954ee177a097ae",
    ),
    "machine": (
        "qa/e40_preproduction_20260813/u18_v7_receipt_templates_v1/"
        "E40_U18_V7_OUTPUT_MACHINE_QA_INPUT_CONTRACT_V1.json",
        "90ab967ad6a21c5df636a6eaf8a800cc6a1e4889c0b1cb2234e21953a5fc9033",
    ),
}
V11_BOUNDARY = (
    "qa/e40_preproduction_20260813/u18_v11_snapshot_boundary_v1/"
    "E40_U18_V11_BOUNDARY_AND_NEGATIVE_TEST_RECEIPT_V1.json",
    "ff993f72738b61d84006ea3065ff35c6888fd9453e836d31bc7afa304e1cb960",
)
ASSETS = {
    "17939df6-4f2c-4148-91c3-38f26870b6dc": {
        "asset_id": "E40-U18-ISO-LOW-AXIS-ARROW-V1",
        "expected_path": "working_assets/e40_preproduction_20260813/u18_v5_isolated_assets/E40-U18-ISO-LOW-AXIS-ARROW-V5-CN_17939df6-4f2c-4148-91c3-38f26870b6dc.png",
    },
    "bac46b24-b9a2-4a17-ab48-c2327b82b67a": {
        "asset_id": "E40-U18-ISO-TORN-CURTAIN-SOURCE-V1",
        "expected_path": "working_assets/e40_preproduction_20260813/u18_v5_isolated_assets/E40-U18-ISO-TORN-CURTAIN-SOURCE-V5-CN_bac46b24-b9a2-4a17-ab48-c2327b82b67a.png",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wait(failures: list[str], ingest: dict | None = None) -> dict:
    return {
        "schema": "qingshan.e40.u18.v17.output_machine_promotion_result.v1",
        "status": "TASK_LOCAL_REMOTE_WAIT",
        "scope": "U18_ONLY",
        "blocks_other_lanes": False,
        "failures": sorted(set(failures)),
        "v9_ingest": ingest,
        "promotion_manifest": None,
        "output_admission_permitted": False,
        "assembly_permitted": False,
        "video_authorization_permitted": False,
        "network_capability": False,
        "maximum_new_submissions": 0,
    }


def compile_promotion(
    snapshot_root: Path,
    readiness_path: Path,
    project_root: Path = ROOT,
) -> dict:
    failures: list[str] = []
    try:
        readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    except Exception:
        return _wait(["V15_READINESS_MISSING_OR_INVALID"])
    if readiness.get("status") != "READY_FOR_LOCAL_OUTPUT_QA":
        failures.append("V15_NOT_READY_FOR_LOCAL_OUTPUT_QA")
    if (readiness.get("ingest") or {}).get("status") != "PASS":
        failures.append("V15_EMBEDDED_V9_NOT_PASS")

    result_paths = [snapshot_root / RESULT_NAMES[task_id] for task_id in EXPECTED]
    credit_path = snapshot_root / CREDIT_NAME
    ingest = validate(result_paths, credit_path, snapshot_root)
    if ingest.get("status") != "PASS":
        failures.append("V9_EXACT_VALID_REQUIRED")
    readiness_ingest = readiness.get("ingest") or {}
    readiness_result_locks = {
        row.get("task_id"): row.get("snapshot_sha256")
        for row in readiness_ingest.get("result_rows") or []
    }
    for result_path in result_paths:
        task_id = result_path.stem.removeprefix("result_")
        if result_path.is_file() and readiness_result_locks.get(task_id) != sha256(result_path):
            failures.append(f"V15_RESULT_SNAPSHOT_SHA_LOCK_FAILED:{task_id}")
    if credit_path.is_file() and readiness_ingest.get("credit_snapshot_sha256") != sha256(credit_path):
        failures.append("V15_CREDIT_SNAPSHOT_SHA_LOCK_FAILED")

    for label, (relative, expected_sha) in V7_FILES.items():
        path = project_root / relative
        if not path.is_file() or sha256(path) != expected_sha:
            failures.append(f"V7_{label.upper()}_TEMPLATE_SHA_LOCK_FAILED")
    boundary_path = project_root / V11_BOUNDARY[0]
    if not boundary_path.is_file() or sha256(boundary_path) != V11_BOUNDARY[1]:
        failures.append("V11_BOUNDARY_SHA_LOCK_FAILED")

    try:
        credit = json.loads(credit_path.read_text(encoding="utf-8"))
    except Exception:
        credit = {}
    classification = credit.get("classification") or {}
    if any(classification.get(key) is None for key in ("pay", "refund", "net", "status")):
        failures.append("AUTHORITATIVE_CREDIT_CLASSIFICATION_INCOMPLETE")
    elif classification.get("status") not in {"PASS", "COMPLETE", "CLASSIFIED", "AUTHORITATIVE_COMPLETE"}:
        failures.append("AUTHORITATIVE_CREDIT_CLASSIFICATION_STATUS_NOT_COMPLETE")

    assets: list[dict] = []
    for result_path in result_paths:
        try:
            row = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        task_id = row.get("task_id")
        expected = EXPECTED.get(task_id)
        binding = ASSETS.get(task_id)
        if not expected or not binding:
            continue
        output = row.get("output") or {}
        if row.get("status") != "SUCCESS":
            failures.append(f"RESULT_NOT_SUCCESS:{task_id}")
        if row.get("submission_fingerprint") != expected[1]:
            failures.append(f"FINGERPRINT_LOCK_FAILED:{task_id}")
        if output.get("path") != binding["expected_path"]:
            failures.append(f"DOWNLOAD_PATH_LOCK_FAILED:{task_id}")
        file_path = project_root / str(output.get("path") or "__missing__")
        if file_path.is_symlink() or not file_path.is_file():
            failures.append(f"DOWNLOAD_FILE_MISSING_OR_SYMLINK:{task_id}")
        elif not output.get("sha256") or sha256(file_path) != output.get("sha256"):
            failures.append(f"DOWNLOAD_SHA_LOCK_FAILED:{task_id}")
        if not str(output.get("provenance") or "").strip():
            failures.append(f"PROVENANCE_MISSING:{task_id}")
        if not str(output.get("license_or_local_authorship") or "").strip():
            failures.append(f"RIGHTS_MISSING:{task_id}")
        dimensions = output.get("dimensions") or {}
        if not dimensions.get("width") or not dimensions.get("height"):
            failures.append(f"DIMENSIONS_MISSING:{task_id}")
        assets.append({
            "asset_id": binding["asset_id"],
            "exact_task_id": task_id,
            "transaction_fingerprint": expected[1],
            "output_path": output.get("path"),
            "output_sha256": output.get("sha256"),
            "dimensions": dimensions,
            "provenance": output.get("provenance"),
            "license_or_local_authorship": output.get("license_or_local_authorship"),
            "output_mask_path": output.get("mask_path"),
            "output_mask_sha256": output.get("mask_sha256"),
        })
    if len(assets) != 2:
        failures.append("EXACTLY_TWO_PROMOTION_ASSETS_REQUIRED")
    if failures:
        return _wait(failures, ingest)

    manifest = {
        "schema": "qingshan.e40.u18.v17.output_machine_promotion_manifest.v1",
        "status": "READY_FOR_EXISTING_U18_OUTPUT_MACHINE_QA_NO_ADMISSION",
        "scope": "U18_ONLY",
        "source_snapshot_locks": {
            "results": {path.name: sha256(path) for path in result_paths},
            "authoritative_credit": {"path": CREDIT_NAME, "sha256": sha256(credit_path)},
        },
        "contract_locks": {
            "v7_template_sha256": {label: expected for label, (_, expected) in V7_FILES.items()},
            "v11_boundary_path": V11_BOUNDARY[0],
            "v11_boundary_sha256": V11_BOUNDARY[1],
        },
        "credit_classification": classification,
        "assets": sorted(assets, key=lambda asset: asset["exact_task_id"]),
        "next_gate": "tools/e40_u18_isolated_asset_output_gate.py",
        "output_admission_permitted": False,
        "assembly_permitted": False,
        "video_authorization_permitted": False,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
        "maximum_new_submissions": 0,
    }
    return {
        "schema": "qingshan.e40.u18.v17.output_machine_promotion_result.v1",
        "status": "PROMOTION_MANIFEST_READY_FOR_EXISTING_U18_OUTPUT_MACHINE_QA_NO_ADMISSION",
        "scope": "U18_ONLY",
        "blocks_other_lanes": False,
        "failures": [],
        "v9_ingest": ingest,
        "promotion_manifest": manifest,
        "output_admission_permitted": False,
        "assembly_permitted": False,
        "video_authorization_permitted": False,
        "network_capability": False,
        "maximum_new_submissions": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-root", required=True, type=Path)
    parser.add_argument("--v15-readiness", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = compile_promotion(args.snapshot_root, args.v15_readiness)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if result["status"].startswith("PROMOTION_MANIFEST_READY") else 3


if __name__ == "__main__":
    raise SystemExit(main())
