#!/usr/bin/env python3
"""Run the bounded U29C V11 writer pinning and child-boundary audit."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WRITER = ROOT / "tools/run_e40_u29c_v10_atomic_reserved_capability_gate.py"
WRITER_SHA256 = "aaeeee8f5b714f443db41bb716aeae5b887962f03d52c949dcbe722a421a1db8"
SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v11_atomic_writer_pinning_v1/E40_U29C_V11_PINNED_WRITER_SUBSTITUTION_AND_DESCRIPTOR_BOUNDARY_SPEC_V1.json"
SPEC_SHA256 = "fb256b28269149ef7e7121c3e20112167c660575c5a006157be9d34235f5319a"
OUTPUT_ROOT = ROOT / "qa/e40_preproduction_20260808/u29c_v10_atomic_reserved_writer_v1"
CANONICAL_NAME = "E40_U29C_V11_PINNED_CANONICAL_GATE_V1.json"
REPORT = ROOT / "qa/e40_preproduction_20260808/u29c_v11_atomic_writer_pinning_v1/E40_U29C_V11_PINNED_WRITER_BOUNDARY_AUDIT_V1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise RuntimeError("REPORT_WRITE_FAILED")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def verify_pins() -> None:
    if digest(WRITER) != WRITER_SHA256:
        raise SystemExit("PINNED_WRITER_SHA_MISMATCH")
    if digest(SPEC) != SPEC_SHA256:
        raise SystemExit("PINNED_SPEC_SHA_MISMATCH")


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)


def canonical_case() -> dict[str, Any]:
    output = OUTPUT_ROOT / CANONICAL_NAME
    if output.exists() or output.is_symlink():
        raise SystemExit("CANONICAL_OUTPUT_ALREADY_EXISTS")
    completed = run([sys.executable, str(WRITER), "--output-name", CANONICAL_NAME])
    report = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    passed = (
        completed.returncode == 0
        and "PASS_ATOMIC_RESERVED_FAIL_CLOSED_NO_SUBMIT" in completed.stdout
        and report.get("status") == "PASS_EXPECTED_FAIL_CLOSED_NO_SUBMIT"
        and report.get("execution_permitted") is False
    )
    return {
        "case_id": "CANONICAL_PINNED_WRITER_PASS",
        "passed": passed,
        "returncode": completed.returncode,
        "output": str(output.relative_to(ROOT)),
        "output_sha256": digest(output) if output.is_file() else None,
        "validator_status": report.get("status"),
        "execution_permitted": report.get("execution_permitted"),
        "stderr": completed.stderr.strip(),
    }


def substitution_case(case_id: str, forbidden_argument: str, value: str) -> dict[str, Any]:
    slug = case_id.removesuffix("_REJECTED")
    unwanted_name = f"E40_U29C_V11_UNWANTED_{slug}_GATE_V1.json"
    unwanted = OUTPUT_ROOT / unwanted_name
    if unwanted.exists() or unwanted.is_symlink():
        raise SystemExit(f"UNWANTED_OUTPUT_ALREADY_EXISTS_{case_id}")
    before_stages = sorted(path.name for path in OUTPUT_ROOT.glob(".u29c-v10-stage-*") if path.exists())
    completed = run(
        [
            sys.executable,
            str(WRITER),
            "--output-name",
            unwanted_name,
            forbidden_argument,
            value,
        ]
    )
    after_stages = sorted(path.name for path in OUTPUT_ROOT.glob(".u29c-v10-stage-*") if path.exists())
    parser_rejected = "unrecognized arguments" in completed.stderr and forbidden_argument in completed.stderr
    passed = completed.returncode == 2 and parser_rejected and not unwanted.exists() and before_stages == after_stages
    return {
        "case_id": case_id,
        "passed": passed,
        "forbidden_argument": forbidden_argument,
        "returncode": completed.returncode,
        "parser_rejected": parser_rejected,
        "unwanted_output": str(unwanted.relative_to(ROOT)),
        "unwanted_output_exists": unwanted.exists(),
        "stage_entries_before": before_stages,
        "stage_entries_after": after_stages,
    }


def find_subprocess_call(source: str) -> tuple[ast.Call, str]:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "run_validator_in_stage":
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
                continue
            if isinstance(child.func.value, ast.Name) and child.func.value.id == "subprocess" and child.func.attr == "run":
                return child, ast.get_source_segment(source, child) or ""
    raise SystemExit("SUBPROCESS_CALL_NOT_FOUND")


def descriptor_boundary_case() -> dict[str, Any]:
    source = WRITER.read_text(encoding="utf-8")
    call, segment = find_subprocess_call(source)
    keyword_names = {keyword.arg for keyword in call.keywords if keyword.arg}
    pinned_validator_present = "str(VALIDATOR)" in segment
    pinned_contract_present = "str(CONTRACT)" in segment
    private_stage_present = "stage_name" in segment and "staged_name" in segment
    final_root_lexically_exposed = "OUTPUT_ROOT" in segment
    reservation_fd_exposed = "reservation.output_fd" in segment or "output_fd" in segment
    root_fd_passed = "pass_fds" in keyword_names or "root_fd" in segment
    close_fds_effective = "pass_fds" not in keyword_names
    boundary_satisfied = (
        pinned_validator_present
        and pinned_contract_present
        and private_stage_present
        and not final_root_lexically_exposed
        and not reservation_fd_exposed
        and not root_fd_passed
        and close_fds_effective
    )
    boundary_failures: list[str] = []
    if final_root_lexically_exposed:
        boundary_failures.append("FINAL_OUTPUT_ROOT_LEXICALLY_EXPOSED_TO_CHILD")
    if reservation_fd_exposed:
        boundary_failures.append("FINAL_RESERVATION_FD_EXPOSED_TO_CHILD")
    if root_fd_passed:
        boundary_failures.append("FINAL_ROOT_FD_EXPOSED_TO_CHILD")
    if not close_fds_effective:
        boundary_failures.append("CHILD_DESCRIPTOR_CLOSURE_NOT_EFFECTIVE")
    return {
        "case_id": "DESCRIPTOR_BOUNDARY_STATIC_AUDIT",
        "audit_completed": True,
        "boundary_satisfied": boundary_satisfied,
        "pinned_validator_present": pinned_validator_present,
        "pinned_contract_present": pinned_contract_present,
        "private_stage_present": private_stage_present,
        "final_output_root_lexically_exposed": final_root_lexically_exposed,
        "final_reservation_fd_exposed": reservation_fd_exposed,
        "final_root_fd_passed": root_fd_passed,
        "close_fds_effective_by_default": close_fds_effective,
        "boundary_failures": boundary_failures,
        "subprocess_call_lineno": call.lineno,
    }


def main() -> int:
    if REPORT.exists() or REPORT.is_symlink():
        raise SystemExit("REPORT_ALREADY_EXISTS")
    verify_pins()
    pins_before = {"writer": digest(WRITER), "spec": digest(SPEC)}
    cases = [
        canonical_case(),
        substitution_case("VALIDATOR_SUBSTITUTION_REJECTED", "--validator", str(ROOT / "tools/validate_e40_u29c_v6_capability_contract.py")),
        substitution_case("CONTRACT_SUBSTITUTION_REJECTED", "--contract", str(SPEC)),
        substitution_case("OUTPUT_ROOT_SUBSTITUTION_REJECTED", "--output-root", "/tmp/e40-u29c-v11-unwanted"),
        descriptor_boundary_case(),
    ]
    pins_after = {"writer": digest(WRITER), "spec": digest(SPEC)}
    operational_failures = [case["case_id"] for case in cases[:4] if not case.get("passed")]
    boundary = cases[4]
    audit_failures: list[str] = []
    if pins_before != pins_after:
        audit_failures.append("PINNED_INPUT_MUTATION")
    audit_failures.extend(operational_failures)
    expected_gap_found = boundary["audit_completed"] and boundary["boundary_failures"] == [
        "FINAL_OUTPUT_ROOT_LEXICALLY_EXPOSED_TO_CHILD"
    ]
    if not expected_gap_found:
        audit_failures.append("BOUNDARY_RESULT_NOT_EXACTLY_EXPECTED_FINAL_ROOT_EXPOSURE")
    status = "PASS_AUDIT_BOUNDARY_GAP_FOUND_FAIL_CLOSED_NO_SUBMIT" if not audit_failures else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29c.v11.pinned_writer_boundary_audit.v1",
        "episode": "E40",
        "unit_id": "U29C",
        "recorded_at": stamp(),
        "status": status,
        "execution_permitted": False,
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "writer": str(WRITER.relative_to(ROOT)),
        "writer_sha256": pins_after["writer"],
        "spec": str(SPEC.relative_to(ROOT)),
        "spec_sha256": pins_after["spec"],
        "case_count": len(cases),
        "operational_pass_count": sum(1 for case in cases[:4] if case.get("passed")),
        "boundary_requirement_satisfied": boundary["boundary_satisfied"],
        "boundary_failures": boundary["boundary_failures"],
        "cases": cases,
        "audit_failures": audit_failures,
        "classification": (
            "The writer is pinned and caller substitution is closed, but the validator receives a staging "
            "path beneath the final output root. Execution remains closed until staging uses a separate "
            "fixed, identity-bound root and the boundary matrix passes."
        ),
        "side_effects": {
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
            "retries": 0,
            "agentcut": 0,
            "assembly": 0,
        },
        "next_action": (
            "Register a zero-cost successor to implement a separately bound staging root, repin the writer, "
            "and rerun canonical, substitution, root-swap and stage-cleanup negatives."
        ),
    }
    write_exclusive(REPORT, payload)
    print(json.dumps({"status": status, "report": str(REPORT), "boundary_failures": boundary["boundary_failures"], "audit_failures": audit_failures}, ensure_ascii=False))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
