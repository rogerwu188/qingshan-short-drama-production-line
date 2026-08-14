#!/usr/bin/env python3
"""Pinned, read-only V28 regression for the V23-V27 receipt chain."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base  # noqa: E402
import run_e40_u29c_v20_post_link_recovery_publish_gate as recovery  # noqa: E402
import run_e40_u29c_v23_persisted_recovery_receipt_gate as writer  # noqa: E402

MANIFEST = ROOT / "qa/e40_preproduction_20260808/u29c_v27_receipt_chain_integrity_v1/E40_U29C_V27_V23_TO_V26_RECEIPT_CHAIN_MANIFEST_V1.json"
MANIFEST_SHA = "081ce2fffb117615bf57eca5f8b208c9f1a74f79f0d9487d90471f0718f48d89"
V27_VERIFIER = ROOT / "tools/verify_e40_u29c_v27_receipt_chain_integrity.py"
V27_VERIFIER_SHA = "497f0099e568b3b95d2a1cf03201d3894bedfa9e7e10fbce1aca5af6d06cacb8"
V27_AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v27_receipt_chain_integrity_v1/E40_U29C_V27_V23_TO_V26_RECEIPT_CHAIN_INTEGRITY_AUDIT_V1.json"
V27_AUDIT_SHA = "9af20e081e5ea810f72cf1472450b5569127df7a6c43d947d37a2ce5a407a1b0"
SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v28_pinned_chain_regression_v1/E40_U29C_V28_PINNED_RECEIPT_CHAIN_REGRESSION_SPEC_V1.json"
SPEC_SHA = "516d600ab3db26c245b1d759461a214e457719ffbe84e15173a5308e6e327881"
ALLOWLIST = ROOT / "qa/e40_preproduction_20260808/u29c_v26_pinned_receipt_inventory_v1/E40_U29C_V26_HISTORICAL_UNPAIRED_OUTPUT_ALLOWLIST_V1.json"
ALLOWLIST_SHA = "5e25fbc2c9aa33865e4679b2bebc330522cf28925446daf6c684859fa60ab863"
REPORT = SPEC.parent / "E40_U29C_V28_PINNED_RECEIPT_CHAIN_REGRESSION_MATRIX_V1.json"
PASS_STATUS = "PASS_PINNED_FULL_CHAIN_10_OF_10_CURRENT_3_OF_3_EXACT_ALLOWLIST_ZERO_RESIDUE_NO_SUBMIT"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    stat = path.stat()
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": digest(path),
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "mode": oct(stat.st_mode & 0o7777),
        "nlink": stat.st_nlink,
        "uid": stat.st_uid,
        "gid": stat.st_gid,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def rejected_substitutions() -> list[dict]:
    rows = []
    for flag in ("--manifest", "--allowlist", "--receipt-root", "--output-root"):
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), flag, "/tmp/forbidden-substitution"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        rows.append({
            "argument": flag,
            "exit_code": proc.returncode,
            "rejected_before_verification": proc.returncode == 2,
            "report_created": REPORT.exists(),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the fixed-path V28 receipt-chain regression; path substitutions are forbidden."
    )
    parser.parse_args()
    if REPORT.exists():
        raise SystemExit("REPORT_ALREADY_EXISTS")

    failures: list[str] = []
    pins = [
        (MANIFEST, MANIFEST_SHA),
        (V27_VERIFIER, V27_VERIFIER_SHA),
        (V27_AUDIT, V27_AUDIT_SHA),
        (SPEC, SPEC_SHA),
        (ALLOWLIST, ALLOWLIST_SHA),
    ]
    pins_before = [identity(path) for path, _ in pins]
    pin_match = [row["sha256"] == expected for row, (_, expected) in zip(pins_before, pins)]
    if not all(pin_match):
        failures.append("PIN_MISMATCH_BEFORE_VERIFICATION")

    # No receipt/output verification is attempted unless every authority is exact.
    if failures:
        print(json.dumps({"status": "FAIL_CLOSED", "failures": failures}))
        return 1

    substitution_rows = rejected_substitutions()
    if REPORT.exists() or not all(row["rejected_before_verification"] and not row["report_created"] for row in substitution_rows):
        failures.append("SUBSTITUTION_NOT_REJECTED_BEFORE_VERIFICATION")

    manifest = json.loads(MANIFEST.read_text())
    chain_rows = []
    for binding in manifest["bindings"]:
        path = ROOT / binding["path"]
        actual = digest(path) if path.is_file() else None
        chain_rows.append({
            "path": binding["path"],
            "expected_sha256": binding["sha256"],
            "actual_sha256": actual,
            "match": actual == binding["sha256"],
        })
    if len(chain_rows) != 10 or not all(row["match"] for row in chain_rows):
        failures.append("CHAIN_NOT_10_OF_10")

    receipt_paths = sorted(writer.RECEIPT_ROOT.glob("*.recovered-success-receipt.json"))
    protected_paths = list(receipt_paths)
    binding_rows = []
    outputs = []
    for receipt_path in receipt_paths:
        try:
            record = writer.validate_restart(receipt_path)
            output_path = ROOT / record["output"]
            protected_paths.append(output_path)
            outputs.append(record["output"])
            binding_rows.append({
                "receipt": str(receipt_path.relative_to(ROOT)),
                "output": record["output"],
                "valid": True,
            })
        except Exception as exc:  # fail-closed evidence intentionally records only type
            binding_rows.append({
                "receipt": str(receipt_path.relative_to(ROOT)),
                "valid": False,
                "error": type(exc).__name__,
            })
    if len(binding_rows) != 3 or sum(row["valid"] for row in binding_rows) != 3:
        failures.append("CURRENT_BINDINGS_NOT_3_OF_3")
    duplicates = sorted(path for path, count in Counter(outputs).items() if count > 1)
    if duplicates:
        failures.append("DUPLICATE_OUTPUT_BINDING")

    protected_before = [identity(path) for path in protected_paths]
    allowlist = json.loads(ALLOWLIST.read_text())
    allow_entries = allowlist.get("entries", [])
    exact_allowlist = (
        allowlist.get("status") == "FAIL_CLOSED_NON_ADMITTED_LOCAL_HARNESS_EVIDENCE"
        and len(allow_entries) == 1
        and allow_entries[0].get("path")
        == "qa/e40_preproduction_20260808/u29c_v20_post_link_recovery_final_output_v1/E40_U29C_V23_RECOVERED_WITH_RECEIPT_GATE_V1.json"
        and allow_entries[0].get("sha256")
        == "02e40965b21b8e29a03681df8de612aff2d4ce9747ecfc868d7d7601983fe83b"
        and digest(ROOT / allow_entries[0]["path"]) == allow_entries[0]["sha256"]
    )
    if not exact_allowlist:
        failures.append("EXACT_ALLOWLIST_MISMATCH")

    bound = set(outputs)
    candidates = sorted(
        path for path in recovery.FINAL_ROOT.glob("E40_U29C_V2[34]*.json")
        if path.is_file() and "RECOVERED" in path.name
    )
    observed_unpaired = {
        str(path.relative_to(ROOT)): digest(path)
        for path in candidates
        if str(path.relative_to(ROOT)) not in bound
    }
    allowed_unpaired = {row["path"]: row["sha256"] for row in allow_entries}
    if observed_unpaired != allowed_unpaired:
        failures.append("OBSERVED_UNPAIRED_NOT_EXACT_ALLOWLIST")

    residue = {
        "data_hidden": sorted(path.name for path in recovery.FINAL_ROOT.iterdir() if path.name.startswith(".u29c-v20-hidden-")),
        "receipt_hidden": sorted(path.name for path in writer.RECEIPT_ROOT.iterdir() if path.name.startswith(".u29c-v23-receipt-hidden-")),
        "staging": sorted(path.name for path in recovery.STAGING_ROOT.iterdir()),
    }
    if any(residue.values()):
        failures.append("RESIDUE")

    v27_audit = json.loads(V27_AUDIT.read_text())
    v28_spec = json.loads(SPEC.read_text())
    admission_closed = (
        v27_audit.get("admission_closed") is True
        and v27_audit.get("execution_permitted") is False
        and v27_audit.get("provider_post_allowed") is False
        and v27_audit.get("maximum_new_submissions") == 0
        and v28_spec.get("execution_permitted") is False
        and v28_spec.get("provider_post_allowed") is False
        and v28_spec.get("maximum_new_submissions") == 0
    )
    if not admission_closed:
        failures.append("ADMISSION_NOT_CLOSED")

    protected_after = [identity(path) for path in protected_paths]
    pins_after = [identity(path) for path, _ in pins]
    if protected_before != protected_after:
        failures.append("RECEIPT_OR_OUTPUT_MUTATION")
    if pins_before != pins_after:
        failures.append("PIN_MUTATION")

    status = PASS_STATUS if not failures else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29c.v28.pinned_receipt_chain_regression_matrix.v1",
        "episode": "E40",
        "unit_id": "U29C",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "execution_permitted": False,
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "pins_before": pins_before,
        "pin_expected_sha256": [expected for _, expected in pins],
        "pin_match_count": sum(pin_match),
        "pins_after": pins_after,
        "chain_binding_count": len(chain_rows),
        "chain_match_count": sum(row["match"] for row in chain_rows),
        "chain_bindings": chain_rows,
        "current_receipt_count": len(binding_rows),
        "current_valid_binding_count": sum(row["valid"] for row in binding_rows),
        "current_bindings": binding_rows,
        "duplicate_output_bindings": duplicates,
        "protected_receipt_output_identity_before": protected_before,
        "protected_receipt_output_identity_after": protected_after,
        "exact_allowlist": allowed_unpaired,
        "exact_allowlist_valid_non_admitted": exact_allowlist,
        "observed_unpaired": observed_unpaired,
        "unpaired_exact_match": observed_unpaired == allowed_unpaired,
        "residue": residue,
        "admission_closed": admission_closed,
        "substitution_negatives": substitution_rows,
        "substitution_negative_count": sum(row["rejected_before_verification"] for row in substitution_rows),
        "blind_replay_allowed": False,
        "failures": failures,
        "side_effects": {
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
            "retries": 0,
            "agentcut": 0,
            "assembly": 0,
        },
        "next_action": "Register V29 read-only receipt/output filesystem-stat integrity audit.",
    }
    fd = os.open(REPORT, base.create_flags(), 0o600)
    base.write_all(fd, (json.dumps(payload, indent=2) + "\n").encode())
    os.fsync(fd)
    os.close(fd)
    print(json.dumps({
        "status": status,
        "chain": sum(row["match"] for row in chain_rows),
        "receipts": sum(row["valid"] for row in binding_rows),
        "substitution_negatives": sum(row["rejected_before_verification"] for row in substitution_rows),
        "failures": failures,
    }))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
