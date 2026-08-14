#!/usr/bin/env python3
"""Wrap V20 recovery with an atomic, persisted owned-inode receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base  # noqa: E402
import run_e40_u29c_v20_post_link_recovery_publish_gate as recovery  # noqa: E402


V20_WRITER = ROOT / "tools/run_e40_u29c_v20_post_link_recovery_publish_gate.py"
V20_WRITER_SHA256 = "6b61cf37134e1a3a2fa16f95140db82efaf5fe164a52e5373ed324890cde227e"
V22_AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v22_recovery_receipt_crash_boundary_audit_v1/E40_U29C_V22_RECOVERED_SUCCESS_RECEIPT_AND_CRASH_BOUNDARY_AUDIT_V1.json"
V22_AUDIT_SHA256 = "09943bbd534f3f69567f98609bbb2a86ca7740062c8e5b036e2321c46725ed85"
V23_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v23_persisted_recovery_receipt_writer_v1/E40_U29C_V23_PERSISTED_OWNED_INODE_RECOVERY_RECEIPT_WRITER_SPEC_V1.json"
V23_SPEC_SHA256 = "0b23cb7fa1ec9e8a9963472e14dcdca0fc31d953957a08b838302cce5fd7c7a0"
RECEIPT_ROOT = recovery.QA_EPISODE_ROOT / "u29c_v23_persisted_recovery_receipts_v1"
WRITER_SHA256 = "SELF_SHA_BOUND_BY_MATRIX"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_pins() -> None:
    for path, expected, code in [
        (V20_WRITER, V20_WRITER_SHA256, "PINNED_V20_WRITER_SHA_MISMATCH"),
        (V22_AUDIT, V22_AUDIT_SHA256, "PINNED_V22_AUDIT_SHA_MISMATCH"),
        (V23_SPEC, V23_SPEC_SHA256, "PINNED_V23_SPEC_SHA_MISMATCH"),
    ]:
        if digest(path) != expected:
            raise base.GateError(code)


def receipt_name(output_name: str) -> str:
    if not base.SAFE_NAME.fullmatch(output_name):
        raise base.GateError("OUTPUT_NAME_MUST_BE_SAFE_JSON_BASENAME")
    return output_name[:-5] + ".recovered-success-receipt.json"


def receipt_payload(output: Path, token: tuple[int, int], cause: str, validator_status: str) -> dict[str, Any]:
    value = os.stat(output, follow_symlinks=False)
    payload = output.read_bytes()
    base.validate_report_bytes(payload)
    if base.identity(value) != token or value.st_nlink != 1:
        raise base.GateError("RECEIPT_OUTPUT_OWNERSHIP_OR_LINK_COUNT_MISMATCH")
    return {
        "schema": "qingshan.e40.u29c.v23.persisted_recovered_success_receipt.v1",
        "status": "RECOVERED_SUCCESS_EXACT_OWNED_INODE_PERSISTED",
        "output": str(output.relative_to(ROOT)),
        "output_sha256": hashlib.sha256(payload).hexdigest(),
        "owned_inode_token": [token[0], token[1]],
        "recovery_cause": cause,
        "validator_status": validator_status,
        "writer_sha256": digest(Path(__file__).resolve()),
        "output_link_count": value.st_nlink,
        "execution_permitted": False,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
    }


def persist_receipt(binding: base.RootBinding, name: str, payload: dict[str, Any]) -> Path:
    public = receipt_name(name)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    hidden_name = f".u29c-v23-receipt-hidden-{secrets.token_hex(12)}.json"
    fd = os.open(hidden_name, base.create_flags(), 0o600, dir_fd=binding.fd)
    token = base.identity(os.fstat(fd))
    linked = False
    try:
        base.write_all(fd, data)
        os.fsync(fd)
        if base.entry_identity(binding, hidden_name) != token or os.fstat(fd).st_nlink != 1:
            raise base.GateError("RECEIPT_HIDDEN_IDENTITY_INVALID")
        try:
            os.link(hidden_name, public, src_dir_fd=binding.fd, dst_dir_fd=binding.fd, follow_symlinks=False)
        except FileExistsError as exc:
            raise base.GateError("RECOVERY_RECEIPT_TARGET_EXISTS") from exc
        linked = True
        os.fsync(binding.fd)
        value = os.stat(public, dir_fd=binding.fd, follow_symlinks=False)
        if base.identity(value) != token or value.st_nlink != 2:
            raise base.GateError("RECEIPT_PUBLICATION_IDENTITY_INVALID")
        os.unlink(hidden_name, dir_fd=binding.fd)
        os.fsync(binding.fd)
        return binding.path / public
    except Exception:
        if base.entry_identity(binding, hidden_name) == token:
            os.unlink(hidden_name, dir_fd=binding.fd)
            os.fsync(binding.fd)
        raise
    finally:
        os.close(fd)


def validate_restart(receipt: Path, output_root: Path = recovery.FINAL_ROOT) -> dict[str, Any]:
    try:
        record = json.loads(receipt.read_text(encoding="utf-8"))
        required = ["output", "output_sha256", "owned_inode_token", "recovery_cause", "validator_status", "writer_sha256", "output_link_count"]
        if any(key not in record for key in required):
            raise base.GateError("RECOVERY_RECEIPT_REQUIRED_FIELD_MISSING")
        output = ROOT / record["output"]
        if output.parent != output_root:
            raise base.GateError("RECOVERY_RECEIPT_OUTPUT_ROOT_MISMATCH")
        payload = output.read_bytes()
        value = os.stat(output, follow_symlinks=False)
        base.validate_report_bytes(payload)
        checks = (
            hashlib.sha256(payload).hexdigest() == record["output_sha256"]
            and [value.st_dev, value.st_ino] == record["owned_inode_token"]
            and value.st_nlink == record["output_link_count"] == 1
            and record["writer_sha256"] == digest(Path(__file__).resolve())
            and record["validator_status"] == "PASS_EXPECTED_FAIL_CLOSED_NO_SUBMIT"
            and record["status"] == "RECOVERED_SUCCESS_EXACT_OWNED_INODE_PERSISTED"
        )
        if not checks:
            raise base.GateError("RECOVERY_RECEIPT_RESTART_BINDING_MISMATCH")
        return record
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise base.GateError("RECOVERY_RECEIPT_RESTART_VALIDATION_FAILED") from exc


def execute(output_name: str) -> dict[str, Any]:
    verify_pins()
    result = recovery.execute(output_name)
    if not result.get("post_link_recovered"):
        return {**result, "receipt_required": False, "receipt": None, "receipt_sha256": None}
    output = Path(str(result["output"]))
    value = os.stat(output, follow_symlinks=False)
    token = base.identity(value)
    record = receipt_payload(output, token, str(result["recovery_cause"]), str(result["validator_status"]))
    receipt_root = base.open_bound_root(RECEIPT_ROOT)
    try:
        receipt = persist_receipt(receipt_root, output_name, record)
    finally:
        os.close(receipt_root.fd)
    validate_restart(receipt)
    return {
        **result,
        "wrapper_status": "PASS_PERSISTED_OWNED_INODE_RECOVERY_RECEIPT_NO_SUBMIT",
        "receipt_required": True,
        "receipt": str(receipt),
        "receipt_sha256": digest(receipt),
        "owned_inode_token": list(token),
    }


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--output-name", required=True)
    args = parser.parse_args()
    try:
        result = execute(args.output_name)
    except base.GateError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
