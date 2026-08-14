#!/usr/bin/env python3
"""Run the U29C closed capability gate with separate final/staging roots."""

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
QA_EPISODE_ROOT = ROOT / "qa/e40_preproduction_20260808"
FINAL_ROOT = QA_EPISODE_ROOT / "u29c_v12_atomic_final_output_v1"
STAGING_ROOT = QA_EPISODE_ROOT / "u29c_v12_private_staging_root_v1"
VALIDATOR = ROOT / "tools/validate_e40_u29c_v6_capability_contract.py"
VALIDATOR_SHA256 = "ebf2275931a09cd51dbb00af8268959faea62e1885b5b3a24be11d6c00fd87e5"
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u29c_v6_changed_representation_no_submit_v1/E40_U29C_V6_PROVIDER_CAPABILITY_AND_EXECUTION_CONTRACT_V1.json"
CONTRACT_SHA256 = "10d38f21b46d37819f4205a265662d011beebc1e778d6f658a97ad394fe935a2"
V11_AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v11_atomic_writer_pinning_v1/E40_U29C_V11_PINNED_WRITER_BOUNDARY_AUDIT_V1.json"
V11_AUDIT_SHA256 = "95ffbbcb655cc7899a1a17b8ad66b9eb64578d3b2072f452fd58c17e69bbd4f4"
V12_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v12_separate_staging_root_v1/E40_U29C_V12_SEPARATE_STAGING_ROOT_HARDENING_SPEC_V1.json"
V12_SPEC_SHA256 = "5c6d3c9aa1384f347cbf1afce6a0eb02096a7190a16ad002b64bded0975eee6e"
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json\Z")


class GateError(RuntimeError):
    """Expected fail-closed gate error."""


@dataclass
class RootBinding:
    path: Path
    fd: int
    token: tuple[int, int]


@dataclass
class Reservation:
    root: RootBinding
    fd: int
    name: str
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
        if current.is_symlink():
            raise GateError("ROOT_COMPONENT_SYMLINK_FORBIDDEN")


def open_bound_root(path: Path) -> RootBinding:
    reject_symlink_components(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, directory_flags())
    try:
        lexical = os.stat(path, follow_symlinks=False)
        opened = os.fstat(fd)
        if not stat.S_ISDIR(lexical.st_mode) or not stat.S_ISDIR(opened.st_mode):
            raise GateError("BOUND_ROOT_NOT_DIRECTORY")
        if identity(lexical) != identity(opened):
            raise GateError("BOUND_ROOT_IDENTITY_MISMATCH")
        if stat.S_IMODE(opened.st_mode) & 0o077:
            raise GateError("BOUND_ROOT_NOT_PRIVATE_0700")
        return RootBinding(path=path, fd=fd, token=identity(opened))
    except Exception:
        os.close(fd)
        raise


