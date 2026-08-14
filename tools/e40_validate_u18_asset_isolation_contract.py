#!/usr/bin/env python3
"""Fail-closed validator for the E40 U18 changed-representation asset contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/keyframe_precompile/E40_U18_CHANGED_REPRESENTATION_ASSET_ISOLATION_CONTRACT_V1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    contract_path = args.contract if args.contract.is_absolute() else ROOT / args.contract
    data = json.loads(contract_path.read_text(encoding="utf-8"))
    failures: list[str] = []

    base = data["base_plate"]
    base_path = ROOT / base["path"]
    if not base_path.is_file():
        failures.append("BASE_PLATE_MISSING")
    elif digest(base_path) != base["sha256"]:
        failures.append("BASE_PLATE_SHA_MISMATCH")

    for donor in data.get("approved_material_donors", []):
        donor_path = ROOT / donor["path"]
        if not donor_path.is_file():
            failures.append(f"MATERIAL_DONOR_MISSING:{donor['role']}")
        elif digest(donor_path) != donor["sha256"]:
            failures.append(f"MATERIAL_DONOR_SHA_MISMATCH:{donor['role']}")

    for asset in data["required_new_assets"]:
        asset_id = asset["asset_id"]
        if not asset.get("path"):
            failures.append(f"{asset_id}:PATH_MISSING")
            continue
        path = ROOT / asset["path"]
        if not path.is_file():
            failures.append(f"{asset_id}:FILE_MISSING")
        if not asset.get("sha256"):
            failures.append(f"{asset_id}:SHA_MISSING")
        elif path.is_file() and digest(path) != asset["sha256"]:
            failures.append(f"{asset_id}:SHA_MISMATCH")
        if not str(asset.get("provenance") or "").strip():
            failures.append(f"{asset_id}:PROVENANCE_MISSING")
        if not str(asset.get("license_or_local_authorship") or "").strip():
            failures.append(f"{asset_id}:RIGHTS_MISSING")

    gate = data["execution_gate"]
    if gate != {
        "model": "seedance-2.0-fast",
        "resolution": "720p",
        "authorization": False,
        "provider_post_allowed": False,
        "transaction_creation_allowed": False,
        "paid_submission_allowed": False,
        "maximum_new_submissions": 0,
        "retry_allowed": False,
    }:
        failures.append("EXECUTION_GATE_NOT_EXACTLY_FAIL_CLOSED_FAST720")

    result = {
        "schema": "qingshan.e40.u18.asset_isolation_contract_validation.v1",
        "status": "BLOCKED_MISSING_REQUIRED_ISOLATED_ASSETS" if failures else "PASS_READY_FOR_DETERMINISTIC_COMPOSITE_ONLY",
        "contract_sha256": digest(contract_path),
        "failures": failures,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
