#!/usr/bin/env python3
"""Bounded reader/contention/cleanup matrix for the U29C V17 writer."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as writer  # noqa: E402


WRITER = ROOT / "tools/run_e40_u29c_v17_atomic_link_publish_gate.py"
WRITER_SHA256 = "7728588e210ae17f61cc1c08eef6a18fdd3dfdba3e6cc1e77e61e2f8ae1778d8"
V16_AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v16_reader_visibility_atomic_publish_v1/E40_U29C_V16_READER_VISIBILITY_ATOMIC_LINK_AUDIT_V1.json"
V16_AUDIT_SHA256 = "d0e84552954e1614f42649e429e4aafa1b773d30a4221f12bf38e23f49c2a0bc"
V17_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v17_atomic_link_writer_v1/E40_U29C_V17_ATOMIC_LINK_WRITER_IMPLEMENTATION_SPEC_V1.json"
V17_SPEC_SHA256 = "f9f947270986b3488206665694b3e4c94ae148163a3b8066e453f4d7ea9519a1"
REPORT = ROOT / "qa/e40_preproduction_20260808/u29c_v17_atomic_link_writer_v1/E40_U29C_V17_ATOMIC_LINK_READER_CONTENTION_MATRIX_V1.json"
CANONICAL_NAME = "E40_U29C_V17_READER_SAFE_CANONICAL_GATE_V1.json"
READER_NAME = "E40_U29C_V17_READER_OBSERVER_GATE_V1.json"
SHARED_NAME = "E40_U29C_V17_SHARED_CONTENTION_GATE_V1.json"
CONTENDERS = 8
MAX_WORKERS = 4


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def valid_public(path: Path) -> bool:
    try:
        data = path.read_bytes()
        report = writer.validate_report_bytes(data)
        value = os.stat(path, follow_symlinks=False)
    except (OSError, writer.GateError):
        return False
    return len(data) > 0 and stat.S_ISREG(value.st_mode) and value.st_nlink == 1 and report["execution_permitted"] is False


def root_identity(path: Path) -> list[int]:
    value = os.stat(path, follow_symlinks=False)
    return [value.st_dev, value.st_ino, stat.S_IMODE(value.st_mode)]


def stage_entries() -> list[str]:
    return sorted(path.name for path in writer.STAGING_ROOT.iterdir())


def hidden_entries() -> list[str]:
    return sorted(path.name for path in writer.FINAL_ROOT.iterdir() if path.name.startswith(".u29c-v17-hidden-"))


def reader_case() -> dict[str, Any]:
    target = writer.FINAL_ROOT / READER_NAME
    initial_absent = not target.exists() and not target.is_symlink()
    process = subprocess.Popen(
        [sys.executable, str(WRITER), "--output-name", READER_NAME],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        close_fds=True,
    )
    observations: list[dict[str, Any]] = []
    while process.poll() is None:
        if target.exists() or target.is_symlink():
            data = target.read_bytes()
            observations.append({"size": len(data), "valid": valid_public(target)})
        time.sleep(0.002)
    stdout, stderr = process.communicate()
    if target.exists() or target.is_symlink():
        data = target.read_bytes()
        observations.append({"size": len(data), "valid": valid_public(target)})
    passed = initial_absent and process.returncode == 0 and bool(observations) and all(item["size"] > 0 and item["valid"] for item in observations)
    return {
        "case_id": "READER_NEVER_OBSERVES_PUBLIC_BASENAME_BEFORE_COMPLETE_COMMIT",
        "passed": passed,
        "initial_public_absent": initial_absent,
        "returncode": process.returncode,
        "stdout": stdout.strip(),
        "stderr": stderr.strip(),
        "observation_count": len(observations),
        "all_public_observations_complete_and_valid": bool(observations) and all(item["size"] > 0 and item["valid"] for item in observations),
        "final_public_valid": valid_public(target),
    }


def run_contender(index: int) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(WRITER), "--output-name", SHARED_NAME],
        cwd=ROOT,
        capture_output=True,
        text=True,
        close_fds=True,
        check=False,
    )
    return {"contender": index, "returncode": completed.returncode, "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}


def contention_case(final_before: set[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="u29c-v17") as executor:
        futures = [executor.submit(run_contender, index) for index in range(1, CONTENDERS + 1)]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item["contender"])
    winners = [item for item in results if item["returncode"] == 0]
    losers = [item for item in results if item["returncode"] != 0]
    exact_losers = [item for item in losers if item["returncode"] == 1 and item["stderr"] == "PUBLICATION_TARGET_EXISTS"]
    additions = {path.name for path in writer.FINAL_ROOT.iterdir()} - final_before
    target = writer.FINAL_ROOT / SHARED_NAME
    passed = len(winners) == 1 and len(exact_losers) == 7 and valid_public(target) and additions == {READER_NAME, SHARED_NAME}
    return ({
        "case_id": "EIGHT_SAME_BASENAME_CONTENDERS_ONE_WINNER_SEVEN_LINK_EEXIST_LOSERS",
        "passed": passed,
        "winner_count": len(winners),
        "publication_target_exists_loser_count": len(exact_losers),
        "public_valid": valid_public(target),
        "final_entry_additions_since_matrix_start": sorted(additions),
    }, results)


def write_fd(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        size = os.write(fd, view)
        if size <= 0:
            raise RuntimeError("FIXTURE_WRITE_FAILED")
        view = view[size:]


def fixture_cases(payload: bytes) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix=".u29c-v17-fixture-", dir=writer.QA_EPISODE_ROOT) as temporary:
        base = Path(temporary)
        compete_path = base / "competing-final"
        compete = writer.open_bound_root(compete_path)
        try:
            public_name = "public.json"
            sentinel = b"COMPETING_PUBLIC_MUST_REMAIN\n"
            fd = os.open(public_name, writer.create_flags(), 0o600, dir_fd=compete.fd)
            try:
                write_fd(fd, sentinel)
                os.fsync(fd)
            finally:
                os.close(fd)
            error = None
            try:
                writer.publish_complete_payload(compete, public_name, payload)
            except writer.GateError as exc:
                error = str(exc)
            preserved = (compete_path / public_name).read_bytes() == sentinel
            competing_case = {
                "case_id": "COMPETING_PUBLIC_ENTRY_PRESERVED_WITHOUT_OVERWRITE",
                "passed": error == "PUBLICATION_TARGET_EXISTS" and preserved,
                "error": error,
                "sentinel_preserved": preserved,
            }
        finally:
            os.close(compete.fd)

        malformed_path = base / "malformed-final"
        malformed = writer.open_bound_root(malformed_path)
        try:
            error = None
            try:
                writer.publish_complete_payload(malformed, "public.json", b"{malformed-json")
            except writer.GateError as exc:
                error = str(exc)
            public_absent = not (malformed_path / "public.json").exists()
            residue = [path.name for path in malformed_path.iterdir()]
            malformed_case = {
                "case_id": "MALFORMED_PAYLOAD_NEVER_PUBLISHED",
                "passed": error == "STAGED_REPORT_INVALID_JSON" and public_absent and residue == [],
                "error": error,
                "public_absent": public_absent,
                "residue": residue,
            }
        finally:
            os.close(malformed.fd)
    return [competing_case, malformed_case]


def child_boundary_case() -> dict[str, Any]:
    stage_name = ".u29c-v17-stage-static"
    command = writer.build_validator_command(stage_name, "validated_report.json")
    joined = "\0".join(command)
    forbidden = [str(writer.FINAL_ROOT), CANONICAL_NAME, SHARED_NAME, ".u29c-v17-hidden-", "final_fd"]
    passed = str(writer.STAGING_ROOT) in joined and all(value not in joined for value in forbidden)
    return {
        "case_id": "CHILD_COMMAND_EXPOSES_ONLY_PRIVATE_STAGING_PATH_AND_CLOSE_FDS",
        "passed": passed,
        "command": command,
        "close_fds": True,
        "forbidden_values_absent": all(value not in joined for value in forbidden),
    }


def substitution_case() -> dict[str, Any]:
    results = []
    for flag in ["--validator", "--contract", "--final-root", "--staging-root"]:
        name = f"E40_U29C_V17_REJECT_{flag[2:].replace('-', '_').upper()}.json"
        completed = subprocess.run(
            [sys.executable, str(WRITER), "--output-name", name, flag, "/tmp/forbidden"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            close_fds=True,
            check=False,
        )
        results.append({"flag": flag, "returncode": completed.returncode, "output_absent": not (writer.FINAL_ROOT / name).exists()})
    passed = all(item["returncode"] == 2 and item["output_absent"] for item in results)
    return {"case_id": "CALLER_SUBSTITUTIONS_REJECTED_BEFORE_CHILD", "passed": passed, "results": results}


def write_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, writer.create_flags(), 0o600)
    try:
        data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
        write_fd(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> int:
    if REPORT.exists() or REPORT.is_symlink():
        raise SystemExit("REPORT_ALREADY_EXISTS")
    if CONTENDERS != 8 or MAX_WORKERS != 4:
        raise SystemExit("BOUNDED_CONTENTION_CONTRACT_MISMATCH")
    canonical = writer.FINAL_ROOT / CANONICAL_NAME
    if not valid_public(canonical):
        raise SystemExit("CANONICAL_OUTPUT_MISSING_OR_INVALID")
    for name in [READER_NAME, SHARED_NAME]:
        if (writer.FINAL_ROOT / name).exists() or (writer.FINAL_ROOT / name).is_symlink():
            raise SystemExit(f"TEST_OUTPUT_ALREADY_EXISTS_{name}")
    pins = [WRITER, V16_AUDIT, V17_SPEC]
    expected = {
        str(WRITER.relative_to(ROOT)): WRITER_SHA256,
        str(V16_AUDIT.relative_to(ROOT)): V16_AUDIT_SHA256,
        str(V17_SPEC.relative_to(ROOT)): V17_SPEC_SHA256,
    }
    pins_before = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    root_before = {"final": root_identity(writer.FINAL_ROOT), "staging": root_identity(writer.STAGING_ROOT)}
    stage_before = stage_entries()
    hidden_before = hidden_entries()
    final_before = {path.name for path in writer.FINAL_ROOT.iterdir()}
    reader = reader_case()
    contention, results = contention_case(final_before)
    payload = canonical.read_bytes()
    cases = [
        {"case_id": "CANONICAL_PUBLIC_GATE_COMPLETE_AND_EXECUTION_FALSE", "passed": valid_public(canonical), "sha256": digest(canonical)},
        reader,
        contention,
        *fixture_cases(payload),
        child_boundary_case(),
        substitution_case(),
    ]
    pins_after = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    root_after = {"final": root_identity(writer.FINAL_ROOT), "staging": root_identity(writer.STAGING_ROOT)}
    stage_after = stage_entries()
    hidden_after = hidden_entries()
    failures = [case["case_id"] for case in cases if not case["passed"]]
    failures.extend(name for name, expected_sha in expected.items() if pins_before.get(name) != expected_sha)
    if pins_before != pins_after:
        failures.append("PINNED_INPUT_MUTATION")
    if root_before != root_after:
        failures.append("ROOT_IDENTITY_OR_MODE_DRIFT")
    if stage_before or stage_after or hidden_before or hidden_after:
        failures.append("HIDDEN_OR_STAGING_RESIDUE_NONZERO")
    status = "PASS_ATOMIC_LINK_READER_CONTENTION_CLEANUP_NO_SUBMIT" if not failures else "FAIL"
    report = {
        "schema": "qingshan.e40.u29c.v17.atomic_link_reader_contention_matrix.v1",
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
        "roots_before": root_before,
        "roots_after": root_after,
        "staging_entries_before": stage_before,
        "staging_entries_after": stage_after,
        "hidden_entries_before": hidden_before,
        "hidden_entries_after": hidden_after,
        "cases": cases,
        "contention_results": results,
        "failures": failures,
        "side_effects": {"provider_calls": 0, "transactions": 0, "credits": 0, "retries": 0, "agentcut": 0, "assembly": 0},
        "next_action": "Keep execution closed. Register a pinned V18 atomic-link regression invoker and rerun bounded reader/contention/residue checks locally.",
    }
    write_exclusive(REPORT, report)
    print(json.dumps({"status": status, "report": str(REPORT), "failures": failures}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
