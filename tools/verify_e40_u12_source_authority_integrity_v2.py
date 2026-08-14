#!/usr/bin/env python3
"""Verify V21 integrity manifest V2 including archived historical bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def check_file(row: dict[str, Any]) -> dict[str, Any]:
    path = (ROOT / row.get("path", "")).resolve()
    exists = path.is_file()
    actual = sha256_file(path) if exists else None
    return {
        "path": row.get("path"),
        "role": row.get("role"),
        "expected_sha256": row.get("sha256"),
        "actual_sha256": actual,
        "status": "PASS" if exists and actual == row.get("sha256") else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    manifest_path = (ROOT / args.manifest).resolve()
    out_path = (ROOT / args.out).resolve()
    manifest = load_json(manifest_path)
    failures: list[dict[str, Any]] = []
    if manifest.get("schema") != "qingshan.e40.u12.v21.source_authority_integrity_manifest.v2":
        failures.append({"code": "MANIFEST_SCHEMA"})

    base_ref = manifest.get("base_manifest") if isinstance(manifest.get("base_manifest"), dict) else {}
    base_path = (ROOT / base_ref.get("path", "")).resolve()
    base_exists = base_path.is_file()
    base_actual = sha256_file(base_path) if base_exists else None
    if not base_exists or base_actual != base_ref.get("sha256"):
        failures.append({"code": "BASE_MANIFEST_SHA", "expected": base_ref.get("sha256"), "actual": base_actual})
        base = {}
    else:
        base = load_json(base_path)

    current_rows = [check_file(row) for row in base.get("current_files", []) if isinstance(row, dict)]
    additional_rows = [check_file(row) for row in manifest.get("additional_files", []) if isinstance(row, dict)]
    for row in current_rows + additional_rows:
        if row["status"] != "PASS":
            failures.append({"code": "FILE_SHA_MISMATCH", "path": row["path"], "expected": row["expected_sha256"], "actual": row["actual_sha256"]})

    pair = manifest.get("versioned_validator_pair") if isinstance(manifest.get("versioned_validator_pair"), dict) else {}
    v7 = check_file(pair.get("historical_v7", {}))
    v8 = check_file(pair.get("current_v8", {}))
    pair_pass = (
        v7["status"] == "PASS"
        and v8["status"] == "PASS"
        and v7["path"] != v8["path"]
        and v7["actual_sha256"] != v8["actual_sha256"]
    )
    if not pair_pass:
        failures.append({"code": "VERSIONED_VALIDATOR_PAIR", "v7": v7, "v8": v8})

    unarchived = 0 if pair_pass else 1
    if unarchived != manifest.get("unarchived_historical_drift_count_expected"):
        failures.append({"code": "UNARCHIVED_DRIFT_COUNT", "actual": unarchived, "expected": manifest.get("unarchived_historical_drift_count_expected")})
    receipt = {
        "schema": "qingshan.e40.u12.v21.source_authority_integrity_gate.v2",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_CURRENT_AND_HISTORICAL_INTEGRITY_NO_UNARCHIVED_DRIFT" if not failures else "FAIL_CLOSED_INTEGRITY_V2",
        "manifest": args.manifest,
        "manifest_sha256": sha256_file(manifest_path),
        "base_manifest_sha256": base_actual,
        "current_file_count": len(current_rows),
        "current_pass_count": sum(row["status"] == "PASS" for row in current_rows),
        "additional_file_count": len(additional_rows),
        "additional_pass_count": sum(row["status"] == "PASS" for row in additional_rows),
        "versioned_validator_pair": {"historical_v7": v7, "current_v8": v8, "status": "PASS" if pair_pass else "FAIL"},
        "unarchived_historical_drift_count": unarchived,
        "failure_count": len(failures),
        "failures": failures,
        "authority_keys_admitted": 0,
        "production_assets_admitted": 0,
        "policy_changed": False,
        "failure_behavior": "NO_KEY_ADMISSION_NO_SOURCE_ADMISSION_NO_RENDER_NO_SUBMIT_NO_TRANSACTION_NO_CREDITS_NO_AGENTCUT_NO_ASSEMBLY",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "current": f"{receipt['current_pass_count']}/{receipt['current_file_count']}", "additional": f"{receipt['additional_pass_count']}/{receipt['additional_file_count']}", "unarchived_drift": unarchived}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
