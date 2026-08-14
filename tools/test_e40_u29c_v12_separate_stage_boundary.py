#!/usr/bin/env python3
"""Run the bounded V12 separate staging-root boundary matrix."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v12_separate_stage_capability_gate as writer  # noqa: E402


WRITER = ROOT / "tools/run_e40_u29c_v12_separate_stage_capability_gate.py"
V10_WRITER = ROOT / "tools/run_e40_u29c_v10_atomic_reserved_capability_gate.py"
V10_WRITER_SHA256 = "aaeeee8f5b714f443db41bb716aeae5b887962f03d52c949dcbe722a421a1db8"
CANONICAL_NAME = "E40_U29C_V12_SEPARATE_STAGE_CANONICAL_GATE_V1.json"
REPORT = ROOT / "qa/e40_preproduction_20260808/u29c_v12_separate_staging_root_v1/E40_U29C_V12_SEPARATE_STAGE_BOUNDARY_MATRIX_V1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)


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


def canonical_case() -> dict[str, Any]:
    output = writer.FINAL_ROOT / CANONICAL_NAME
    if output.exists() or output.is_symlink():
        raise SystemExit("CANONICAL_OUTPUT_ALREADY_EXISTS")
    completed = run([sys.executable, str(WRITER), "--output-name", CANONICAL_NAME])
    report = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    passed = (
        completed.returncode == 0
        and "PASS_SEPARATE_STAGE_ATOMIC_RESERVED_FAIL_CLOSED_NO_SUBMIT" in completed.stdout
        and report.get("status") == "PASS_EXPECTED_FAIL_CLOSED_NO_SUBMIT"
        and report.get("execution_permitted") is False
    )
    return {
        "case_id": "CANONICAL_SEPARATE_STAGE_PASS_EXECUTION_FALSE",
        "passed": passed,
        "returncode": completed.returncode,
        "stderr": completed.stderr.strip(),
        "output": str(output.relative_to(ROOT)),
        "output_sha256": digest(output) if output.is_file() else None,
        "validator_status": report.get("status"),
        "execution_permitted": report.get("execution_permitted"),
    }


def find_child_call(source: str) -> tuple[ast.Call, str]:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "run_validator":
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == "subprocess"
                and child.func.attr == "run"
            ):
                return child, ast.get_source_segment(source, child) or ""
    raise SystemExit("CHILD_SUBPROCESS_CALL_NOT_FOUND")


def static_boundary_case() -> dict[str, Any]:
    source = WRITER.read_text(encoding="utf-8")
    call, segment = find_child_call(source)
    keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
    close_fds_true = isinstance(keywords.get("close_fds"), ast.Constant) and keywords["close_fds"].value is True
    checks = {
        "pinned_validator_present": "str(VALIDATOR)" in segment,
        "pinned_contract_present": "str(CONTRACT)" in segment,
        "staging_root_present": "STAGING_ROOT" in segment,
        "final_root_absent": "FINAL_ROOT" not in segment,
        "final_output_name_absent": "output_name" not in segment,
        "final_reservation_fd_absent": "reservation.fd" not in segment,
        "final_root_fd_absent": "final.fd" not in segment and "final_root.fd" not in segment,
        "pass_fds_absent": "pass_fds" not in keywords,
        "close_fds_explicit_true": close_fds_true,
    }
    return {
        "case_id": "STATIC_CHILD_BOUNDARY_FINAL_ROOT_ABSENT",
        "passed": all(checks.values()),
        "checks": checks,
        "subprocess_call_lineno": call.lineno,
    }


def distinct_roots_case() -> dict[str, Any]:
    final_stat = os.stat(writer.FINAL_ROOT, follow_symlinks=False)
    stage_stat = os.stat(writer.STAGING_ROOT, follow_symlinks=False)
    final_rel = writer.FINAL_ROOT.relative_to(writer.QA_EPISODE_ROOT)
    stage_rel = writer.STAGING_ROOT.relative_to(writer.QA_EPISODE_ROOT)
    distinct = (final_stat.st_dev, final_stat.st_ino) != (stage_stat.st_dev, stage_stat.st_ino)
    separate_child_roots = final_rel.parts[0] != stage_rel.parts[0]
    private_modes = (final_stat.st_mode & 0o077) == 0 and (stage_stat.st_mode & 0o077) == 0
    return {
        "case_id": "FINAL_AND_STAGE_ROOT_DISTINCT_INODES",
        "passed": distinct and separate_child_roots and private_modes,
        "final_identity": [final_stat.st_dev, final_stat.st_ino],
        "staging_identity": [stage_stat.st_dev, stage_stat.st_ino],
        "separate_child_roots": separate_child_roots,
        "private_modes": private_modes,
    }


def stage_root_swap_case(base: Path) -> dict[str, Any]:
    final_path = base / "swap_final"
    stage_path = base / "swap_stage"
    final = writer.open_bound_root(final_path)
    staging = writer.open_bound_root(stage_path)
    reservation = writer.reserve_output(final, "target.json")
    stage_name, stage_fd, stage_token = writer.create_stage(staging)
    original = base / "swap_stage_original"
    attacker = base / "swap_stage_attacker"
    try:
        stage_path.rename(original)
        attacker.mkdir(mode=0o700)
        stage_path.symlink_to(attacker, target_is_directory=True)
        error = None
        try:
            writer.assert_root_identity(staging)
        except writer.GateError as exc:
            error = str(exc)
        writer.cleanup_stage(staging, stage_name, stage_fd, stage_token)
        stage_fd = -1
        removed = writer.cleanup_reservation(reservation)
        final_absent = not (final_path / "target.json").exists()
        return {
            "case_id": "STAGING_ROOT_SWAP_REJECTED_WITH_NO_FINAL_GATE",
            "passed": error == "BOUND_ROOT_IDENTITY_DRIFT" and removed and final_absent,
            "error": error,
            "owned_reservation_removed": removed,
            "final_gate_absent": final_absent,
        }
    finally:
        if stage_fd >= 0:
            writer.cleanup_stage(staging, stage_name, stage_fd, stage_token)
        os.close(reservation.fd)
        os.close(staging.fd)
        os.close(final.fd)


def malformed_cleanup_case(base: Path) -> dict[str, Any]:
    final_path = base / "malformed_final"
    stage_path = base / "malformed_stage"
    final = writer.open_bound_root(final_path)
    staging = writer.open_bound_root(stage_path)
    reservation = writer.reserve_output(final, "target.json")
    stage_name, stage_fd, stage_token = writer.create_stage(staging)
    try:
        error = None
        try:
            writer.commit_report(reservation, b"{malformed-json")
        except writer.GateError as exc:
            error = str(exc)
        writer.cleanup_stage(staging, stage_name, stage_fd, stage_token)
        stage_fd = -1
        removed = writer.cleanup_reservation(reservation)
        final_absent = not (final_path / "target.json").exists()
        stage_empty = list(stage_path.iterdir()) == []
        return {
            "case_id": "MALFORMED_REPORT_NO_FINAL_GATE_NO_STAGE_RESIDUE",
            "passed": error == "STAGED_REPORT_INVALID_JSON" and removed and final_absent and stage_empty,
            "error": error,
            "owned_reservation_removed": removed,
            "final_gate_absent": final_absent,
            "staging_root_empty": stage_empty,
        }
    finally:
        if stage_fd >= 0:
            writer.cleanup_stage(staging, stage_name, stage_fd, stage_token)
        os.close(reservation.fd)
        os.close(staging.fd)
        os.close(final.fd)


def substitution_case(argument: str, value: str) -> dict[str, Any]:
    slug = argument.removeprefix("--").replace("-", "_").upper()
    name = f"E40_U29C_V12_UNWANTED_{slug}_GATE_V1.json"
    output = writer.FINAL_ROOT / name
    if output.exists() or output.is_symlink():
        raise SystemExit(f"UNWANTED_OUTPUT_ALREADY_EXISTS_{slug}")
    stages_before = sorted(path.name for path in writer.STAGING_ROOT.glob(".u29c-v12-stage-*"))
    completed = run([sys.executable, str(WRITER), "--output-name", name, argument, value])
    stages_after = sorted(path.name for path in writer.STAGING_ROOT.glob(".u29c-v12-stage-*"))
    parser_rejected = "unrecognized arguments" in completed.stderr and argument in completed.stderr
    passed = completed.returncode == 2 and parser_rejected and not output.exists() and stages_before == stages_after
    return {
        "argument": argument,
        "passed": passed,
        "returncode": completed.returncode,
        "parser_rejected": parser_rejected,
        "unwanted_output_exists": output.exists(),
        "stage_entries_unchanged": stages_before == stages_after,
    }


def substitutions_case() -> dict[str, Any]:
    cases = [
        substitution_case("--validator", str(writer.VALIDATOR)),
        substitution_case("--contract", str(writer.CONTRACT)),
        substitution_case("--final-root", "/tmp/e40-u29c-v12-final"),
        substitution_case("--staging-root", "/tmp/e40-u29c-v12-stage"),
    ]
    return {
        "case_id": "CALLER_SUBSTITUTIONS_REJECTED_BEFORE_CHILD",
        "passed": all(case["passed"] for case in cases),
        "subcases": cases,
    }


def main() -> int:
    if REPORT.exists() or REPORT.is_symlink():
        raise SystemExit("REPORT_ALREADY_EXISTS")
    pins = [writer.VALIDATOR, writer.CONTRACT, writer.V11_AUDIT, writer.V12_SPEC, V10_WRITER]
    pins_before = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    if pins_before[str(V10_WRITER.relative_to(ROOT))] != V10_WRITER_SHA256:
        raise SystemExit("IMMUTABLE_V10_WRITER_SHA_MISMATCH")
    canonical = canonical_case()
    static_boundary = static_boundary_case()
    distinct = distinct_roots_case()
    writer.QA_EPISODE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bounded-u29c-v12-", dir=writer.QA_EPISODE_ROOT) as temporary:
        base = Path(temporary)
        stage_swap = stage_root_swap_case(base)
        malformed = malformed_cleanup_case(base)
    substitutions = substitutions_case()
    cases = [canonical, static_boundary, distinct, stage_swap, malformed, substitutions]
    pins_after = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    failures = [case["case_id"] for case in cases if not case["passed"]]
    if pins_before != pins_after:
        failures.append("PINNED_INPUT_MUTATION")
    status = "PASS_SEPARATE_STAGING_ROOT_BOUNDARY_MATRIX_NO_SUBMIT" if not failures else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29c.v12.separate_staging_root_boundary_matrix.v1",
        "episode": "E40",
        "unit_id": "U29C",
        "recorded_at": stamp(),
        "status": status,
        "execution_permitted": False,
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "writer": str(WRITER.relative_to(ROOT)),
        "writer_sha256": digest(WRITER),
        "pins_before": pins_before,
        "pins_after": pins_after,
        "case_count": len(cases),
        "pass_count": sum(1 for case in cases if case["passed"]),
        "cases": cases,
        "failures": failures,
        "side_effects": {
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
            "retries": 0,
            "agentcut": 0,
            "assembly": 0,
        },
        "next_action": (
            "Keep execution closed. Register a local fixed-SHA successor to audit staging-root parent "
            "containment, permissions and process-level residue across repeated canonical runs."
        ),
    }
    write_exclusive(REPORT, payload)
    print(json.dumps({"status": status, "report": str(REPORT), "failures": failures}, ensure_ascii=False))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
