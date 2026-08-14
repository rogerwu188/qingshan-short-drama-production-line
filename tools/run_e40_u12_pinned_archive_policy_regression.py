#!/usr/bin/env python3
"""Run the bounded E40/U12 immutable-snapshot policy regression matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v27_archive_policy_regression_v1/E40_U12_V27_PINNED_ARCHIVE_POLICY_REGRESSION_SPEC_V1.json"
SPEC_SHA256 = "a98906029f6516a6aa97a2182288c0656a49146a57e5ac2ed8e18b64692001ab"
CANONICAL_ARCHIVE = ROOT / "workflow/archive/e40_u12_v8_validator_snapshot_6c7fcd/validate_e40_u12_source_layer_package_v8_historical.py"
CURRENT_VALIDATOR = ROOT / "tools/validate_e40_u12_source_layer_package.py"
EXPECTED_V8_SHA256 = "6c7fcd2923166c909b07e8d108e7efb75b1d070edd99a4bc998096565e0c70d2"
RECEIPT_SCHEMA = "qingshan.e40.u12.v27.pinned_archive_policy_regression_matrix.v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"repo-relative path required: {raw}")
    resolved = (ROOT / path).resolve()
    resolved.relative_to(ROOT)
    return resolved


def verify_pin(item: dict[str, str], label: str) -> dict[str, Any]:
    path = repo_path(item["path"])
    actual = sha256(path) if path.is_file() else None
    return {
        "label": label,
        "path": item["path"],
        "expected_sha256": item["sha256"],
        "actual_sha256": actual,
        "status": "PASS" if actual == item["sha256"] else "FAIL",
    }


def slug(case_id: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in case_id).strip("_")


def run_request_case(case: dict[str, Any], invoker: Path, case_dir: Path) -> dict[str, Any]:
    request = repo_path(case["request"])
    request_actual_sha = sha256(request) if request.is_file() else None
    gate = case_dir / f"{slug(case['case_id'])}_GATE.json"
    command = [
        sys.executable,
        str(invoker),
        "--request",
        str(request.relative_to(ROOT)),
        "--out",
        str(gate.relative_to(ROOT)),
        "--expect-status",
        case["expected_status"],
    ]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    gate_payload: dict[str, Any] | None = None
    gate_error: str | None = None
    if gate.is_file():
        try:
            gate_payload = json.loads(gate.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            gate_error = str(exc)
    actual_status = gate_payload.get("status") if gate_payload else None
    actual_failures = gate_payload.get("failures") if gate_payload else None
    passed = all(
        [
            request_actual_sha == case["request_sha256"],
            completed.returncode == 0,
            actual_status == case["expected_status"],
            actual_failures == case["expected_failures"],
            gate_payload is not None,
            gate_payload.get("target_validator_mutated") is False if gate_payload else False,
        ]
    )
    return {
        "case_id": case["case_id"],
        "invocation": case["invocation"],
        "status": "PASS" if passed else "FAIL",
        "request": case["request"],
        "request_expected_sha256": case["request_sha256"],
        "request_actual_sha256": request_actual_sha,
        "process_exit_code": completed.returncode,
        "expected_status": case["expected_status"],
        "actual_status": actual_status,
        "expected_failures": case["expected_failures"],
        "actual_failures": actual_failures,
        "gate": str(gate.relative_to(ROOT)),
        "gate_sha256": sha256(gate) if gate.is_file() else None,
        "gate_parse_error": gate_error,
        "target_validator_mutated": gate_payload.get("target_validator_mutated") if gate_payload else None,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def run_forbidden_argument_case(
    case: dict[str, Any], invoker: Path, canonical_request: str, case_dir: Path
) -> dict[str, Any]:
    unwanted = case_dir / f"{slug(case['case_id'])}_UNWANTED_GATE.json"
    if unwanted.exists() or unwanted.is_symlink():
        return {
            "case_id": case["case_id"],
            "invocation": case["invocation"],
            "status": "FAIL",
            "failure": "UNWANTED_GATE_PREEXISTED",
            "unwanted_gate": str(unwanted.relative_to(ROOT)),
        }
    policy = "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v22_immutable_snapshot_policy_v1/E40_U12_V22_IMMUTABLE_PRE_UPGRADE_SNAPSHOT_POLICY_V1.json"
    command = [
        sys.executable,
        str(invoker),
        "--request",
        canonical_request,
        "--out",
        str(unwanted.relative_to(ROOT)),
        "--expect-status",
        "PASS_ARCHIVE_PRECONDITION_PROVEN_NO_MUTATION",
        case["forbidden_argument"],
        policy,
    ]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    unwanted_exists = unwanted.exists() or unwanted.is_symlink()
    validator_executed = unwanted_exists
    parser_rejected = "unrecognized arguments" in completed.stderr and case["forbidden_argument"] in completed.stderr
    passed = all(
        [
            completed.returncode == case["expected_exit_code"],
            validator_executed is case["expected_validator_executed"],
            unwanted_exists is case["expected_unwanted_gate_exists"],
            parser_rejected,
        ]
    )
    return {
        "case_id": case["case_id"],
        "invocation": case["invocation"],
        "status": "PASS" if passed else "FAIL",
        "forbidden_argument": case["forbidden_argument"],
        "expected_exit_code": case["expected_exit_code"],
        "actual_exit_code": completed.returncode,
        "expected_validator_executed": case["expected_validator_executed"],
        "actual_validator_executed": validator_executed,
        "expected_unwanted_gate_exists": case["expected_unwanted_gate_exists"],
        "actual_unwanted_gate_exists": unwanted_exists,
        "parser_rejected": parser_rejected,
        "unwanted_gate": str(unwanted.relative_to(ROOT)),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = repo_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    case_dir = out.parent / "cases"
    case_dir.mkdir(parents=True, exist_ok=True)

    spec_actual_sha = sha256(SPEC)
    spec = json.loads(SPEC.read_text())
    pins = [
        verify_pin(spec["pinned_invoker"], "PINNED_INVOKER"),
        verify_pin(spec["pinned_validator"], "PINNED_VALIDATOR"),
        verify_pin(spec["pinned_policy"], "PINNED_POLICY"),
    ]
    before = {
        "canonical_archive_sha256": sha256(CANONICAL_ARCHIVE),
        "current_validator_sha256": sha256(CURRENT_VALIDATOR),
    }
    invoker = repo_path(spec["pinned_invoker"]["path"])
    request_cases = [case for case in spec["cases"] if case["invocation"] == "PINNED_REQUEST"]
    argument_cases = [case for case in spec["cases"] if case["invocation"] == "FORBIDDEN_ARGUMENT_NEGATIVE"]
    canonical_request = request_cases[0]["request"]
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(run_request_case, case, invoker, case_dir): case["case_id"]
            for case in request_cases
        }
        for case in argument_cases:
            futures[executor.submit(run_forbidden_argument_case, case, invoker, canonical_request, case_dir)] = case["case_id"]
        for future in as_completed(futures):
            results.append(future.result())
    positions = {case["case_id"]: index for index, case in enumerate(spec["cases"])}
    results.sort(key=lambda item: positions[item["case_id"]])

    after = {
        "canonical_archive_sha256": sha256(CANONICAL_ARCHIVE),
        "current_validator_sha256": sha256(CURRENT_VALIDATOR),
    }
    passed_count = sum(item["status"] == "PASS" for item in results)
    unchanged = before == after and all(value == EXPECTED_V8_SHA256 for value in before.values())
    pin_pass = all(item["status"] == "PASS" for item in pins)
    overall_pass = all(
        [
            spec_actual_sha == SPEC_SHA256,
            pin_pass,
            len(results) == spec["expected_case_count"],
            passed_count == spec["expected_pass_count"],
            unchanged,
        ]
    )
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_ALL_5_EXPECTED_PINNED_ARCHIVE_POLICY_OUTCOMES" if overall_pass else "FAIL_CLOSED_REGRESSION_MISMATCH",
        "spec": str(SPEC.relative_to(ROOT)),
        "spec_expected_sha256": SPEC_SHA256,
        "spec_actual_sha256": spec_actual_sha,
        "pins": pins,
        "case_count": len(results),
        "pass_count": passed_count,
        "cases": results,
        "canonical_before": before,
        "canonical_after": after,
        "canonical_files_unchanged": unchanged,
        "bounded_concurrency": 4,
        "authority_keys_admitted": 0,
        "production_assets_admitted": 0,
        "authorization": False,
        "maximum_new_submissions": 0,
        "side_effects": {
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
            "generation_actions": 0,
            "renders": 0,
            "agentcut_actions": 0,
            "assembly_actions": 0,
            "release_actions": 0,
            "browser_started": False,
            "platform_state_changed": False,
            "work_queue_changed": False,
            "e38_state_changed": False,
            "e39_state_changed": False,
        },
    }
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "passed": f"{passed_count}/{len(results)}", "canonical_unchanged": unchanged}))
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
