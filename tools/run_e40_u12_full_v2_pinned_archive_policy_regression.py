#!/usr/bin/env python3
"""Run the full seven-case E40/U12 V2 pinned archive regression."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v31_full_v2_regression_v1/E40_U12_V31_FULL_V2_PINNED_REGRESSION_SPEC_V1.json"
SPEC_SHA256 = "03a7a3c55b9411c4a41f7935ca03a0abc57aa42afaefc8ad6a9d80075411a8a8"
TARGET = ROOT / "tools/validate_e40_u12_source_layer_package.py"
CANONICAL_ARCHIVE = ROOT / "workflow/archive/e40_u12_v8_validator_snapshot_6c7fcd/validate_e40_u12_source_layer_package_v8_historical.py"
EXPECTED_CANONICAL_SHA256 = "6c7fcd2923166c909b07e8d108e7efb75b1d070edd99a4bc998096565e0c70d2"
V1_ARTIFACTS = {
    "policy_v1": (
        ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v22_immutable_snapshot_policy_v1/E40_U12_V22_IMMUTABLE_PRE_UPGRADE_SNAPSHOT_POLICY_V1.json",
        "f511ebca41fb884e35ee09ae56517d3b65915d7742b25e554b8debdafbe4c5c9",
    ),
    "validator_v1": (
        ROOT / "tools/validate_e40_u12_immutable_snapshot_upgrade_request.py",
        "6e850c22a4685ab50469c5d1b9d4281d1125e4b4f4b04fefcb8fd408c60d4b78",
    ),
    "invoker_v1": (
        ROOT / "tools/run_e40_u12_immutable_snapshot_upgrade_gate.py",
        "f87da30d588ad1a6447f9c4bcb24cf2673474b10fe22957dac24b58202888389",
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"repo-relative path required: {raw}")
    resolved = (ROOT / path).resolve()
    resolved.relative_to(ROOT)
    return resolved


def stat_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.relative_to(ROOT)),
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "st_nlink": stat.st_nlink,
        "st_size": stat.st_size,
        "st_mtime_ns": stat.st_mtime_ns,
        "sha256": sha256(path),
    }


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
    completed = subprocess.run(
        [
            sys.executable,
            str(invoker),
            "--request",
            str(request.relative_to(ROOT)),
            "--out",
            str(gate.relative_to(ROOT)),
            "--expect-status",
            case["expected_status"],
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    gate_payload: dict[str, Any] | None = None
    gate_error: str | None = None
    if gate.is_file():
        try:
            gate_payload = json.loads(gate.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            gate_error = str(exc)
    actual_status = gate_payload.get("status") if gate_payload else None
    actual_failures = gate_payload.get("failures") if gate_payload else None
    passed = bool(
        request_actual_sha == case["request_sha256"]
        and completed.returncode == 0
        and gate_payload
        and actual_status == case["expected_status"]
        and actual_failures == case["expected_failures"]
        and gate_payload.get("target_validator_mutated") is False
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
    policy = "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v30_inode_independence_hardening_v2/E40_U12_V30_IMMUTABLE_PRE_UPGRADE_SNAPSHOT_POLICY_V2.json"
    completed = subprocess.run(
        [
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
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    unwanted_exists = unwanted.exists() or unwanted.is_symlink()
    parser_rejected = "unrecognized arguments" in completed.stderr and case["forbidden_argument"] in completed.stderr
    passed = bool(
        completed.returncode == case["expected_exit_code"]
        and unwanted_exists is case["expected_unwanted_gate_exists"]
        and unwanted_exists is case["expected_validator_executed"]
        and parser_rejected
    )
    return {
        "case_id": case["case_id"],
        "invocation": case["invocation"],
        "status": "PASS" if passed else "FAIL",
        "forbidden_argument": case["forbidden_argument"],
        "expected_exit_code": case["expected_exit_code"],
        "actual_exit_code": completed.returncode,
        "expected_validator_executed": case["expected_validator_executed"],
        "actual_validator_executed": unwanted_exists,
        "expected_unwanted_gate_exists": case["expected_unwanted_gate_exists"],
        "actual_unwanted_gate_exists": unwanted_exists,
        "parser_rejected": parser_rejected,
        "unwanted_gate": str(unwanted.relative_to(ROOT)),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def run_hardlink_case(case: dict[str, Any], invoker: Path, case_dir: Path) -> dict[str, Any]:
    request = repo_path(case["request"])
    request_actual_sha = sha256(request) if request.is_file() else None
    request_payload = json.loads(request.read_text())
    fixture = repo_path(request_payload["prior_version"]["archive_path"])
    gate = case_dir / f"{slug(case['case_id'])}_GATE.json"
    target_before = stat_record(TARGET)
    fixture_during: dict[str, Any] | None = None
    target_during: dict[str, Any] | None = None
    gate_payload: dict[str, Any] | None = None
    process_exit_code: int | None = None
    stdout = ""
    stderr = ""
    error: str | None = None
    fixture_removed = False
    if fixture.exists() or fixture.is_symlink():
        error = "HARDLINK_FIXTURE_PREEXISTED"
    else:
        try:
            fixture.parent.mkdir(parents=True, exist_ok=True)
            os.link(TARGET, fixture, follow_symlinks=False)
            fixture_during = stat_record(fixture)
            target_during = stat_record(TARGET)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(invoker),
                    "--request",
                    str(request.relative_to(ROOT)),
                    "--out",
                    str(gate.relative_to(ROOT)),
                    "--expect-status",
                    case["expected_status"],
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            process_exit_code = completed.returncode
            stdout = completed.stdout.strip()
            stderr = completed.stderr.strip()
            if gate.is_file():
                gate_payload = json.loads(gate.read_text())
        except Exception as exc:
            error = f"{type(exc).__name__}:{exc}"
        finally:
            if fixture.exists() and not fixture.is_symlink():
                fixture.unlink()
            fixture_removed = not fixture.exists() and not fixture.is_symlink()
    target_after = stat_record(TARGET)
    same_inode = bool(
        fixture_during
        and target_during
        and (fixture_during["st_dev"], fixture_during["st_ino"])
        == (target_during["st_dev"], target_during["st_ino"])
    )
    link_incremented = bool(
        target_during and target_during["st_nlink"] == target_before["st_nlink"] + 1
    )
    link_restored = target_after["st_nlink"] == target_before["st_nlink"]
    target_content_unchanged = all(
        [
            target_before["sha256"] == target_after["sha256"] == EXPECTED_CANONICAL_SHA256,
            target_before["st_size"] == target_after["st_size"],
            target_before["st_mtime_ns"] == target_after["st_mtime_ns"],
        ]
    )
    actual_status = gate_payload.get("status") if gate_payload else None
    actual_failures = gate_payload.get("failures") if gate_payload else None
    passed = bool(
        error is None
        and request_actual_sha == case["request_sha256"]
        and same_inode
        and link_incremented
        and process_exit_code == 0
        and gate_payload
        and actual_status == case["expected_status"]
        and actual_failures == case["expected_failures"]
        and gate_payload.get("target_validator_mutated") is False
        and fixture_removed is case["fixture_must_be_removed"]
        and link_restored is case["target_link_count_must_be_restored"]
        and target_content_unchanged
    )
    return {
        "case_id": case["case_id"],
        "invocation": case["invocation"],
        "status": "PASS" if passed else "FAIL",
        "request": case["request"],
        "request_expected_sha256": case["request_sha256"],
        "request_actual_sha256": request_actual_sha,
        "target_before": target_before,
        "target_during": target_during,
        "target_after": target_after,
        "fixture_during": fixture_during,
        "same_device_and_inode": same_inode,
        "link_count_incremented_exactly_one": link_incremented,
        "fixture_removed": fixture_removed,
        "target_link_count_restored": link_restored,
        "target_content_unchanged": target_content_unchanged,
        "process_exit_code": process_exit_code,
        "expected_status": case["expected_status"],
        "actual_status": actual_status,
        "expected_failures": case["expected_failures"],
        "actual_failures": actual_failures,
        "gate": str(gate.relative_to(ROOT)),
        "gate_sha256": sha256(gate) if gate.is_file() else None,
        "target_validator_mutated": gate_payload.get("target_validator_mutated") if gate_payload else None,
        "error": error,
        "stdout": stdout,
        "stderr": stderr,
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
        verify_pin(spec["pinned_invoker_v2"], "PINNED_INVOKER_V2"),
        verify_pin(spec["pinned_validator_v2"], "PINNED_VALIDATOR_V2"),
        verify_pin(spec["pinned_policy_v2"], "PINNED_POLICY_V2"),
    ]
    v1_before = {
        label: {"expected_sha256": expected, "actual_sha256": sha256(path)}
        for label, (path, expected) in V1_ARTIFACTS.items()
    }
    target_before = stat_record(TARGET)
    canonical_before = stat_record(CANONICAL_ARCHIVE)
    invoker = repo_path(spec["pinned_invoker_v2"]["path"])
    request_cases = [case for case in spec["cases"] if case["invocation"] == "PINNED_REQUEST"]
    argument_case = next(case for case in spec["cases"] if case["invocation"] == "FORBIDDEN_ARGUMENT_NEGATIVE")
    hardlink_case = next(case for case in spec["cases"] if case["invocation"] == "EPHEMERAL_HARDLINK_PINNED_REQUEST")
    canonical_request = request_cases[0]["request"]
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(run_request_case, case, invoker, case_dir) for case in request_cases]
        futures.append(executor.submit(run_forbidden_argument_case, argument_case, invoker, canonical_request, case_dir))
        for future in as_completed(futures):
            results.append(future.result())
    results.append(run_hardlink_case(hardlink_case, invoker, case_dir))
    positions = {case["case_id"]: index for index, case in enumerate(spec["cases"])}
    results.sort(key=lambda item: positions[item["case_id"]])
    target_after = stat_record(TARGET)
    canonical_after = stat_record(CANONICAL_ARCHIVE)
    v1_after = {
        label: {"expected_sha256": expected, "actual_sha256": sha256(path)}
        for label, (path, expected) in V1_ARTIFACTS.items()
    }
    v1_preserved = v1_before == v1_after and all(
        item["actual_sha256"] == item["expected_sha256"] for item in v1_after.values()
    )
    canonical_preserved = target_before == target_after and canonical_before == canonical_after
    pin_pass = all(item["status"] == "PASS" for item in pins)
    passed_count = sum(item["status"] == "PASS" for item in results)
    overall_pass = all(
        [
            spec_actual_sha == SPEC_SHA256,
            pin_pass,
            v1_preserved,
            canonical_preserved,
            len(results) == spec["expected_case_count"],
            passed_count == spec["expected_pass_count"],
        ]
    )
    receipt = {
        "schema": "qingshan.e40.u12.v31.full_v2_pinned_regression_matrix.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_ALL_7_EXPECTED_V2_PINNED_OUTCOMES" if overall_pass else "FAIL_CLOSED_V2_REGRESSION_MISMATCH",
        "spec": str(SPEC.relative_to(ROOT)),
        "spec_expected_sha256": SPEC_SHA256,
        "spec_actual_sha256": spec_actual_sha,
        "pins": pins,
        "case_count": len(results),
        "pass_count": passed_count,
        "cases": results,
        "bounded_parallel_workers": 4,
        "hardlink_case_execution": "SERIAL_AFTER_INDEPENDENT_CASES",
        "v1_before": v1_before,
        "v1_after": v1_after,
        "v1_preserved": v1_preserved,
        "target_before": target_before,
        "target_after": target_after,
        "canonical_before": canonical_before,
        "canonical_after": canonical_after,
        "canonical_and_target_preserved": canonical_preserved,
        "actual_upgrade_executed": False,
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
    print(json.dumps({"status": receipt["status"], "passed": f"{passed_count}/{len(results)}", "v1_preserved": v1_preserved, "canonical_preserved": canonical_preserved}))
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
