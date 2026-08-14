#!/usr/bin/env python3
"""Verify the exact-SHA E40 U12 source-authority toolchain manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    manifest_path = (ROOT / args.manifest).resolve()
    out_path = (ROOT / args.out).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures = []
    rows = []
    for row in manifest.get("current_files", []):
        path = (ROOT / row.get("path", "")).resolve()
        exists = path.is_file()
        actual = sha256_file(path) if exists else None
        passed = exists and actual == row.get("sha256")
        rows.append({"path": row.get("path"), "role": row.get("role"), "expected_sha256": row.get("sha256"), "actual_sha256": actual, "status": "PASS" if passed else "FAIL"})
        if not passed:
            failures.append({"code": "CURRENT_FILE_SHA_MISMATCH", "path": row.get("path"), "expected": row.get("sha256"), "actual": actual})
    drift_rows = []
    for row in manifest.get("acknowledged_historical_drift", []):
        path = (ROOT / row.get("path", "")).resolve()
        actual = sha256_file(path) if path.is_file() else None
        acknowledged = (
            actual == row.get("current_sha256")
            and row.get("historical_sha256") != row.get("current_sha256")
            and isinstance(row.get("reason"), str)
            and bool(row.get("reason"))
            and isinstance(row.get("successor_closeout_sha256"), str)
            and len(row.get("successor_closeout_sha256")) == 64
        )
        drift_rows.append({"path": row.get("path"), "historical_sha256": row.get("historical_sha256"), "current_sha256": actual, "status": "PASS_ACKNOWLEDGED" if acknowledged else "FAIL"})
        if not acknowledged:
            failures.append({"code": "HISTORICAL_DRIFT_NOT_FULLY_ACKNOWLEDGED", "path": row.get("path")})
    receipt = {
        "schema": "qingshan.e40.u12.v19.source_authority_integrity_gate.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_CURRENT_INTEGRITY_HISTORICAL_DRIFT_ACKNOWLEDGED" if not failures else "FAIL_CLOSED_INTEGRITY",
        "manifest": args.manifest,
        "manifest_sha256": sha256_file(manifest_path),
        "current_file_count": len(rows),
        "current_pass_count": sum(row["status"] == "PASS" for row in rows),
        "historical_drift_count": len(drift_rows),
        "current_files": rows,
        "historical_drift": drift_rows,
        "failure_count": len(failures),
        "failures": failures,
        "authority_keys_admitted": 0,
        "production_assets_admitted": 0,
        "policy_changed": False,
        "failure_behavior": "NO_KEY_ADMISSION_NO_SOURCE_ADMISSION_NO_RENDER_NO_SUBMIT_NO_TRANSACTION_NO_CREDITS_NO_AGENTCUT_NO_ASSEMBLY",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "current_pass": receipt["current_pass_count"], "current_total": receipt["current_file_count"], "historical_drift": len(drift_rows)}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