def assert_root_identity(binding: RootBinding) -> None:
    try:
        lexical = os.stat(binding.path, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise GateError("BOUND_ROOT_MISSING") from exc
    opened = os.fstat(binding.fd)
    if (
        not stat.S_ISDIR(lexical.st_mode)
        or identity(lexical) != binding.token
        or identity(opened) != binding.token
        or stat.S_IMODE(opened.st_mode) & 0o077
    ):
        raise GateError("BOUND_ROOT_IDENTITY_DRIFT")


def assert_distinct_roots(final_root: RootBinding, staging_root: RootBinding) -> None:
    if final_root.token == staging_root.token:
        raise GateError("FINAL_AND_STAGING_ROOT_INODES_NOT_DISTINCT")
    final_rel = final_root.path.relative_to(QA_EPISODE_ROOT)
    staging_rel = staging_root.path.relative_to(QA_EPISODE_ROOT)
    if not final_rel.parts or not staging_rel.parts or final_rel.parts[0] == staging_rel.parts[0]:
        raise GateError("FINAL_AND_STAGING_ROOTS_SHARE_CHILD_ANCESTOR")


def entry_identity(binding: RootBinding, name: str) -> tuple[int, int] | None:
    try:
        value = os.stat(name, dir_fd=binding.fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return identity(value)


def reserve_output(binding: RootBinding, name: str) -> Reservation:
    if not SAFE_NAME.fullmatch(name):
        raise GateError("OUTPUT_NAME_MUST_BE_SAFE_JSON_BASENAME")
    try:
        fd = os.open(name, create_flags(), 0o600, dir_fd=binding.fd)
    except FileExistsError as exc:
        raise GateError("OUTPUT_RESERVATION_EXISTS") from exc
    opened = os.fstat(fd)
    token = identity(opened)
    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or entry_identity(binding, name) != token:
        os.close(fd)
        raise GateError("OUTPUT_RESERVATION_IDENTITY_INVALID")
    return Reservation(root=binding, fd=fd, name=name, token=token)


def assert_reservation_owned(reservation: Reservation) -> None:
    opened = os.fstat(reservation.fd)
    if identity(opened) != reservation.token or opened.st_nlink != 1:
        raise GateError("OUTPUT_RESERVATION_FD_IDENTITY_DRIFT")
    if entry_identity(reservation.root, reservation.name) != reservation.token:
        raise GateError("OUTPUT_RESERVATION_ENTRY_IDENTITY_DRIFT")


def cleanup_reservation(reservation: Reservation) -> bool:
    if reservation.finalized or entry_identity(reservation.root, reservation.name) != reservation.token:
        return False
    os.unlink(reservation.name, dir_fd=reservation.root.fd)
    os.fsync(reservation.root.fd)
    return True


def create_stage(binding: RootBinding) -> tuple[str, int, tuple[int, int]]:
    for _ in range(16):
        name = f".u29c-v12-stage-{secrets.token_hex(12)}"
        try:
            os.mkdir(name, 0o700, dir_fd=binding.fd)
        except FileExistsError:
            continue
        fd = os.open(name, directory_flags(), dir_fd=binding.fd)
        opened = os.fstat(fd)
        lexical = os.stat(name, dir_fd=binding.fd, follow_symlinks=False)
        token = identity(opened)
        if identity(lexical) != token or not stat.S_ISDIR(opened.st_mode) or stat.S_IMODE(opened.st_mode) & 0o077:
            os.close(fd)
            raise GateError("STAGE_IDENTITY_INVALID")
        return name, fd, token
    raise GateError("STAGE_EXCLUSIVE_CREATE_EXHAUSTED")


def assert_stage_identity(binding: RootBinding, name: str, fd: int, token: tuple[int, int]) -> None:
    try:
        lexical = os.stat(name, dir_fd=binding.fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise GateError("STAGE_MISSING") from exc
    opened = os.fstat(fd)
    if not stat.S_ISDIR(lexical.st_mode) or identity(lexical) != token or identity(opened) != token:
        raise GateError("STAGE_IDENTITY_DRIFT")


def read_stage_file(stage_fd: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=stage_fd)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise GateError("STAGED_REPORT_NOT_PRIVATE_REGULAR_FILE")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(fd)


def cleanup_stage(binding: RootBinding, name: str, fd: int, token: tuple[int, int]) -> None:
    assert_stage_identity(binding, name, fd, token)
    try:
        for child in os.listdir(fd):
            opened = os.stat(child, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(opened.st_mode):
                raise GateError("UNEXPECTED_STAGE_SUBDIRECTORY")
            os.unlink(child, dir_fd=fd)
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=binding.fd)


def validate_report_bytes(data: bytes) -> dict[str, Any]:
    try:
        report = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("STAGED_REPORT_INVALID_JSON") from exc
    side_effects = report.get("side_effects") or {}
    zeros = ["provider_calls", "transactions", "credits", "retries", "agentcut", "assembly"]
    valid = (
        report.get("status") == "PASS_EXPECTED_FAIL_CLOSED_NO_SUBMIT"
        and report.get("execution_permitted") is False
        and report.get("contract_closed") is True
        and report.get("failures") == []
        and all(side_effects.get(name) == 0 for name in zeros)
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


def commit_report(reservation: Reservation, data: bytes) -> dict[str, Any]:
    report = validate_report_bytes(data)
    assert_root_identity(reservation.root)
    assert_reservation_owned(reservation)
    os.lseek(reservation.fd, 0, os.SEEK_SET)
    write_all(reservation.fd, data)
    os.fsync(reservation.fd)
    assert_root_identity(reservation.root)
    assert_reservation_owned(reservation)
    os.fsync(reservation.root.fd)
    reservation.finalized = True
    return report


def run_validator(staging: RootBinding, stage_name: str, stage_fd: int, stage_token: tuple[int, int]) -> bytes:
    staged_name = "validated_report.json"
    assert_root_identity(staging)
    assert_stage_identity(staging, stage_name, stage_fd, stage_token)
    completed = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--contract",
            str(CONTRACT),
            "--out",
            str(STAGING_ROOT / stage_name / staged_name),
        ],
        cwd=ROOT,
        close_fds=True,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise GateError(f"PINNED_VALIDATOR_FAILED_EXIT_{completed.returncode}")
    assert_root_identity(staging)
    assert_stage_identity(staging, stage_name, stage_fd, stage_token)
    return read_stage_file(stage_fd, staged_name)


def verify_pins() -> None:
    pins = [
        (VALIDATOR, VALIDATOR_SHA256, "PINNED_VALIDATOR_SHA_MISMATCH"),
        (CONTRACT, CONTRACT_SHA256, "PINNED_CONTRACT_SHA_MISMATCH"),
        (V11_AUDIT, V11_AUDIT_SHA256, "PINNED_V11_AUDIT_SHA_MISMATCH"),
        (V12_SPEC, V12_SPEC_SHA256, "PINNED_V12_SPEC_SHA_MISMATCH"),
    ]
    for path, expected, code in pins:
        if digest(path) != expected:
            raise GateError(code)


def execute(output_name: str) -> dict[str, Any]:
    verify_pins()
    final = open_bound_root(FINAL_ROOT)
    staging: RootBinding | None = None
    reservation: Reservation | None = None
    stage_name: str | None = None
    stage_fd: int | None = None
    stage_token: tuple[int, int] | None = None
    try:
        staging = open_bound_root(STAGING_ROOT)
        assert_distinct_roots(final, staging)
        reservation = reserve_output(final, output_name)
        stage_name, stage_fd, stage_token = create_stage(staging)
        assert_root_identity(final)
        data = run_validator(staging, stage_name, stage_fd, stage_token)
        assert_root_identity(final)
        cleanup_stage(staging, stage_name, stage_fd, stage_token)
        stage_name = None
        stage_fd = None
        stage_token = None
        report = commit_report(reservation, data)
        return {
            "wrapper_status": "PASS_SEPARATE_STAGE_ATOMIC_RESERVED_FAIL_CLOSED_NO_SUBMIT",
            "output": str(FINAL_ROOT / output_name),
            "output_sha256": digest(FINAL_ROOT / output_name),
            "validator_status": report["status"],
            "execution_permitted": False,
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
        }
    except Exception:
        if staging is not None and stage_name is not None and stage_fd is not None and stage_token is not None:
            cleanup_stage(staging, stage_name, stage_fd, stage_token)
        if reservation is not None:
            cleanup_reservation(reservation)
        raise
    finally:
        if reservation is not None:
            os.close(reservation.fd)
        if staging is not None:
            os.close(staging.fd)
        os.close(final.fd)


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
