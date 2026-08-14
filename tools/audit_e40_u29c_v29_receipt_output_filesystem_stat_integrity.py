#!/usr/bin/env python3
"""Read-only V29 filesystem-stat integrity audit for persisted receipt/output pairs."""
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

V28_RUNNER = ROOT / "tools/run_e40_u29c_v28_pinned_receipt_chain_regression.py"
V28_RUNNER_SHA = "352ea66d6287cd01e5fdd2286c9177f0d07ce03a5aba2ab88adc85bb366cd26e"
V28_MATRIX = ROOT / "qa/e40_preproduction_20260808/u29c_v28_pinned_chain_regression_v1/E40_U29C_V28_PINNED_RECEIPT_CHAIN_REGRESSION_MATRIX_V1.json"
V28_MATRIX_SHA = "a8f2c81ea0e27fc777430da5f15ac6bc3745e43d6c005b86a2913c0859e7697c"
V29_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v29_receipt_filesystem_stat_audit_v1/E40_U29C_V29_RECEIPT_OUTPUT_FILESYSTEM_STAT_INTEGRITY_SPEC_V1.json"
V29_SPEC_SHA = "6a1eb41a333bf7f4d7ea04f5a4c5ed084e4100bbb4e7ca3c046b2fbc93e7ba48"
ALLOWLIST = ROOT / "qa/e40_preproduction_20260808/u29c_v26_pinned_receipt_inventory_v1/E40_U29C_V26_HISTORICAL_UNPAIRED_OUTPUT_ALLOWLIST_V1.json"
ALLOWLIST_SHA = "5e25fbc2c9aa33865e4679b2bebc330522cf28925446daf6c684859fa60ab863"
REPORT = V29_SPEC.parent / "E40_U29C_V29_RECEIPT_OUTPUT_FILESYSTEM_STAT_INTEGRITY_AUDIT_V1.json"
PASS_STATUS = "PASS_3_OF_3_RECEIPT_OUTPUT_STAT_IDENTITIES_EXACT_ROOTS_UNIQUE_INODES_NO_MUTATION_NO_SUBMIT"


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
    for flag in ("--receipt-root", "--output-root", "--allowlist"):
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
            "rejected_before_inspection": proc.returncode == 2,
            "report_created": REPORT.exists(),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit fixed receipt/output roots; caller path substitution is forbidden.",
        allow_abbrev=False,
    )
    parser.parse_args()
    if REPORT.exists():
        raise SystemExit("REPORT_ALREADY_EXISTS")

    failures: list[str] = []
    pins = [
        (V28_RUNNER, V28_RUNNER_SHA),
        (V28_MATRIX, V28_MATRIX_SHA),
        (V29_SPEC, V29_SPEC_SHA),
        (ALLOWLIST, ALLOWLIST_SHA),
    ]
    pins_before = [identity(path) for path, _ in pins]
    pin_matches = [row["sha256"] == expected for row, (_, expected) in zip(pins_before, pins)]
    if not all(pin_matches):
        print(json.dumps({"status": "FAIL_CLOSED_PIN_MISMATCH", "pin_matches": pin_matches}))
        return 1

    negatives = substitution_negatives()
    if REPORT.exists() or not all(row["rejected_before_inspection"] and not row["report_created"] for row in negatives):
        failures.append("SUBSTITUTION_NOT_REJECTED_BEFORE_INSPECTION")

    receipt_root = writer.RECEIPT_ROOT
    output_root = recovery.FINAL_ROOT
    root_before = [identity(receipt_root), identity(output_root)]
    root_contract = (
        receipt_root.resolve() == receipt_root
        and output_root.resolve() == output_root
        and receipt_root.parent.resolve() == receipt_root.parent
        and output_root.parent.resolve() == output_root.parent
        and all(row["directory"] and not row["symlink"] and row["mode"] == "0o700" for row in root_before)
        and root_before[0]["uid"] == root_before[1]["uid"] == os.getuid()
        and root_before[0]["gid"] == root_before[1]["gid"] == os.getgid()
    )
    if not root_contract:
        failures.append("ROOT_IDENTITY_OR_PERMISSION_CONTRACT_MISMATCH")

    receipt_paths = sorted(receipt_root.glob("*.recovered-success-receipt.json"))
    protected_paths: list[Path] = []
    pair_rows = []
    for receipt_path in receipt_paths:
        protected_paths.append(receipt_path)
        try:
            record = writer.validate_restart(receipt_path)
            output_path = ROOT / record["output"]
            protected_paths.append(output_path)
            receipt_stat = identity(receipt_path)
            output_stat = identity(output_path)
            contained = (
                receipt_path.parent.resolve() == receipt_root
                and output_path.parent.resolve() == output_root
                and receipt_path.resolve().parent == receipt_root
                and output_path.resolve().parent == output_root
            )
            stat_contract = (
                receipt_stat["regular_file"] and not receipt_stat["symlink"]
                and output_stat["regular_file"] and not output_stat["symlink"]
                and receipt_stat["mode"] == output_stat["mode"] == "0o600"
                and receipt_stat["nlink"] == output_stat["nlink"] == record["output_link_count"] == 1
                and receipt_stat["uid"] == output_stat["uid"] == root_before[0]["uid"]
                and receipt_stat["gid"] == output_stat["gid"] == root_before[0]["gid"]
                and [output_stat["device"], output_stat["inode"]] == record["owned_inode_token"]
                and output_stat["sha256"] == record["output_sha256"]
            )
            pair_rows.append({
                "receipt": str(receipt_path.relative_to(ROOT)),
                "output": record["output"],
                "contained_in_exact_roots": contained,
                "stat_contract": stat_contract,
                "restart_binding_valid": True,
                "receipt_identity": receipt_stat,
                "output_identity": output_stat,
            })
            if not contained:
                failures.append("PAIR_ROOT_CONTAINMENT_MISMATCH")
            if not stat_contract:
                failures.append("PAIR_STAT_CONTRACT_MISMATCH")
        except Exception as exc:  # fail closed and record only exception class
            pair_rows.append({
                "receipt": str(receipt_path.relative_to(ROOT)),
                "restart_binding_valid": False,
                "error": type(exc).__name__,
            })
            failures.append("PAIR_RESTART_BINDING_INVALID")

    if len(pair_rows) != 3 or sum(row["restart_binding_valid"] for row in pair_rows) != 3:
        failures.append("PAIR_COUNT_NOT_3_OF_3")

    inode_tokens = [
        (row["device"], row["inode"])
        for pair in pair_rows if pair.get("restart_binding_valid")
        for row in (pair["receipt_identity"], pair["output_identity"])
    ]
    unique_inodes = len(inode_tokens) == 6 and len(set(inode_tokens)) == 6
    if not unique_inodes:
        failures.append("RECEIPT_OUTPUT_INODES_NOT_6_OF_6_UNIQUE")

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
        failures.append("EXACT_NON_ADMITTED_ALLOWLIST_INVALID")

    protected_before = [identity(path) for path in protected_paths]
    # Repeat restart validation between identity snapshots; this must remain read-only.
    restart_repeat_count = 0
    for receipt_path in receipt_paths:
        writer.validate_restart(receipt_path)
        restart_repeat_count += 1
    protected_after = [identity(path) for path in protected_paths]
    root_after = [identity(receipt_root), identity(output_root)]
    pins_after = [identity(path) for path, _ in pins]
    if protected_before != protected_after:
        failures.append("PAIR_IDENTITY_MUTATION")
    if root_before != root_after:
        failures.append("ROOT_IDENTITY_MUTATION")
    if pins_before != pins_after:
        failures.append("PIN_IDENTITY_MUTATION")

    status = PASS_STATUS if not failures else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29c.v29.receipt_output_filesystem_stat_integrity_audit.v1",
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
        "root_identity_before": root_before,
        "root_identity_after": root_after,
        "root_contract_valid": root_contract,
        "receipt_output_pair_count": len(pair_rows),
        "valid_pair_count": sum(row["restart_binding_valid"] for row in pair_rows),
        "pairs": pair_rows,
        "inode_token_count": len(inode_tokens),
        "unique_inode_token_count": len(set(inode_tokens)),
        "all_receipt_output_inodes_unique": unique_inodes,
        "protected_pair_identity_before": protected_before,
        "protected_pair_identity_after": protected_after,
        "restart_repeat_count": restart_repeat_count,
        "exact_allowlist": {row["path"]: row["sha256"] for row in entries},
        "exact_allowlist_valid_non_admitted": allowlist_valid,
        "substitution_negatives": negatives,
        "substitution_negative_count": sum(row["rejected_before_inspection"] for row in negatives),
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
        "next_action": "Register V30 pinned filesystem-stat audit regression.",
    }
    fd = os.open(REPORT, base.create_flags(), 0o600)
    base.write_all(fd, (json.dumps(payload, indent=2) + "\n").encode())
    os.fsync(fd)
    os.close(fd)
    print(json.dumps({
        "status": status,
        "pairs": sum(row["restart_binding_valid"] for row in pair_rows),
        "unique_inodes": len(set(inode_tokens)),
        "substitution_negatives": sum(row["rejected_before_inspection"] for row in negatives),
        "failures": failures,
    }))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
