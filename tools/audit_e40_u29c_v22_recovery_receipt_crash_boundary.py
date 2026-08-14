#!/usr/bin/env python3
"""Audit V20 recovered-success receipts and restart crash boundaries."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base  # noqa: E402
import run_e40_u29c_v20_post_link_recovery_publish_gate as writer  # noqa: E402


WRITER = ROOT / "tools/run_e40_u29c_v20_post_link_recovery_publish_gate.py"
WRITER_SHA256 = "6b61cf37134e1a3a2fa16f95140db82efaf5fe164a52e5373ed324890cde227e"
V21_INVOKER = ROOT / "tools/run_e40_u29c_v21_pinned_post_link_recovery_regression.py"
V21_INVOKER_SHA256 = "1569d2575d4654c780641484b2d7b75f937fdb1b003696e02ddff4313c7ec8f4"
V21_MATRIX = ROOT / "qa/e40_preproduction_20260808/u29c_v21_pinned_recovery_regression_v1/E40_U29C_V21_PINNED_RECOVERY_REGRESSION_MATRIX_V1.json"
V21_MATRIX_SHA256 = "17ca4ebcf63a0ffdb5901cc25f371516680819b1f0df1b3a1b4abeb3ffd0dfb2"
V22_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v22_recovery_receipt_crash_boundary_audit_v1/E40_U29C_V22_RECOVERED_SUCCESS_RECEIPT_AND_CRASH_BOUNDARY_AUDIT_SPEC_V1.json"
V22_SPEC_SHA256 = "6129c219d353c646763e62954272c7182a2cc46fdf5c9689a94623d8079e6c32"
CANONICAL = writer.FINAL_ROOT / "E40_U29C_V20_CANONICAL_RECOVERY_GATE_V1.json"
REPORT = ROOT / "qa/e40_preproduction_20260808/u29c_v22_recovery_receipt_crash_boundary_audit_v1/E40_U29C_V22_RECOVERED_SUCCESS_RECEIPT_AND_CRASH_BOUNDARY_AUDIT_V1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        size = os.write(fd, view)
        if size <= 0:
            raise RuntimeError("WRITE_FAILED")
        view = view[size:]


def static_receipt_case() -> dict[str, Any]:
    source = WRITER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    execute_source = ""
    publish_source = ""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "execute":
            execute_source = ast.get_source_segment(source, node) or ""
        if isinstance(node, ast.FunctionDef) and node.name == "publish_complete_payload":
            publish_source = ast.get_source_segment(source, node) or ""
    bindings = {
        "exact_public_output_path": '"output"' in execute_source,
        "exact_public_output_sha256": '"output_sha256"' in execute_source,
        "original_exception_class": '"recovery_cause"' in execute_source and "type(exc).__name__" in publish_source,
        "fail_closed_validator_status": '"validator_status"' in execute_source,
        "owned_inode_token": '"owned_inode_token"' in execute_source,
    }
    return {
        "case_id": "STATIC_RECOVERED_SUCCESS_RECEIPT_BINDINGS",
        "passed": bindings == {
            "exact_public_output_path": True,
            "exact_public_output_sha256": True,
            "original_exception_class": True,
            "fail_closed_validator_status": True,
            "owned_inode_token": False,
        },
        "bindings": bindings,
        "gap_found": not bindings["owned_inode_token"],
        "gap_code": "RECOVERED_SUCCESS_RECEIPT_OMITS_OWNED_INODE_TOKEN",
    }


def dynamic_recovered_receipt_case(payload: bytes) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=".u29c-v22-receipt-", dir=writer.QA_EPISODE_ROOT) as temporary:
        path = Path(temporary)
        binding = base.open_bound_root(path)
        original_fsync = writer.os.fsync
        fired = False

        def inject(fd: int) -> None:
            nonlocal fired
            if fd == binding.fd and not fired:
                fired = True
                raise OSError("V22_INJECTED_POST_LINK_FSYNC")
            original_fsync(fd)

        writer.os.fsync = inject
        try:
            report, recovered, cause = writer.publish_complete_payload(binding, "public.json", payload)
        finally:
            writer.os.fsync = original_fsync
            os.close(binding.fd)
        public = path / "public.json"
        value = os.stat(public, follow_symlinks=False)
        simulated_receipt = {
            "output": str(public),
            "output_sha256": digest(public),
            "validator_status": report["status"],
            "post_link_recovered": recovered,
            "recovery_cause": cause,
        }
        required = ["output", "output_sha256", "owned_inode_token", "recovery_cause", "validator_status"]
        missing = [key for key in required if key not in simulated_receipt]
        return {
            "case_id": "DYNAMIC_RECOVERED_SUCCESS_RECEIPT_GAP_REPRODUCTION",
            "passed": fired and recovered and cause == "OSError" and missing == ["owned_inode_token"] and value.st_nlink == 1,
            "simulated_receipt": simulated_receipt,
            "actual_public_inode_token": [value.st_dev, value.st_ino],
            "required_binding_fields": required,
            "missing_binding_fields": missing,
            "gap_found": True,
        }


def crash_boundary_case() -> dict[str, Any]:
    boundaries = [
        {
            "boundary": "BEFORE_LINK",
            "public_expected": "ABSENT_OR_COMPETITOR_ONLY",
            "restart_authority": "NO_RECOVERED_SUCCESS; PRESERVE_COMPETITOR; NEW UNIQUE LOCAL ATTEMPT_ONLY_AFTER_POLICY",
        },
        {
            "boundary": "AFTER_LINK_BEFORE_DIRECTORY_FSYNC",
            "public_expected": "MAY_BE_OWNED_COMPLETE_OR_ABSENT_AFTER_CRASH",
            "restart_authority": "INSPECT_BOUND_DIRFD; RECOVER_ONLY_EXACT_OWNED_INODE_PLUS_EXACT_BYTES_PLUS_VALID_CONTRACT",
        },
        {
            "boundary": "AFTER_DIRECTORY_FSYNC_BEFORE_HIDDEN_UNLINK",
            "public_expected": "OWNED_COMPLETE_WITH_HIDDEN_LINK_POSSIBLE",
            "restart_authority": "RECOVER_ONLY_EXACT_OWNED_INODE_PLUS_EXACT_BYTES_PLUS_VALID_CONTRACT; CLEAN_OWNED_HIDDEN",
        },
        {
            "boundary": "AFTER_HIDDEN_UNLINK_BEFORE_SECOND_DIRECTORY_FSYNC",
            "public_expected": "OWNED_COMPLETE_SINGLE_LINK_OR_METADATA_OUTCOME_UNCERTAIN",
            "restart_authority": "RECOVER_ONLY_EXACT_OWNED_INODE_PLUS_EXACT_BYTES_PLUS_VALID_CONTRACT",
        },
        {
            "boundary": "BEFORE_CALLER_RECEIPT",
            "public_expected": "OWNED_COMPLETE_SINGLE_LINK",
            "restart_authority": "PERSISTED_RECEIPT_REQUIRED; ABSENT OWNED_TOKEN_BINDING FAILS_CLOSED",
        },
    ]
    valid = all("EXACT_OWNED_INODE" in item["restart_authority"] or item["boundary"] == "BEFORE_LINK" or "PERSISTED_RECEIPT_REQUIRED" in item["restart_authority"] for item in boundaries)
    blind_replay_forbidden = all("BLIND_REPLAY" not in item["restart_authority"] for item in boundaries)
    return {
        "case_id": "FIVE_CRASH_BOUNDARY_RESTART_CLASSIFICATIONS",
        "passed": len(boundaries) == 5 and valid and blind_replay_forbidden,
        "boundaries": boundaries,
        "blind_replay_allowed": False,
    }


def write_report(payload: dict[str, Any]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(REPORT, base.create_flags(), 0o600)
    try:
        data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
        write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> int:
    if REPORT.exists() or REPORT.is_symlink():
        raise SystemExit("REPORT_ALREADY_EXISTS")
    pins = [WRITER, V21_INVOKER, V21_MATRIX, V22_SPEC]
    expected = {
        str(WRITER.relative_to(ROOT)): WRITER_SHA256,
        str(V21_INVOKER.relative_to(ROOT)): V21_INVOKER_SHA256,
        str(V21_MATRIX.relative_to(ROOT)): V21_MATRIX_SHA256,
        str(V22_SPEC.relative_to(ROOT)): V22_SPEC_SHA256,
    }
    pins_before = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    payload = CANONICAL.read_bytes()
    base.validate_report_bytes(payload)
    cases = [static_receipt_case(), dynamic_recovered_receipt_case(payload), crash_boundary_case()]
    pins_after = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    failures = [case["case_id"] for case in cases if not case["passed"]]
    failures.extend(name for name, value in expected.items() if pins_before.get(name) != value)
    if pins_before != pins_after:
        failures.append("PINNED_INPUT_MUTATION")
    gap_found = all(case.get("gap_found") for case in cases[:2])
    status = "PASS_AUDIT_RECOVERED_RECEIPT_OWNED_TOKEN_GAP_FOUND_FAIL_CLOSED" if not failures and gap_found else "FAIL"
    report = {
        "schema": "qingshan.e40.u29c.v22.recovery_receipt_crash_boundary_audit.v1",
        "episode": "E40",
        "unit_id": "U29C",
        "recorded_at": stamp(),
        "status": status,
        "execution_permitted": False,
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "pins_before": pins_before,
        "pins_after": pins_after,
        "cases": cases,
        "receipt_binding_gap_found": gap_found,
        "gap_classification": {
            "code": "RECOVERED_SUCCESS_RECEIPT_OMITS_OWNED_INODE_TOKEN",
            "risk": "The in-process recovery decision is exact, but its returned receipt cannot independently prove that the public inode was the owned inode after restart.",
            "admission": "FAIL_CLOSED_NEW_VERSIONED_RECEIPT_WRITER_REQUIRED",
        },
        "blind_replay_allowed": False,
        "failures": failures,
        "side_effects": {"provider_calls": 0, "transactions": 0, "credits": 0, "retries": 0, "agentcut": 0, "assembly": 0},
        "next_action": "Keep execution closed. Register a new versioned V23 writer that persists an exact owned-inode recovered-success receipt before returning to the caller.",
    }
    write_report(report)
    print(json.dumps({"status": status, "report": str(REPORT), "failures": failures}, ensure_ascii=False))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
