#!/usr/bin/env python3
"""Bounded exact-SHA/reader/contention/cleanup regression for U29C V18."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as writer  # noqa: E402


INVOKER = ROOT / "tools/run_e40_u29c_v18_pinned_atomic_link_regression.py"
INVOKER_SHA256 = "ca8224744d7a8f3b71a30d5dcb2c13a3f10f21605f3c293e0698d104b4b02329"
V17_WRITER = ROOT / "tools/run_e40_u29c_v17_atomic_link_publish_gate.py"
V17_WRITER_SHA256 = "7728588e210ae17f61cc1c08eef6a18fdd3dfdba3e6cc1e77e61e2f8ae1778d8"
V17_MATRIX = ROOT / "qa/e40_preproduction_20260808/u29c_v17_atomic_link_writer_v1/E40_U29C_V17_ATOMIC_LINK_READER_CONTENTION_MATRIX_V1.json"
V17_MATRIX_SHA256 = "e9927de46465e09c1e70403aeebb1235bfa57ce6a42c46ac13a5b106adba0062"
VALIDATOR = ROOT / "tools/validate_e40_u29c_v6_capability_contract.py"
VALIDATOR_SHA256 = "ebf2275931a09cd51dbb00af8268959faea62e1885b5b3a24be11d6c00fd87e5"
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u29c_v6_changed_representation_no_submit_v1/E40_U29C_V6_PROVIDER_CAPABILITY_AND_EXECUTION_CONTRACT_V1.json"
CONTRACT_SHA256 = "10d38f21b46d37819f4205a265662d011beebc1e778d6f658a97ad394fe935a2"
V18_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v18_pinned_atomic_link_regression_v1/E40_U29C_V18_PINNED_ATOMIC_LINK_REGRESSION_SPEC_V1.json"
V18_SPEC_SHA256 = "e35dcfc0b446a72be8e05e214989d8dc35d692722020152d20407cf023adf372"
REPORT = ROOT / "qa/e40_preproduction_20260808/u29c_v18_pinned_atomic_link_regression_v1/E40_U29C_V18_PINNED_ATOMIC_LINK_REGRESSION_MATRIX_V1.json"
CANONICAL_NAME = "E40_U29C_V18_PINNED_READER_CANONICAL_GATE_V1.json"
SHARED_NAME = "E40_U29C_V18_PINNED_SHARED_CONTENTION_GATE_V1.json"
CONTENDERS = 8
MAX_WORKERS = 4


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def root_identity(path: Path) -> list[int]:
    value = os.stat(path, follow_symlinks=False)
    return [value.st_dev, value.st_ino, stat.S_IMODE(value.st_mode)]


def valid_public(path: Path) -> bool:
    try:
        data = path.read_bytes()
        report = writer.validate_report_bytes(data)
        value = os.stat(path, follow_symlinks=False)
    except (OSError, writer.GateError):
        return False
    return len(data) > 0 and stat.S_ISREG(value.st_mode) and value.st_nlink == 1 and report.get("execution_permitted") is False


def stage_entries() -> list[str]:
    return sorted(path.name for path in writer.STAGING_ROOT.iterdir())


def hidden_entries() -> list[str]:
    return sorted(path.name for path in writer.FINAL_ROOT.iterdir() if path.name.startswith(".u29c-v17-hidden-"))


def run_process(name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(INVOKER), "--output-name", name],
        cwd=ROOT,
        capture_output=True,
        text=True,
        close_fds=True,
        check=False,
    )


def reader_case() -> dict[str, Any]:
    target = writer.FINAL_ROOT / CANONICAL_NAME
    initial_absent = not target.exists() and not target.is_symlink()
    process = subprocess.Popen(
        [sys.executable, str(INVOKER), "--output-name", CANONICAL_NAME],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        close_fds=True,
    )
    observations: list[dict[str, Any]] = []
    while process.poll() is None:
        if target.exists() or target.is_symlink():
            payload = target.read_bytes()
            observations.append({"size": len(payload), "valid": valid_public(target)})
        time.sleep(0.001)
    stdout, stderr = process.communicate()
    if target.exists() or target.is_symlink():
        payload = target.read_bytes()
        observations.append({"size": len(payload), "valid": valid_public(target)})
    all_valid = bool(observations) and all(item["size"] > 0 and item["valid"] for item in observations)
    wrapper_valid = False
    try:
        wrapper_valid = json.loads(stdout).get("invoker_status") == "PASS_PINNED_V17_ATOMIC_LINK_WRITER_NO_SUBMIT"
    except json.JSONDecodeError:
        pass
    return {
        "case_id": "FRESH_PINNED_CANONICAL_READER_VISIBILITY",
        "passed": initial_absent and process.returncode == 0 and wrapper_valid and all_valid and valid_public(target),
        "initial_public_absent": initial_absent,
        "returncode": process.returncode,
        "stderr": stderr.strip(),
        "observation_count": len(observations),
        "all_public_observations_complete_and_valid": all_valid,
        "final_public_valid": valid_public(target),
        "output_sha256": digest(target) if target.is_file() else None,
    }


def run_contender(index: int) -> dict[str, Any]:
    completed = run_process(SHARED_NAME)
    return {
        "contender": index,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def contention_case() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    target = writer.FINAL_ROOT / SHARED_NAME
    observations: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="u29c-v18") as executor:
        futures = [executor.submit(run_contender, index) for index in range(1, CONTENDERS + 1)]
        pending = set(futures)
        while pending:
            if target.exists() or target.is_symlink():
                payload = target.read_bytes()
                observations.append({"size": len(payload), "valid": valid_public(target)})
            completed_now = {future for future in pending if future.done()}
            for future in completed_now:
                results.append(future.result())
            pending -= completed_now
            if pending:
                time.sleep(0.001)
    results.sort(key=lambda item: item["contender"])
    if target.exists() or target.is_symlink():
        payload = target.read_bytes()
        observations.append({"size": len(payload), "valid": valid_public(target)})
    winners = [item for item in results if item["returncode"] == 0]
    losers = [item for item in results if item["returncode"] == 1 and item["stderr"] == "PUBLICATION_TARGET_EXISTS"]
    all_valid = bool(observations) and all(item["size"] > 0 and item["valid"] for item in observations)
    case = {
        "case_id": "EIGHT_PINNED_SAME_BASENAME_CONTENDERS_READER_SAFE",
        "passed": len(winners) == 1 and len(losers) == 7 and all_valid and valid_public(target),
        "winner_count": len(winners),
        "publication_target_exists_loser_count": len(losers),
        "reader_observation_count": len(observations),
        "all_public_observations_complete_and_valid": all_valid,
        "public_valid": valid_public(target),
        "output_sha256": digest(target) if target.is_file() else None,
    }
    return case, results


def substitution_case() -> dict[str, Any]:
    results = []
    for flag in ["--validator", "--contract", "--final-root", "--staging-root"]:
        name = f"E40_U29C_V18_REJECT_{flag[2:].replace('-', '_').upper()}.json"
        completed = subprocess.run(
            [sys.executable, str(INVOKER), "--output-name", name, flag, "/tmp/forbidden"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            close_fds=True,
            check=False,
        )
        results.append({"flag": flag, "returncode": completed.returncode, "output_absent": not (writer.FINAL_ROOT / name).exists()})
    return {
        "case_id": "PINNED_CALLER_SUBSTITUTIONS_REJECTED_BEFORE_CHILD",
        "passed": all(item["returncode"] == 2 and item["output_absent"] for item in results),
        "results": results,
    }


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        size = os.write(fd, view)
        if size <= 0:
            raise RuntimeError("REPORT_WRITE_FAILED")
        view = view[size:]


def write_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, writer.create_flags(), 0o600)
    try:
        data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
        write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> int:
    if REPORT.exists() or REPORT.is_symlink():
        raise SystemExit("REPORT_ALREADY_EXISTS")
    if CONTENDERS != 8 or MAX_WORKERS != 4:
        raise SystemExit("BOUNDED_REGRESSION_CONTRACT_MISMATCH")
    writer.verify_pins()
    writer.FINAL_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    writer.STAGING_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in [CANONICAL_NAME, SHARED_NAME]:
        if (writer.FINAL_ROOT / name).exists() or (writer.FINAL_ROOT / name).is_symlink():
            raise SystemExit(f"REGRESSION_OUTPUT_ALREADY_EXISTS_{name}")
    pins = [INVOKER, V17_WRITER, V17_MATRIX, VALIDATOR, CONTRACT, V18_SPEC]
    expected = {
        str(INVOKER.relative_to(ROOT)): INVOKER_SHA256,
        str(V17_WRITER.relative_to(ROOT)): V17_WRITER_SHA256,
        str(V17_MATRIX.relative_to(ROOT)): V17_MATRIX_SHA256,
        str(VALIDATOR.relative_to(ROOT)): VALIDATOR_SHA256,
        str(CONTRACT.relative_to(ROOT)): CONTRACT_SHA256,
        str(V18_SPEC.relative_to(ROOT)): V18_SPEC_SHA256,
    }
    pins_before = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    roots_before = {"final": root_identity(writer.FINAL_ROOT), "staging": root_identity(writer.STAGING_ROOT)}
    stage_before = stage_entries()
    hidden_before = hidden_entries()
    reader = reader_case()
    contention, contention_results = contention_case()
    cases = [reader, contention, substitution_case()]
    pins_after = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    roots_after = {"final": root_identity(writer.FINAL_ROOT), "staging": root_identity(writer.STAGING_ROOT)}
    stage_after = stage_entries()
    hidden_after = hidden_entries()
    failures = [case["case_id"] for case in cases if not case["passed"]]
    failures.extend(name for name, value in expected.items() if pins_before.get(name) != value)
    if pins_before != pins_after:
        failures.append("PINNED_INPUT_MUTATION")
    if roots_before != roots_after:
        failures.append("ROOT_IDENTITY_OR_MODE_DRIFT")
    if stage_before or stage_after or hidden_before or hidden_after:
        failures.append("HIDDEN_OR_STAGING_RESIDUE_NONZERO")
    status = "PASS_PINNED_ATOMIC_LINK_READER_CONTENTION_CLEANUP_REGRESSION_NO_SUBMIT" if not failures else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29c.v18.pinned_atomic_link_regression_matrix.v1",
        "episode": "E40",
        "unit_id": "U29C",
        "recorded_at": stamp(),
        "status": status,
        "execution_permitted": False,
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "bounded_load": {"contenders": CONTENDERS, "maximum_workers": MAX_WORKERS},
        "pins_before": pins_before,
        "pins_after": pins_after,
        "roots_before": roots_before,
        "roots_after": roots_after,
        "staging_entries_before": stage_before,
        "staging_entries_after": stage_after,
        "hidden_entries_before": hidden_before,
        "hidden_entries_after": hidden_after,
        "cases": cases,
        "contention_results": contention_results,
        "failures": failures,
        "side_effects": {"provider_calls": 0, "transactions": 0, "credits": 0, "retries": 0, "agentcut": 0, "assembly": 0},
        "next_action": "Keep execution closed. Register a V19 read-only source/static audit for atomic-link ownership cleanup exception safety and descriptor closure.",
    }
    write_exclusive(REPORT, payload)
    print(json.dumps({"status": status, "report": str(REPORT), "failures": failures}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
