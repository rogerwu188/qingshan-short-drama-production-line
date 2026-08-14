#!/usr/bin/env python3
"""Run the U29C fail-closed capability gate with atomic output reservation.

The validator runs only in a private staging directory.  The final output is
created once with O_EXCL and populated through the retained descriptor after
all pins and staged JSON have been verified.  No provider API is called.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools/validate_e40_u29c_v6_capability_contract.py"
VALIDATOR_SHA256 = "ebf2275931a09cd51dbb00af8268959faea62e1885b5b3a24be11d6c00fd87e5"
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u29c_v6_changed_representation_no_submit_v1/E40_U29C_V6_PROVIDER_CAPABILITY_AND_EXECUTION_CONTRACT_V1.json"
CONTRACT_SHA256 = "10d38f21b46d37819f4205a265662d011beebc1e778d6f658a97ad394fe935a2"
V10_AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v10_output_race_window_audit_v1/E40_U29C_V10_OUTPUT_RACE_WINDOW_AND_ATOMIC_RESERVATION_CONTRACT_V1.json"
V10_AUDIT_SHA256 = "988a1d6619a49fadd3ff3072952a2301ea0f18731d4048ba0ede8630216cd90f"
OUTPUT_ROOT = ROOT / "qa/e40_preproduction_20260808/u29c_v10_atomic_reserved_writer_v1"
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json\Z")


class GateError(RuntimeError):
    """Expected fail-closed gate error."""


@dataclass
class Reservation:
    root_fd: int
    output_fd: int
    output_name: str
    token: tuple[int, int]
    finalized: bool = False


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def directory_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def create_flags() -> int:
    return os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)


def reject_symlink_components(path: Path) -> None:
    current = ROOT
    for part in path.relative_to(ROOT).parts:
        current /= part
        if current.exists() and current.is_symlink():
            raise GateError("OUTPUT_COMPONENT_SYMLINK_FORBIDDEN")


def open_bound_root(path: Path) -> int:
    reject_symlink_components(path)
    path.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, directory_flags())
    try:
        disk = os.stat(path, follow_symlinks=False)
        opened = os.fstat(fd)
        if not stat.S_ISDIR(disk.st_mode) or not stat.S_ISDIR(opened.st_mode):
            raise GateError("OUTPUT_ROOT_NOT_DIRECTORY")
        if identity(disk) != identity(opened):
            raise GateError("OUTPUT_ROOT_IDENTITY_MISMATCH")
        return fd
    except Exception:
        os.close(fd)
        raise


def assert_root_identity(path: Path, root_fd: int) -> None:
    try:
        lexical = os.stat(path, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise GateError("OUTPUT_ROOT_MISSING_AFTER_BIND") from exc
    opened = os.fstat(root_fd)
    if not stat.S_ISDIR(lexical.st_mode) or identity(lexical) != identity(opened):
        raise GateError("OUTPUT_ROOT_IDENTITY_DRIFT")


def entry_identity(root_fd: int, name: str) -> tuple[int, int] | None:
    try:
        value = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return identity(value)


def reserve_output(root_fd: int, output_name: str) -> Reservation:
    if not SAFE_NAME.fullmatch(output_name):
        raise GateError("OUTPUT_NAME_MUST_BE_SAFE_JSON_BASENAME")
    try:
        output_fd = os.open(output_name, create_flags(), 0o600, dir_fd=root_fd)
    except FileExistsError as exc:
        raise GateError("OUTPUT_RESERVATION_EXISTS") from exc
    opened = os.fstat(output_fd)
    token = identity(opened)
    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
        os.close(output_fd)
        raise GateError("OUTPUT_RESERVATION_NOT_PRIVATE_REGULAR_FILE")
    if entry_identity(root_fd, output_name) != token:
        os.close(output_fd)
        raise GateError("OUTPUT_RESERVATION_TOKEN_MISMATCH")
    return Reservation(root_fd=root_fd, output_fd=output_fd, output_name=output_name, token=token)


def assert_reservation_owned(reservation: Reservation) -> None:
    opened = os.fstat(reservation.output_fd)
    if identity(opened) != reservation.token or opened.st_nlink != 1:
        raise GateError("OUTPUT_RESERVATION_FD_IDENTITY_DRIFT")
    if entry_identity(reservation.root_fd, reservation.output_name) != reservation.token:
        raise GateError("OUTPUT_RESERVATION_ENTRY_IDENTITY_DRIFT")


def cleanup_reservation(reservation: Reservation) -> bool:
    if reservation.finalized:
        return False
    if entry_identity(reservation.root_fd, reservation.output_name) != reservation.token:
        return False
    os.unlink(reservation.output_name, dir_fd=reservation.root_fd)
    os.fsync(reservation.root_fd)
    return True


def validate_report_bytes(data: bytes) -> dict[str, Any]:
    try:
        report = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("STAGED_REPORT_INVALID_JSON") from exc
    side_effects = report.get("side_effects") or {}
    required_zero = ["provider_calls", "transactions", "credits", "retries", "agentcut", "assembly"]
    valid = (
        report.get("status") == "PASS_EXPECTED_FAIL_CLOSED_NO_SUBMIT"
        and report.get("execution_permitted") is False
        and report.get("contract_closed") is True
        and report.get("failures") == []
        and all(side_effects.get(name) == 0 for name in required_zero)
    )
    if not valid:
        raise GateError("STAGED_REPORT_FAIL_CLOSED_CONTRACT_MISMATCH")
    return report


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise GateError("OUTPUT_DESCRIPTOR_WRITE_FAILED")
        view = view[written:]


def commit_report(reservation: Reservation, output_root: Path, data: bytes) -> dict[str, Any]:
    report = validate_report_bytes(data)
    assert_root_identity(output_root, reservation.root_fd)
    assert_reservation_owned(reservation)
    os.lseek(reservation.output_fd, 0, os.SEEK_SET)
    write_all(reservation.output_fd, data)
    os.fsync(reservation.output_fd)
    assert_root_identity(output_root, reservation.root_fd)
    assert_reservation_owned(reservation)
    os.fsync(reservation.root_fd)
    reservation.finalized = True
    return report


def create_private_stage(root_fd: int) -> tuple[str, int]:
    for _ in range(16):
        name = f".u29c-v10-stage-{secrets.token_hex(12)}"
        try:
            os.mkdir(name, 0o700, dir_fd=root_fd)
        except FileExistsError:
            continue
        stage_fd = os.open(name, directory_flags(), dir_fd=root_fd)
        opened = os.fstat(stage_fd)
        lexical = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if identity(opened) != identity(lexical) or not stat.S_ISDIR(opened.st_mode):
            os.close(stage_fd)
            raise GateError("STAGE_IDENTITY_MISMATCH")
        return name, stage_fd
    raise GateError("STAGE_EXCLUSIVE_CREATE_EXHAUSTED")


def assert_stage_identity(root_fd: int, stage_name: str, stage_fd: int) -> None:
    try:
        lexical = os.stat(stage_name, dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise GateError("STAGE_MISSING_AFTER_BIND") from exc
    opened = os.fstat(stage_fd)
    if not stat.S_ISDIR(lexical.st_mode) or identity(lexical) != identity(opened):
        raise GateError("STAGE_IDENTITY_DRIFT")


def read_stage_file(stage_fd: int, name: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, dir_fd=stage_fd)
    try:
        value = os.fstat(fd)
        if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
            raise GateError("STAGED_REPORT_NOT_PRIVATE_REGULAR_FILE")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def cleanup_stage(root_fd: int, stage_name: str, stage_fd: int) -> None:
    try:
        for name in os.listdir(stage_fd):
            value = os.stat(name, dir_fd=stage_fd, follow_symlinks=False)
            if stat.S_ISDIR(value.st_mode):
                raise GateError("UNEXPECTED_STAGE_SUBDIRECTORY")
            os.unlink(name, dir_fd=stage_fd)
    finally:
        os.close(stage_fd)
    os.rmdir(stage_name, dir_fd=root_fd)


def run_validator_in_stage(root_fd: int, stage_name: str, stage_fd: int) -> bytes:
    staged_name = "validated_report.json"
    assert_stage_identity(root_fd, stage_name, stage_fd)
    completed = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--contract",
            str(CONTRACT),
            "--out",
            str(OUTPUT_ROOT / stage_name / staged_name),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise GateError(f"PINNED_VALIDATOR_FAILED_EXIT_{completed.returncode}")
    assert_stage_identity(root_fd, stage_name, stage_fd)
    return read_stage_file(stage_fd, staged_name)


def verify_pins() -> None:
    pins = [
        (VALIDATOR, VALIDATOR_SHA256, "PINNED_VALIDATOR_SHA_MISMATCH"),
        (CONTRACT, CONTRACT_SHA256, "PINNED_CONTRACT_SHA_MISMATCH"),
        (V10_AUDIT, V10_AUDIT_SHA256, "PINNED_V10_AUDIT_SHA_MISMATCH"),
    ]
    for path, expected, code in pins:
        if digest(path) != expected:
            raise GateError(code)


def execute(output_name: str) -> dict[str, Any]:
    verify_pins()
    root_fd = open_bound_root(OUTPUT_ROOT)
    reservation: Reservation | None = None
    stage_name: str | None = None
    stage_fd: int | None = None
    try:
        assert_root_identity(OUTPUT_ROOT, root_fd)
        reservation = reserve_output(root_fd, output_name)
        stage_name, stage_fd = create_private_stage(root_fd)
        assert_root_identity(OUTPUT_ROOT, root_fd)
        data = run_validator_in_stage(root_fd, stage_name, stage_fd)
        assert_root_identity(OUTPUT_ROOT, root_fd)
        cleanup_stage(root_fd, stage_name, stage_fd)
        stage_name = None
        stage_fd = None
        report = commit_report(reservation, OUTPUT_ROOT, data)
        return {
            "wrapper_status": "PASS_ATOMIC_RESERVED_FAIL_CLOSED_NO_SUBMIT",
            "output": str(OUTPUT_ROOT / output_name),
            "output_sha256": digest(OUTPUT_ROOT / output_name),
            "validator_status": report["status"],
            "execution_permitted": False,
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
        }
    except Exception:
        if stage_fd is not None and stage_name is not None:
            cleanup_stage(root_fd, stage_name, stage_fd)
        if reservation is not None:
            cleanup_reservation(reservation)
        raise
    finally:
        if reservation is not None:
            os.close(reservation.output_fd)
        os.close(root_fd)


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--output-name", required=True)
    args = parser.parse_args()
    try:
        result = execute(args.output_name)
    except GateError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
