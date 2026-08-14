#!/usr/bin/env python3
"""V31 read-only closed-set inventory of receipt and recovery-output roots."""
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

V30_RUNNER = ROOT / "tools/run_e40_u29c_v30_pinned_filesystem_stat_audit_regression.py"
V30_RUNNER_SHA = "177034e363e91b8ff26990f9c164213b7658509ca31f6bee55a016a832c55958"
V30_MATRIX = ROOT / "qa/e40_preproduction_20260808/u29c_v30_pinned_filesystem_stat_regression_v1/E40_U29C_V30_PINNED_FILESYSTEM_STAT_AUDIT_REGRESSION_MATRIX_V1.json"
V30_MATRIX_SHA = "106564e7dbfa6b54582e2f5f77d7a2ca0f6e986b3a64299e069144bb6ebe97ef"
V31_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v31_directory_entry_inventory_v1/E40_U29C_V31_RECEIPT_OUTPUT_DIRECTORY_ENTRY_INVENTORY_SPEC_V1.json"
V31_SPEC_SHA = "4d33685a2c2e144ec67db5e01a8067778098c9963608081e91ad2a7f734b879d"
REPORT = V31_SPEC.parent / "E40_U29C_V31_RECEIPT_OUTPUT_DIRECTORY_ENTRY_INVENTORY_AUDIT_V1.json"
PASS_STATUS = "PASS_CLOSED_SET_3_RECEIPTS_14_OUTPUTS_ALL_ENTRIES_CLASSIFIED_NO_MUTATION_NO_SUBMIT"

EXPECTED_RECEIPTS = {
    "E40_U29C_V23_RECOVERED_WITH_RECEIPT_GATE_V2.recovered-success-receipt.json": "b1fa9825cb941320169e63f48d39c6dfebf352795b5c923471c675fe9b349201",
    "E40_U29C_V23_RECOVERED_WITH_RECEIPT_GATE_V3.recovered-success-receipt.json": "0420957eca9939f16ce5b58ceb220f560d384f506cb8449700467e19cafd55e2",
    "E40_U29C_V24_PINNED_RECOVERED_RECEIPT_GATE_V1.recovered-success-receipt.json": "0c5a1f99d1cc72e47ef019c87b0454d4412d13898a533ae58b594d121369e4c6",
}

