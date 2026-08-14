#!/usr/bin/env python3
"""Run the V13 pinned repeated-run residue and containment matrix."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v12_separate_stage_capability_gate as writer  # noqa: E402


INVOKER = ROOT / "tools/run_e40_u29c_v13_pinned_separate_stage_gate.py"
INVOKER_SHA256 = "d9dbce9dc23ac293b59ff2df66b3a51a28a5db3612d632d2302d26e66f9acd7a"
V12_WRITER = ROOT / "tools/run_e40_u29c_v12_separate_stage_capability_gate.py"
V12_WRITER_SHA256 = "00696e5c81a5e41510fad9f2244c8068c35d373c09f55c2911e21e47e65d23f9"
V12_MATRIX = ROOT / "qa/e40_preproduction_20260808/u29c_v12_separate_staging_root_v1/E40_U29C_V12_SEPARATE_STAGE_BOUNDARY_MATRIX_V1.json"
V12_MATRIX_SHA256 = "420da06203ec4fce9934912d341848fe564622df68b55b4d2ec01c0148e8566e"
V13_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v13_pinned_separate_stage_regression_v1/E40_U29C_V13_PINNED_WRITER_RESIDUE_AND_PARENT_CONTAINMENT_SPEC_V1.json"
V13_SPEC_SHA256 = "36bc00ee54c340471656a6353df16476984dbb2a44274fb278811d27764a682d"
RUN_NAMES = [
    "E40_U29C_V13_PINNED_REPEAT_RUN_1_GATE_V1.json",
    "E40_U29C_V13_PINNED_REPEAT_RUN_2_GATE_V1.json",
]
REPORT = ROOT / "qa/e40_preproduction_20260808/u29c_v13_pinned_separate_stage_regression_v1/E40_U29C_V13_PINNED_RESIDUE_PARENT_CONTAINMENT_MATRIX_V1.json"


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


def stage_entries() -> list[str]:
    return sorted(path.name for path in writer.STAGING_ROOT.iterdir())


def canonical_run(name: str, run_number: int) -> dict[str, Any]:
    output = writer.FINAL_ROOT / name
    if output.exists() or output.is_symlink():
        raise SystemExit(f"RUN_OUTPUT_ALREADY_EXISTS_{run_number}")
    residue_before = stage_entries()
    completed = run([sys.executable, str(INVOKER), "--output-name", name])
    residue_after = stage_entries()
    report = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    passed = (
        completed.returncode == 0
        and "PASS_SEPARATE_STAGE_ATOMIC_RESERVED_FAIL_CLOSED_NO_SUBMIT" in completed.stdout
        and report.get("status") == "PASS_EXPECTED_FAIL_CLOSED_NO_SUBMIT"
        and report.get("execution_permitted") is False
        and residue_before == []
        and residue_after == []
    )
    return {
        "case_id": f"PINNED_INVOKER_CANONICAL_RUN_{run_number}",
        "passed": passed,
        "returncode": completed.returncode,
        "stderr": completed.stderr.strip(),
        "output": str(output.relative_to(ROOT)),
        "output_sha256": digest(output) if output.is_file() else None,
        "validator_status": report.get("status"),
        "execution_permitted": report.get("execution_permitted"),
        "staging_entries_before": residue_before,
        "staging_entries_after": residue_after,
    }


def no_symlink_components(path: Path, anchor: Path) -> bool:
    current = anchor
    for part in path.relative_to(anchor).parts:
        current /= part
        if current.is_symlink():
            return False
    return True


def contained(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(parent.resolve(strict=True))
        return True
    except (FileNotFoundError, ValueError):
        return False


def root_containment_case() -> dict[str, Any]:
    final = os.stat(writer.FINAL_ROOT, follow_symlinks=False)
    staging = os.stat(writer.STAGING_ROOT, follow_symlinks=False)
    final_rel = writer.FINAL_ROOT.relative_to(writer.QA_EPISODE_ROOT)
    stage_rel = writer.STAGING_ROOT.relative_to(writer.QA_EPISODE_ROOT)
    checks = {
        "final_contained": contained(writer.FINAL_ROOT, writer.QA_EPISODE_ROOT),
        "staging_contained": contained(writer.STAGING_ROOT, writer.QA_EPISODE_ROOT),
        "final_no_symlink_components": no_symlink_components(writer.FINAL_ROOT, writer.QA_EPISODE_ROOT),
        "staging_no_symlink_components": no_symlink_components(writer.STAGING_ROOT, writer.QA_EPISODE_ROOT),
        "distinct_inodes": (final.st_dev, final.st_ino) != (staging.st_dev, staging.st_ino),
        "distinct_child_roots": final_rel.parts[0] != stage_rel.parts[0],
        "final_private_0700": stat.S_IMODE(final.st_mode) == 0o700,
        "staging_private_0700": stat.S_IMODE(staging.st_mode) == 0o700,
        "staging_empty": stage_entries() == [],
    }
    return {
        "case_id": "ROOTS_PRIVATE_DISTINCT_PARENT_CONTAINED",
        "passed": all(checks.values()),
        "checks": checks,
        "final_identity": [final.st_dev, final.st_ino],
        "staging_identity": [staging.st_dev, staging.st_ino],
    }


def substitution_case(argument: str, value: str) -> dict[str, Any]:
    slug = argument.removeprefix("--").replace("-", "_").upper()
    name = f"E40_U29C_V13_UNWANTED_{slug}_GATE_V1.json"
    output = writer.FINAL_ROOT / name
    if output.exists() or output.is_symlink():
        raise SystemExit(f"UNWANTED_OUTPUT_ALREADY_EXISTS_{slug}")
    before = stage_entries()
    completed = run([sys.executable, str(INVOKER), "--output-name", name, argument, value])
    after = stage_entries()
    parser_rejected = "unrecognized arguments" in completed.stderr and argument in completed.stderr
    return {
        "argument": argument,
        "passed": completed.returncode == 2 and parser_rejected and not output.exists() and before == after == [],
        "returncode": completed.returncode,
        "parser_rejected": parser_rejected,
        "unwanted_output_exists": output.exists(),
        "staging_entries_before": before,
        "staging_entries_after": after,
    }


def substitutions_case() -> dict[str, Any]:
    subcases = [
        substitution_case("--writer", str(writer.ROOT / "tools/run_e40_u29c_v10_atomic_reserved_capability_gate.py")),
        substitution_case("--validator", str(writer.VALIDATOR)),
        substitution_case("--contract", str(writer.CONTRACT)),
        substitution_case("--final-root", "/tmp/e40-u29c-v13-final"),
        substitution_case("--staging-root", "/tmp/e40-u29c-v13-stage"),
    ]
    return {
        "case_id": "CALLER_SUBSTITUTIONS_REJECTED_BEFORE_CHILD",
        "passed": all(case["passed"] for case in subcases),
        "subcases": subcases,
    }


def main() -> int:
    if REPORT.exists() or REPORT.is_symlink():
        raise SystemExit("REPORT_ALREADY_EXISTS")
    pins = [INVOKER, V12_WRITER, V12_MATRIX, V13_SPEC]
    expected = {
        str(INVOKER.relative_to(ROOT)): INVOKER_SHA256,
        str(V12_WRITER.relative_to(ROOT)): V12_WRITER_SHA256,
        str(V12_MATRIX.relative_to(ROOT)): V12_MATRIX_SHA256,
        str(V13_SPEC.relative_to(ROOT)): V13_SPEC_SHA256,
    }
    pins_before = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    pin_failures = [name for name, value in expected.items() if pins_before.get(name) != value]
    cases = [canonical_run(RUN_NAMES[0], 1), canonical_run(RUN_NAMES[1], 2), root_containment_case(), substitutions_case()]
    pins_after = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    failures = [case["case_id"] for case in cases if not case["passed"]]
    failures.extend(pin_failures)
    if pins_before != pins_after:
        failures.append("PINNED_INPUT_MUTATION")
    status = "PASS_PINNED_REPEATED_RUN_RESIDUE_PARENT_CONTAINMENT_NO_SUBMIT" if not failures else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29c.v13.pinned_repeated_run_residue_parent_containment.v1",
        "episode": "E40",
        "unit_id": "U29C",
        "recorded_at": stamp(),
        "status": status,
        "execution_permitted": False,
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "invoker": str(INVOKER.relative_to(ROOT)),
        "invoker_sha256": digest(INVOKER),
        "pins_before": pins_before,
        "pins_after": pins_after,
        "case_count": len(cases),
        "pass_count": sum(1 for case in cases if case["passed"]),
        "cases": cases,
        "final_staging_residue": stage_entries(),
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
            "Keep execution closed. Register a bounded local successor to run concurrent distinct basenames "
            "through the pinned invoker and prove stage isolation and zero residue under shared load."
        ),
    }
    write_exclusive(REPORT, payload)
    print(json.dumps({"status": status, "report": str(REPORT), "failures": failures}, ensure_ascii=False))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
