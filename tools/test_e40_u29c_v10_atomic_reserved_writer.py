#!/usr/bin/env python3
"""Run bounded local negatives for the U29C V10 atomic output writer."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v10_atomic_reserved_capability_gate as writer  # noqa: E402


TOOL = ROOT / "tools/run_e40_u29c_v10_atomic_reserved_capability_gate.py"
COMPETING_NAME = "E40_U29C_V10_COMPETING_RESERVATION_CANONICAL_GATE_V2.json"
SUMMARY = ROOT / "qa/e40_preproduction_20260808/u29c_v10_output_race_window_audit_v1/E40_U29C_V10_ATOMIC_RESERVED_WRITER_NEGATIVE_GATE_V2.json"
FIXTURE_PARENT = ROOT / "qa/e40_preproduction_20260808/u29c_v10_atomic_reserved_writer_negative_fixtures_v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_competing_invocations() -> dict:
    output = writer.OUTPUT_ROOT / COMPETING_NAME
    if output.exists() or output.is_symlink():
        raise SystemExit("COMPETING_TEST_OUTPUT_ALREADY_EXISTS")
    command = [sys.executable, str(TOOL), "--output-name", COMPETING_NAME]
    processes = [
        subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(2)
    ]
    results = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        results.append({"returncode": process.returncode, "stdout": stdout.strip(), "stderr": stderr.strip()})
    winners = [result for result in results if result["returncode"] == 0]
    losers = [result for result in results if result["returncode"] != 0]
    final = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    passed = (
        len(winners) == 1
        and len(losers) == 1
        and "PASS_ATOMIC_RESERVED_FAIL_CLOSED_NO_SUBMIT" in winners[0]["stdout"]
        and losers[0]["stderr"] == "OUTPUT_RESERVATION_EXISTS"
        and final.get("status") == "PASS_EXPECTED_FAIL_CLOSED_NO_SUBMIT"
        and final.get("execution_permitted") is False
    )
    return {
        "case": "TWO_CONCURRENT_INVOCATIONS_SAME_BASENAME",
        "passed": passed,
        "winner_count": len(winners),
        "loser_count": len(losers),
        "loser_error": losers[0]["stderr"] if len(losers) == 1 else None,
        "final_output": str(output.relative_to(ROOT)),
        "final_output_sha256": digest(output) if output.is_file() else None,
        "validator_status": final.get("status"),
        "execution_permitted": final.get("execution_permitted"),
    }


def valid_report_bytes() -> bytes:
    path = writer.OUTPUT_ROOT / COMPETING_NAME
    return path.read_bytes()


def destination_substitution_negative(base: Path) -> dict:
    root = base / "destination_substitution_root"
    root_fd = writer.open_bound_root(root)
    reservation = writer.reserve_output(root_fd, "target.json")
    sentinel = b"ATTACKER_SUBSTITUTION_MUST_REMAIN\n"
    try:
        os.unlink("target.json", dir_fd=root_fd)
        attacker_fd = os.open("target.json", writer.create_flags(), 0o600, dir_fd=root_fd)
        try:
            os.write(attacker_fd, sentinel)
            os.fsync(attacker_fd)
        finally:
            os.close(attacker_fd)
        error = None
        try:
            writer.commit_report(reservation, root, valid_report_bytes())
        except writer.GateError as exc:
            error = str(exc)
        cleanup_removed = writer.cleanup_reservation(reservation)
        preserved = (root / "target.json").read_bytes() == sentinel
        return {
            "case": "DESTINATION_SUBSTITUTION_AFTER_RESERVATION",
            "passed": error in {
                "OUTPUT_RESERVATION_FD_IDENTITY_DRIFT",
                "OUTPUT_RESERVATION_ENTRY_IDENTITY_DRIFT",
            } and not cleanup_removed and preserved,
            "error": error,
            "cleanup_removed_substitution": cleanup_removed,
            "substitution_preserved": preserved,
        }
    finally:
        os.close(reservation.output_fd)
        os.close(root_fd)


def root_swap_negative(base: Path) -> dict:
    root = base / "root_swap_target"
    root_fd = writer.open_bound_root(root)
    original = base / "root_swap_original"
    attacker = base / "root_swap_attacker"
    try:
        root.rename(original)
        attacker.mkdir(mode=0o700)
        root.symlink_to(attacker, target_is_directory=True)
        error = None
        try:
            writer.assert_root_identity(root, root_fd)
        except writer.GateError as exc:
            error = str(exc)
        return {
            "case": "OUTPUT_ROOT_SWAP_TO_SYMLINK",
            "passed": error == "OUTPUT_ROOT_IDENTITY_DRIFT",
            "error": error,
        }
    finally:
        os.close(root_fd)


def malformed_report_negative(base: Path) -> dict:
    root = base / "malformed_report_root"
    root_fd = writer.open_bound_root(root)
    reservation = writer.reserve_output(root_fd, "target.json")
    try:
        error = None
        try:
            writer.commit_report(reservation, root, b"{malformed-json")
        except writer.GateError as exc:
            error = str(exc)
        cleanup_removed = writer.cleanup_reservation(reservation)
        absent = not (root / "target.json").exists()
        return {
            "case": "MALFORMED_CHILD_REPORT",
            "passed": error == "STAGED_REPORT_INVALID_JSON" and cleanup_removed and absent,
            "error": error,
            "owned_reservation_removed": cleanup_removed,
            "completed_gate_absent": absent,
        }
    finally:
        os.close(reservation.output_fd)
        os.close(root_fd)


def write_exclusive(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> int:
    if SUMMARY.exists() or SUMMARY.is_symlink():
        raise SystemExit("SUMMARY_ALREADY_EXISTS")
    pin_paths = [writer.VALIDATOR, writer.CONTRACT, writer.V10_AUDIT]
    pins_before = {str(path.relative_to(ROOT)): digest(path) for path in pin_paths}
    competition = run_competing_invocations()
    FIXTURE_PARENT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bounded-v10-", dir=FIXTURE_PARENT) as temporary:
        base = Path(temporary)
        substitution = destination_substitution_negative(base)
        root_swap = root_swap_negative(base)
        malformed = malformed_report_negative(base)
    pins_after = {str(path.relative_to(ROOT)): digest(path) for path in pin_paths}
    cases = [competition, substitution, root_swap, malformed]
    failures = [case["case"] for case in cases if not case["passed"]]
    if pins_before != pins_after:
        failures.append("PINNED_INPUT_MUTATION")
    status = "PASS_ATOMIC_RESERVATION_AND_REQUIRED_NEGATIVES_NO_SUBMIT" if not failures else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29c.v10.atomic_reserved_writer_negative_gate.v2",
        "episode": "E40",
        "unit_id": "U29C",
        "recorded_at": now(),
        "status": status,
        "execution_permitted": False,
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "writer": str(TOOL.relative_to(ROOT)),
        "writer_sha256": digest(TOOL),
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
            "Keep execution closed. Register a local successor to pin this writer by exact SHA and reject "
            "caller substitution or descriptor-boundary regressions before any future use."
        ),
    }
    write_exclusive(SUMMARY, payload)
    print(json.dumps({"status": status, "summary": str(SUMMARY), "failures": failures}, ensure_ascii=False))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
