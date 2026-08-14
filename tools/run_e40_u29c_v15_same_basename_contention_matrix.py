#!/usr/bin/env python3
"""Run eight V15 contenders against one atomically reserved basename."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
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
V14_MATRIX = ROOT / "qa/e40_preproduction_20260808/u29c_v14_concurrent_stage_isolation_v1/E40_U29C_V14_CONCURRENT_STAGE_ISOLATION_MATRIX_V1.json"
V14_MATRIX_SHA256 = "b9c1146254335e9f369a7b44e788cf9f202b20b9cbd40b32626fdf90f8340d5d"
V15_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v15_same_basename_contention_v1/E40_U29C_V15_SAME_BASENAME_CONTENTION_SPEC_V1.json"
V15_SPEC_SHA256 = "a25c5ebb4ef65f81a10cad4edd5ed5f3337a5d1e1122d64668e894fc4e4939f3"
OUTPUT_NAME = "E40_U29C_V15_SHARED_BASENAME_CONTENTION_GATE_V1.json"
CONTENDERS = 8
MAX_WORKERS = 4
REPORT = ROOT / "qa/e40_preproduction_20260808/u29c_v15_same_basename_contention_v1/E40_U29C_V15_SAME_BASENAME_CONTENTION_MATRIX_V1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stage_entries() -> list[str]:
    return sorted(path.name for path in writer.STAGING_ROOT.iterdir())


def final_entries() -> set[str]:
    return {path.name for path in writer.FINAL_ROOT.iterdir()}


def root_identity(path: Path) -> tuple[int, int, int]:
    value = os.stat(path, follow_symlinks=False)
    return value.st_dev, value.st_ino, stat.S_IMODE(value.st_mode)


def run_contender(index: int) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(INVOKER), "--output-name", OUTPUT_NAME],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "contender": index,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


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


def main() -> int:
    output = writer.FINAL_ROOT / OUTPUT_NAME
    if REPORT.exists() or REPORT.is_symlink():
        raise SystemExit("REPORT_ALREADY_EXISTS")
    if output.exists() or output.is_symlink():
        raise SystemExit("SHARED_OUTPUT_ALREADY_EXISTS")
    if CONTENDERS != 8 or MAX_WORKERS != 4:
        raise SystemExit("BOUNDED_CONTENTION_CONTRACT_MISMATCH")
    pins = [INVOKER, V12_WRITER, V14_MATRIX, V15_SPEC]
    expected = {
        str(INVOKER.relative_to(ROOT)): INVOKER_SHA256,
        str(V12_WRITER.relative_to(ROOT)): V12_WRITER_SHA256,
        str(V14_MATRIX.relative_to(ROOT)): V14_MATRIX_SHA256,
        str(V15_SPEC.relative_to(ROOT)): V15_SPEC_SHA256,
    }
    pins_before = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    pin_failures = [name for name, value in expected.items() if pins_before.get(name) != value]
    stage_before = stage_entries()
    final_before = final_entries()
    roots_before = {"final": root_identity(writer.FINAL_ROOT), "staging": root_identity(writer.STAGING_ROOT)}

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="u29c-v15") as executor:
        futures = [executor.submit(run_contender, index) for index in range(1, CONTENDERS + 1)]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item["contender"])

    winners = [item for item in results if item["returncode"] == 0]
    losers = [item for item in results if item["returncode"] != 0]
    exact_losers = [item for item in losers if item["returncode"] == 1 and item["stderr"] == "OUTPUT_RESERVATION_EXISTS"]
    final_after = final_entries()
    stage_after = stage_entries()
    roots_after = {"final": root_identity(writer.FINAL_ROOT), "staging": root_identity(writer.STAGING_ROOT)}
    pins_after = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    report = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    value = os.stat(output, follow_symlinks=False) if output.is_file() else None
    output_valid = (
        value is not None
        and stat.S_ISREG(value.st_mode)
        and value.st_nlink == 1
        and report.get("status") == "PASS_EXPECTED_FAIL_CLOSED_NO_SUBMIT"
        and report.get("execution_permitted") is False
    )
    additions = final_after - final_before
    winner_valid = len(winners) == 1 and "PASS_SEPARATE_STAGE_ATOMIC_RESERVED_FAIL_CLOSED_NO_SUBMIT" in winners[0]["stdout"]
    losers_valid = len(losers) == 7 and len(exact_losers) == 7
    no_overwrite = additions == {OUTPUT_NAME} and output_valid
    failures: list[str] = []
    failures.extend(pin_failures)
    if not winner_valid:
        failures.append("WINNER_COUNT_OR_RESULT_NOT_EXACTLY_ONE")
    if not losers_valid:
        failures.append("O_EXCL_LOSER_COUNT_OR_ERROR_NOT_EXACTLY_SEVEN")
    if not no_overwrite:
        failures.append("FINAL_OUTPUT_ADDITION_OR_VALIDITY_MISMATCH")
    if stage_before != [] or stage_after != []:
        failures.append("SHARED_STAGING_RESIDUE_NONZERO")
    if roots_before != roots_after:
        failures.append("ROOT_IDENTITY_OR_MODE_DRIFT")
    if pins_before != pins_after:
        failures.append("PINNED_INPUT_MUTATION")
    status = "PASS_1_WINNER_7_O_EXCL_LOSERS_ZERO_RESIDUE_NO_SUBMIT" if not failures else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29c.v15.same_basename_contention_matrix.v1",
        "episode": "E40",
        "unit_id": "U29C",
        "recorded_at": stamp(),
        "status": status,
        "execution_permitted": False,
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "bounded_load": {"contender_count": CONTENDERS, "maximum_workers": MAX_WORKERS},
        "shared_output": str(output.relative_to(ROOT)),
        "shared_output_sha256": digest(output) if output.is_file() else None,
        "shared_output_identity": [value.st_dev, value.st_ino] if value else None,
        "winner_count": len(winners),
        "o_excl_loser_count": len(exact_losers),
        "no_overwrite": no_overwrite,
        "final_entry_additions": sorted(additions),
        "staging_entries_before": stage_before,
        "staging_entries_after": stage_after,
        "roots_before": roots_before,
        "roots_after": roots_after,
        "pins_before": pins_before,
        "pins_after": pins_after,
        "results": results,
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
            "Keep execution closed. Register a local audit of reader-visible incomplete final content between "
            "reservation and commit, and define a fail-closed admission-marker contract."
        ),
    }
    write_exclusive(REPORT, payload)
    print(json.dumps({"status": status, "report": str(REPORT), "failures": failures}, ensure_ascii=False))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