EXPECTED_OUTPUTS = {
    "E40_U29C_V20_CANONICAL_RECOVERY_GATE_V1.json": ("DOCUMENTED_LOCAL_HARNESS_EVIDENCE", "20d85d62c140c9a9f8321182f8d77e79fa7381d0358fb67622d88203093577c7"),
    "E40_U29C_V20_READER_SAFE_GATE_V1.json": ("DOCUMENTED_LOCAL_HARNESS_EVIDENCE", "c9ac2c1edafe63bd6dbc479d79f38fdfbedb0f004ba73fe38fcd44fd5e13d293"),
    "E40_U29C_V20_SHARED_RECOVERY_CONTENTION_GATE_V1.json": ("DOCUMENTED_LOCAL_HARNESS_EVIDENCE", "894fd7be8edcde934c25153420e86f926b6a19b815c4acaf87ddddb2fd4a7739"),
    "E40_U29C_V21_PINNED_READER_GATE_V1.json": ("DOCUMENTED_LOCAL_HARNESS_EVIDENCE", "54d19b55f69699e93161160dc336932e2dadc7c6d15fe1c533771bd3fc380de4"),
    "E40_U29C_V21_PINNED_SHARED_CONTENTION_GATE_V1.json": ("DOCUMENTED_LOCAL_HARNESS_EVIDENCE", "2b5d050a3ecc2d7bb1303af4574f71702603f2b0d226eab3d562989762201ce0"),
    "E40_U29C_V23_COMPETITOR_PRESERVED_GATE_V3.json": ("DOCUMENTED_LOCAL_HARNESS_EVIDENCE", "abe96c04f521600b75d71e84fc4aba1c5d23d5a1161dc0d7e803f54d47ed5e00"),
    "E40_U29C_V23_NORMAL_NO_RECEIPT_GATE_V1.json": ("DOCUMENTED_LOCAL_HARNESS_EVIDENCE", "a33cfbd50f41b07ffa4c265028d671fe8d39919a2522bfc8fdf94aaada562398"),
    "E40_U29C_V23_NORMAL_NO_RECEIPT_GATE_V2.json": ("DOCUMENTED_LOCAL_HARNESS_EVIDENCE", "232048b8288a5e52ea9e6d47754590ad8c50ef16ea783bf4d8a1d16438bdf225"),
    "E40_U29C_V23_NORMAL_NO_RECEIPT_GATE_V3.json": ("DOCUMENTED_LOCAL_HARNESS_EVIDENCE", "86cc8015344c3cf56cb6d0c39662ec38c7428ba335bfa41427725ea523e81a4a"),
    "E40_U29C_V23_RECOVERED_WITH_RECEIPT_GATE_V1.json": ("HISTORICAL_NON_ADMITTED_LOCAL_HARNESS_EVIDENCE", "02e40965b21b8e29a03681df8de612aff2d4ce9747ecfc868d7d7601983fe83b"),
    "E40_U29C_V23_RECOVERED_WITH_RECEIPT_GATE_V2.json": ("BOUND_CURRENT_RECOVERED_EVIDENCE", "d5a9083b9c05612c532ca439b7ecf37ea239ab1374ee51df52b343d4a521bb88"),
    "E40_U29C_V23_RECOVERED_WITH_RECEIPT_GATE_V3.json": ("BOUND_CURRENT_RECOVERED_EVIDENCE", "4c8c5234ab736c160800709304e46356e878acfc6d6ed8b785612af39ec9040f"),
    "E40_U29C_V24_PINNED_COMPETITOR_GATE_V1.json": ("DOCUMENTED_LOCAL_HARNESS_EVIDENCE", "b85d3b4964351f3121909a5b6249c439aff4b24f7ca5ab2a84cc57bbaa6d2373"),
    "E40_U29C_V24_PINNED_RECOVERED_RECEIPT_GATE_V1.json": ("BOUND_CURRENT_RECOVERED_EVIDENCE", "1a30931186974b76bc6ac02fa2d02e57b098b00cb26927b2881f462a3839d50e"),
}


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
    for flag in ("--receipt-root", "--output-root", "--classification"):
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
            "rejected_before_inventory": proc.returncode == 2,
            "report_created": REPORT.exists(),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inventory fixed roots against a compiled closed set; substitutions are forbidden.",
        allow_abbrev=False,
    )
    parser.parse_args()
    if REPORT.exists():
        raise SystemExit("REPORT_ALREADY_EXISTS")

    failures: list[str] = []
    pins = [(V30_RUNNER, V30_RUNNER_SHA), (V30_MATRIX, V30_MATRIX_SHA), (V31_SPEC, V31_SPEC_SHA)]
    pins_before = [identity(path) for path, _ in pins]
    pin_matches = [row["sha256"] == expected for row, (_, expected) in zip(pins_before, pins)]
    if not all(pin_matches):
        print(json.dumps({"status": "FAIL_CLOSED_PIN_MISMATCH", "pin_matches": pin_matches}))
        return 1

    negatives = substitution_negatives()
    if REPORT.exists() or not all(row["rejected_before_inventory"] and not row["report_created"] for row in negatives):
        failures.append("SUBSTITUTION_NOT_REJECTED_BEFORE_INVENTORY")

    roots = [writer.RECEIPT_ROOT, recovery.FINAL_ROOT]
    roots_before = [identity(path) for path in roots]
    observed_receipt_paths = sorted(writer.RECEIPT_ROOT.iterdir())
    observed_output_paths = sorted(recovery.FINAL_ROOT.iterdir())
    all_paths = observed_receipt_paths + observed_output_paths
    entries_before = [identity(path) for path in all_paths]

    receipt_rows = []
    for path in observed_receipt_paths:
        row = identity(path)
        expected_sha = EXPECTED_RECEIPTS.get(path.name)
        classification = "BOUND_CURRENT_RECEIPT" if expected_sha else "FORBIDDEN_UNEXPECTED_RECEIPT"
        exact = (
            expected_sha is not None
            and row["sha256"] == expected_sha
            and row["regular_file"]
            and not row["symlink"]
            and not path.name.startswith(".")
            and row["mode"] == "0o600"
            and row["nlink"] == 1
        )
        receipt_rows.append({**row, "classification": classification, "expected_sha256": expected_sha, "exact": exact})
        if not exact:
            failures.append("RECEIPT_ENTRY_NOT_EXACT_CLOSED_SET")

    output_rows = []
    for path in observed_output_paths:
        row = identity(path)
        expected = EXPECTED_OUTPUTS.get(path.name)
        classification, expected_sha = expected if expected else ("FORBIDDEN_UNCLASSIFIED_OUTPUT", None)
        exact = (
            expected is not None
            and row["sha256"] == expected_sha
            and row["regular_file"]
            and not row["symlink"]
            and not path.name.startswith(".")
            and row["mode"] == "0o600"
            and row["nlink"] == 1
        )
        output_rows.append({**row, "classification": classification, "expected_sha256": expected_sha, "exact": exact})
        if not exact:
            failures.append("OUTPUT_ENTRY_NOT_EXACT_CLOSED_SET")

    receipt_names = {path.name for path in observed_receipt_paths}
    output_names = {path.name for path in observed_output_paths}
    closed_set_exact = receipt_names == set(EXPECTED_RECEIPTS) and output_names == set(EXPECTED_OUTPUTS)
    if not closed_set_exact:
        failures.append("DIRECTORY_ENTRY_CLOSED_SET_MISMATCH")

    bound_outputs = {name for name, (kind, _) in EXPECTED_OUTPUTS.items() if kind == "BOUND_CURRENT_RECOVERED_EVIDENCE"}
    restart_outputs = set()
    for receipt_path in observed_receipt_paths:
        record = writer.validate_restart(receipt_path)
        restart_outputs.add(Path(record["output"]).name)
    current_binding_exact = restart_outputs == bound_outputs and len(restart_outputs) == 3
    if not current_binding_exact:
        failures.append("CURRENT_BINDING_SET_NOT_EXACT_3_OF_3")

    category_counts: dict[str, int] = {}
    for row in receipt_rows + output_rows:
        category_counts[row["classification"]] = category_counts.get(row["classification"], 0) + 1
    expected_counts = {
        "BOUND_CURRENT_RECEIPT": 3,
        "BOUND_CURRENT_RECOVERED_EVIDENCE": 3,
        "HISTORICAL_NON_ADMITTED_LOCAL_HARNESS_EVIDENCE": 1,
        "DOCUMENTED_LOCAL_HARNESS_EVIDENCE": 10,
    }
    if category_counts != expected_counts:
        failures.append("CLASSIFICATION_COUNTS_MISMATCH")

    entries_after = [identity(path) for path in all_paths]
    roots_after = [identity(path) for path in roots]
    pins_after = [identity(path) for path, _ in pins]
    if entries_before != entries_after:
        failures.append("DIRECTORY_ENTRY_IDENTITY_MUTATION")
    if roots_before != roots_after:
        failures.append("ROOT_IDENTITY_MUTATION")
    if pins_before != pins_after:
        failures.append("PIN_IDENTITY_MUTATION")

    status = PASS_STATUS if not failures else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29c.v31.receipt_output_directory_entry_inventory_audit.v1",
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
        "root_identity_before": roots_before,
        "root_identity_after": roots_after,
        "receipt_entry_count": len(receipt_rows),
        "output_entry_count": len(output_rows),
        "total_entry_count": len(receipt_rows) + len(output_rows),
        "receipt_entries": receipt_rows,
        "output_entries": output_rows,
        "classification_counts": category_counts,
        "expected_classification_counts": expected_counts,
        "closed_set_exact": closed_set_exact,
        "current_binding_set_exact_3_of_3": current_binding_exact,
        "entry_identity_before": entries_before,
        "entry_identity_after": entries_after,
        "hidden_entry_count": sum(path.name.startswith(".") for path in all_paths),
        "symlink_entry_count": sum(row["symlink"] for row in receipt_rows + output_rows),
        "nonregular_entry_count": sum(not row["regular_file"] for row in receipt_rows + output_rows),
        "unclassified_entry_count": sum(row["classification"].startswith("FORBIDDEN_") for row in receipt_rows + output_rows),
        "substitution_negatives": negatives,
        "substitution_negative_count": sum(row["rejected_before_inventory"] for row in negatives),
        "admission_closed": True,
        "blind_replay_allowed": False,
        "failures": failures,
        "side_effects": {"provider_calls": 0, "transactions": 0, "credits": 0, "retries": 0, "agentcut": 0, "assembly": 0},
        "next_action": "Register V32 pinned closed-set directory inventory regression.",
    }
    fd = os.open(REPORT, base.create_flags(), 0o600)
    base.write_all(fd, (json.dumps(payload, indent=2) + "\n").encode())
    os.fsync(fd)
    os.close(fd)
    print(json.dumps({
        "status": status,
        "receipts": len(receipt_rows),
        "outputs": len(output_rows),
        "classified": len(receipt_rows) + len(output_rows),
        "substitution_negatives": sum(row["rejected_before_inventory"] for row in negatives),
        "failures": failures,
    }))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
