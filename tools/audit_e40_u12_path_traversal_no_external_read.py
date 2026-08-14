#!/usr/bin/env python3
"""Dynamically audit that V28 containment rejects before external file access."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools/validate_e40_u12_immutable_snapshot_upgrade_request.py"
VALIDATOR_SHA256 = "6e850c22a4685ab50469c5d1b9d4281d1125e4b4f4b04fefcb8fd408c60d4b78"
POLICY = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v22_immutable_snapshot_policy_v1/E40_U12_V22_IMMUTABLE_PRE_UPGRADE_SNAPSHOT_POLICY_V1.json"
REQUEST = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v28_archive_path_traversal_negative_v1/E40_U12_V28_ARCHIVE_PATH_TRAVERSAL_NEGATIVE_REQUEST_V1.json"
REQUEST_SHA256 = "14ed62a28703391d7ff7a2ef41ddb976ad8940b7494fb858df237417b3322e38"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT)
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = (ROOT / args.out).resolve()
    out.relative_to(ROOT)

    policy = json.loads(POLICY.read_text())
    request = json.loads(REQUEST.read_text())
    validator_pin_ok = sha256(VALIDATOR) == VALIDATOR_SHA256
    request_pin_ok = sha256(REQUEST) == REQUEST_SHA256
    raw_archive = request["prior_version"]["archive_path"]
    resolved_archive = (ROOT / raw_archive).resolve()
    resolves_outside = not inside_repo(resolved_archive)

    spec = importlib.util.spec_from_file_location("e40_u12_v22_snapshot_validator", VALIDATOR)
    if spec is None or spec.loader is None:
        raise SystemExit("VALIDATOR_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    external_metadata_attempts: list[str] = []
    external_read_attempts: list[str] = []
    original_is_file = Path.is_file
    original_read_bytes = Path.read_bytes

    def audited_is_file(path: Path) -> bool:
        if not inside_repo(path):
            external_metadata_attempts.append(str(path))
            raise AssertionError(f"external is_file attempted: {path}")
        return original_is_file(path)

    def audited_read_bytes(path: Path) -> bytes:
        if not inside_repo(path):
            external_read_attempts.append(str(path))
            raise AssertionError(f"external read_bytes attempted: {path}")
        return original_read_bytes(path)

    Path.is_file = audited_is_file
    Path.read_bytes = audited_read_bytes
    validation_error: str | None = None
    result: dict[str, Any] | None = None
    try:
        result = module.validate(policy, request)
    except Exception as exc:  # receipt must expose any attempted bypass
        validation_error = f"{type(exc).__name__}:{exc}"
    finally:
        Path.is_file = original_is_file
        Path.read_bytes = original_read_bytes

    expected_failures = [
        "PRIOR_ARCHIVE_EXISTS",
        "PRIOR_ARCHIVE_NOT_SYMLINK",
        "PRIOR_ARCHIVE_SHA_EXACT",
    ]
    actual_failures = result.get("failures") if result else None
    external_target_read = bool(external_read_attempts)
    external_target_metadata_access = bool(external_metadata_attempts)
    passed = all(
        [
            validator_pin_ok,
            request_pin_ok,
            resolves_outside,
            validation_error is None,
            result is not None,
            result.get("status") == "FAIL_CLOSED_PRIOR_SNAPSHOT_NOT_PROVEN_NO_MUTATION" if result else False,
            actual_failures == expected_failures,
            not external_target_read,
            not external_target_metadata_access,
        ]
    )
    receipt = {
        "schema": "qingshan.e40.u12.v28.path_traversal_no_external_read_audit.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_CONTAINMENT_BEFORE_EXTERNAL_ACCESS" if passed else "FAIL_CLOSED_CONTAINMENT_AUDIT_MISMATCH",
        "validator_sha256": sha256(VALIDATOR),
        "validator_pin_ok": validator_pin_ok,
        "request_sha256": sha256(REQUEST),
        "request_pin_ok": request_pin_ok,
        "raw_archive_path": raw_archive,
        "resolved_archive_path": str(resolved_archive),
        "resolved_outside_repository": resolves_outside,
        "validation_status": result.get("status") if result else None,
        "expected_failures": expected_failures,
        "actual_failures": actual_failures,
        "external_target_metadata_attempts": external_metadata_attempts,
        "external_target_read_attempts": external_read_attempts,
        "external_target_metadata_access": external_target_metadata_access,
        "external_target_read": external_target_read,
        "validation_error": validation_error,
        "target_validator_mutated": result.get("target_validator_mutated") if result else None,
        "authorization": False,
        "maximum_new_submissions": 0,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "external_target_read": external_target_read, "external_target_metadata_access": external_target_metadata_access}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
