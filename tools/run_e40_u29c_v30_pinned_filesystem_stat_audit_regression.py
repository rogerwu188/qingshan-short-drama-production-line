#!/usr/bin/env python3
"""Pinned V30 regression over the V29 receipt/output filesystem-stat audit."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base  # noqa: E402
import run_e40_u29c_v20_post_link_recovery_publish_gate as recovery  # noqa: E402
import run_e40_u29c_v23_persisted_recovery_receipt_gate as writer  # noqa: E402

V29_AUDITOR = ROOT / "tools/audit_e40_u29c_v29_receipt_output_filesystem_stat_integrity.py"
V29_AUDITOR_SHA = "345b8fff9bc015948c056ab041219bd8dc25e7eae7883871a67d032f55542828"
V29_AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v29_receipt_filesystem_stat_audit_v1/E40_U29C_V29_RECEIPT_OUTPUT_FILESYSTEM_STAT_INTEGRITY_AUDIT_V1.json"
V29_AUDIT_SHA = "e2cba033e45dddb9cee26594f18ac13963fbaad34b4293e48d3586c2c46f377b"
V30_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v30_pinned_filesystem_stat_regression_v1/E40_U29C_V30_PINNED_FILESYSTEM_STAT_AUDIT_REGRESSION_SPEC_V1.json"
V30_SPEC_SHA = "06086c8f5433aaf6b5bc782a25210eac2a9eae8c27b3b49193b0bece158190f4"
ALLOWLIST = ROOT / "qa/e40_preproduction_20260808/u29c_v26_pinned_receipt_inventory_v1/E40_U29C_V26_HISTORICAL_UNPAIRED_OUTPUT_ALLOWLIST_V1.json"
ALLOWLIST_SHA = "5e25fbc2c9aa33865e4679b2bebc330522cf28925446daf6c684859fa60ab863"
REPORT = V30_SPEC.parent / "E40_U29C_V30_PINNED_FILESYSTEM_STAT_AUDIT_REGRESSION_MATRIX_V1.json"
PASS_STATUS = "PASS_PINNED_3_OF_3_STAT_PAIRS_6_OF_6_UNIQUE_INODES_EXACT_SNAPSHOT_NO_MUTATION_NO_SUBMIT"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    value = os.lstat(path)
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": digest(path) if stat.S_ISREG(value.st_mode) else None,
        "device": value.st_dev,
        "inode": value.st_ino,
        "mode": oct(stat.S_IMODE(value.st_mode)),
        "nlink": value.st_nlink,
        "uid": value.st_uid,
        "gid": value.st_gid,
        "size": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
        "regular_file": stat.S_ISREG(value.st_mode),
        "directory": stat.S_ISDIR(value.st_mode),
        "symlink": stat.S_ISLNK(value.st_mode),
    }


def substitution_negatives() -> list[dict]:
    rows = []
    for flag in ("--auditor", "--audit", "--spec", "--receipt-root", "--output-root", "--allowlist"):
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
        description="Run fixed V30 regression; all authority and root substitutions are forbidden.",
        allow_abbrev=False,
    )
    parser.parse_args()
    if REPORT.exists():
        raise SystemExit("REPORT_ALREADY_EXISTS")

    failures: list[str] = []
    pins = [
        (V29_AUDITOR, V29_AUDITOR_SHA),
        (V29_AUDIT, V29_AUDIT_SHA),
        (V30_SPEC, V30_SPEC_SHA),
        (ALLOWLIST, ALLOWLIST_SHA),
    ]
    pins_before = [identity(path) for path, _ in pins]
    pin_matches = [row["sha256"] == expected for row, (_, expected) in zip(pins_before, pins)]
    if not all(pin_matches):
        print(json.dumps({"status": "FAIL_CLOSED_PIN_MISMATCH", "pin_matches": pin_matches}))
        return 1

    v29 = json.loads(V29_AUDIT.read_text())
    v29_authority_valid = (
        v29.get("status")
        == "PASS_3_OF_3_RECEIPT_OUTPUT_STAT_IDENTITIES_EXACT_ROOTS_UNIQUE_INODES_NO_MUTATION_NO_SUBMIT"
        and v29.get("valid_pair_count") == 3
        and v29.get("unique_inode_token_count") == 6
        and v29.get("root_contract_valid") is True
        and v29.get("exact_allowlist_valid_non_admitted") is True
        and v29.get("failures") == []
        and v29.get("execution_permitted") is False
        and v29.get("provider_post_allowed") is False
        and v29.get("maximum_new_submissions") == 0
    )
    if not v29_authority_valid:
        failures.append("V29_AUTHORITY_NOT_PASS_CLOSED")

    negatives = substitution_negatives()
    if REPORT.exists() or not all(row["rejected_before_verification"] and not row["report_created"] for row in negatives):
        failures.append("SUBSTITUTION_NOT_REJECTED_BEFORE_VERIFICATION")

    receipt_paths = sorted(writer.RECEIPT_ROOT.glob("*.recovered-success-receipt.json"))
    protected_paths: list[Path] = []
    pair_rows = []
    inode_tokens = []
    for receipt_path in receipt_paths:
        protected_paths.append(receipt_path)
        try:
            record = writer.validate_restart(receipt_path)
            output_path = ROOT / record["output"]
            protected_paths.append(output_path)
            receipt_identity = identity(receipt_path)
            output_identity = identity(output_path)
            contained = (
                receipt_path.resolve().parent == writer.RECEIPT_ROOT
                and output_path.resolve().parent == recovery.FINAL_ROOT
            )
            exact_stat = (
                receipt_identity["regular_file"] and output_identity["regular_file"]
                and not receipt_identity["symlink"] and not output_identity["symlink"]
                and receipt_identity["mode"] == output_identity["mode"] == "0o600"
                and receipt_identity["nlink"] == output_identity["nlink"] == 1
                and receipt_identity["uid"] == output_identity["uid"] == os.getuid()
                and receipt_identity["gid"] == output_identity["gid"] == os.getgid()
                and [output_identity["device"], output_identity["inode"]] == record["owned_inode_token"]
                and output_identity["sha256"] == record["output_sha256"]
            )
            inode_tokens.extend([
                [receipt_identity["device"], receipt_identity["inode"]],
                [output_identity["device"], output_identity["inode"]],
            ])
            pair_rows.append({
                "receipt": str(receipt_path.relative_to(ROOT)),
                "output": record["output"],
                "restart_binding_valid": True,
                "contained_in_exact_roots": contained,
                "stat_contract": exact_stat,
                "receipt_identity": receipt_identity,
                "output_identity": output_identity,
            })
            if not contained or not exact_stat:
                failures.append("PAIR_EXACT_ROOT_OR_STAT_MISMATCH")
        except Exception as exc:
            pair_rows.append({
                "receipt": str(receipt_path.relative_to(ROOT)),
                "restart_binding_valid": False,
                "error": type(exc).__name__,
            })
            failures.append("PAIR_RESTART_BINDING_INVALID")

    if len(pair_rows) != 3 or sum(row["restart_binding_valid"] for row in pair_rows) != 3:
        failures.append("PAIR_COUNT_NOT_3_OF_3")
    unique_inodes = len(inode_tokens) == 6 and len({tuple(token) for token in inode_tokens}) == 6
    if not unique_inodes:
        failures.append("INODES_NOT_6_OF_6_UNIQUE")

    roots_before = [identity(writer.RECEIPT_ROOT), identity(recovery.FINAL_ROOT)]
    protected_before = [identity(path) for path in protected_paths]
    v29_snapshot_exact = (
        roots_before == v29.get("root_identity_after")
        and protected_before == v29.get("protected_pair_identity_after")
    )
    if not v29_snapshot_exact:
        failures.append("LIVE_IDENTITY_DRIFT_FROM_V29_AFTER_SNAPSHOT")

    allowlist = json.loads(ALLOWLIST.read_text())
    entries = allowlist.get("entries", [])
    allowlist_valid = (
        allowlist.get("status") == "FAIL_CLOSED_NON_ADMITTED_LOCAL_HARNESS_EVIDENCE"
        and len(entries) == 1
        and entries[0].get("path")
        == "qa/e40_preproduction_20260808/u29c_v20_post_link_recovery_final_output_v1/E40_U29C_V23_RECOVERED_WITH_RECEIPT_GATE_V1.json"
        and entries[0].get("sha256")
        == "02e40965b21b8e29a03681df8de612aff2d4ce9747ecfc868d7d7601983fe83b"
        and digest(ROOT / entries[0]["path"]) == entries[0]["sha256"]
    )
    if not allowlist_valid:
        failures.append("ALLOWLIST_NOT_EXACT_NON_ADMITTED")

    for receipt_path in receipt_paths:
        writer.validate_restart(receipt_path)
    protected_after = [identity(path) for path in protected_paths]
    roots_after = [identity(writer.RECEIPT_ROOT), identity(recovery.FINAL_ROOT)]
    pins_after = [identity(path) for path, _ in pins]
    if protected_before != protected_after:
        failures.append("PAIR_IDENTITY_MUTATION")
    if roots_before != roots_after:
        failures.append("ROOT_IDENTITY_MUTATION")
    if pins_before != pins_after:
        failures.append("PIN_IDENTITY_MUTATION")

    status = PASS_STATUS if not failures else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29c.v30.pinned_filesystem_stat_audit_regression_matrix.v1",
        "episode": "E40",
        "unit_id": "U29C",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "execution_permitted": False,
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "pins_before": pins_before,
        "pin_expected_sha256": [expected for _, expected in pins],
        "pin_match_count": sum(pin_matches),
        "pins_after": pins_after,
        "v29_authority_valid": v29_authority_valid,
        "receipt_output_pair_count": len(pair_rows),
        "valid_pair_count": sum(row["restart_binding_valid"] for row in pair_rows),
        "pairs": pair_rows,
        "inode_token_count": len(inode_tokens),
        "unique_inode_token_count": len({tuple(token) for token in inode_tokens}),
        "all_receipt_output_inodes_unique": unique_inodes,
        "v29_after_snapshot_exact": v29_snapshot_exact,
        "root_identity_before": roots_before,
        "root_identity_after": roots_after,
        "protected_pair_identity_before": protected_before,
        "protected_pair_identity_after": protected_after,
        "exact_allowlist": {row["path"]: row["sha256"] for row in entries},
        "exact_allowlist_valid_non_admitted": allowlist_valid,
        "substitution_negatives": negatives,
        "substitution_negative_count": sum(row["rejected_before_verification"] for row in negatives),
        "admission_closed": True,
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
        "next_action": "Register V31 receipt/output directory-entry inventory integrity audit.",
    }
    fd = os.open(REPORT, base.create_flags(), 0o600)
    base.write_all(fd, (json.dumps(payload, indent=2) + "\n").encode())
    os.fsync(fd)
    os.close(fd)
    print(json.dumps({
        "status": status,
        "pairs": sum(row["restart_binding_valid"] for row in pair_rows),
        "unique_inodes": len({tuple(token) for token in inode_tokens}),
        "v29_snapshot_exact": v29_snapshot_exact,
        "substitution_negatives": sum(row["rejected_before_verification"] for row in negatives),
        "failures": failures,
    }))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
