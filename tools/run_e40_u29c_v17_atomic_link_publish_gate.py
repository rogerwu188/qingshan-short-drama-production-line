#!/usr/bin/env python3
"""Run the U29C fail-closed gate with complete-inode atomic-link publication."""

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
FINAL_ROOT = QA_EPISODE_ROOT / "u29c_v17_atomic_link_final_output_v1"
STAGING_ROOT = QA_EPISODE_ROOT / "u29c_v17_private_staging_root_v1"
VALIDATOR = ROOT / "tools/validate_e40_u29c_v6_capability_contract.py"
VALIDATOR_SHA256 = "ebf2275931a09cd51dbb00af8268959faea62e1885b5b3a24be11d6c00fd87e5"
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u29c_v6_changed_representation_no_submit_v1/E40_U29C_V6_PROVIDER_CAPABILITY_AND_EXECUTION_CONTRACT_V1.json"
CONTRACT_SHA256 = "10d38f21b46d37819f4205a265662d011beebc1e778d6f658a97ad394fe935a2"
V16_AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v16_reader_visibility_atomic_publish_v1/E40_U29C_V16_READER_VISIBILITY_ATOMIC_LINK_AUDIT_V1.json"
V16_AUDIT_SHA256 = "d0e84552954e1614f42649e429e4aafa1b773d30a4221f12bf38e23f49c2a0bc"
V17_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v17_atomic_link_writer_v1/E40_U29C_V17_ATOMIC_LINK_WRITER_IMPLEMENTATION_SPEC_V1.json"
V17_SPEC_SHA256 = "f9f947270986b3488206665694b3e4c94ae148163a3b8066e453f4d7ea9519a1"
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json\Z")


class GateError(RuntimeError):
    """Expected fail-closed gate error."""


@dataclass
class RootBinding:
    path: Path
    fd: int
    token: tuple[int, int]


@dataclass
class HiddenInode:
    root: RootBinding
    name: str
    fd: int
    token: tuple[int, int]
    linked_public: bool = False


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
        if not stat.S_ISDIR(lexical.st_mode) or identity(lexical) != identity(opened):
            raise GateError("BOUND_ROOT_IDENTITY_MISMATCH")
        if stat.S_IMODE(opened.st_mode) & 0o077:
            raise GateError("BOUND_ROOT_NOT_PRIVATE_0700")
        return RootBinding(path, fd, identity(opened))
    except Exception:
        os.close(fd)
        raise


def assert_root_identity(binding: RootBinding) -> None:
    try:
        lexical = os.stat(binding.path, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise GateError("BOUND_ROOT_MISSING") from exc
    opened = os.fstat(binding.fd)
    if identity(lexical) != binding.token or identity(opened) != binding.token or stat.S_IMODE(opened.st_mode) & 0o077:
        raise GateError("BOUND_ROOT_IDENTITY_DRIFT")


def assert_distinct_roots(final: RootBinding, staging: RootBinding) -> None:
    if final.token == staging.token:
        raise GateError("FINAL_AND_STAGING_ROOT_INODES_NOT_DISTINCT")
    final_rel = final.path.relative_to(QA_EPISODE_ROOT)
    stage_rel = staging.path.relative_to(QA_EPISODE_ROOT)
    if not final_rel.parts or not stage_rel.parts or final_rel.parts[0] == stage_rel.parts[0]:
        raise GateError("FINAL_AND_STAGING_ROOTS_SHARE_CHILD_ANCESTOR")


def entry_identity(binding: RootBinding, name: str) -> tuple[int, int] | None:
    try:
        return identity(os.stat(name, dir_fd=binding.fd, follow_symlinks=False))
    except FileNotFoundError:
        return None


def create_stage(binding: RootBinding) -> tuple[str, int, tuple[int, int]]:
    for _ in range(16):
        name = f".u29c-v17-stage-{secrets.token_hex(12)}"
        try:
            os.mkdir(name, 0o700, dir_fd=binding.fd)
        except FileExistsError:
            continue
        fd = os.open(name, directory_flags(), dir_fd=binding.fd)
        opened = os.fstat(fd)
        token = identity(opened)
        lexical = os.stat(name, dir_fd=binding.fd, follow_symlinks=False)
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
    if identity(lexical) != token or identity(os.fstat(fd)) != token or not stat.S_ISDIR(lexical.st_mode):
        raise GateError("STAGE_IDENTITY_DRIFT")


def read_stage_file(stage_fd: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=stage_fd)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise GateError("STAGED_REPORT_NOT_PRIVATE_REGULAR_FILE")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 65536):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def cleanup_stage(binding: RootBinding, name: str, fd: int, token: tuple[int, int]) -> None:
    assert_stage_identity(binding, name, fd, token)
    try:
        for child in os.listdir(fd):
            value = os.stat(child, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(value.st_mode):
                raise GateError("UNEXPECTED_STAGE_SUBDIRECTORY")
            os.unlink(child, dir_fd=fd)
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=binding.fd)
    os.fsync(binding.fd)


def validate_report_bytes(data: bytes) -> dict[str, Any]:
    try:
        report = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("STAGED_REPORT_INVALID_JSON") from exc
    side = report.get("side_effects") or {}
    zeros = ["provider_calls", "transactions", "credits", "retries", "agentcut", "assembly"]
    if not (
        report.get("status") == "PASS_EXPECTED_FAIL_CLOSED_NO_SUBMIT"
        and report.get("execution_permitted") is False
        and report.get("contract_closed") is True
        and report.get("failures") == []
        and all(side.get(key) == 0 for key in zeros)
    ):
        raise GateError("STAGED_REPORT_FAIL_CLOSED_CONTRACT_MISMATCH")
    return report


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise GateError("OUTPUT_DESCRIPTOR_WRITE_FAILED")
        view = view[written:]


def create_hidden(binding: RootBinding) -> HiddenInode:
    for _ in range(16):
        name = f".u29c-v17-hidden-{secrets.token_hex(12)}.json"
        try:
            fd = os.open(name, create_flags(), 0o600, dir_fd=binding.fd)
        except FileExistsError:
            continue
        opened = os.fstat(fd)
        token = identity(opened)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or entry_identity(binding, name) != token:
            os.close(fd)
            raise GateError("HIDDEN_INODE_IDENTITY_INVALID")
        return HiddenInode(binding, name, fd, token)
    raise GateError("HIDDEN_EXCLUSIVE_CREATE_EXHAUSTED")


def assert_hidden_owned(hidden: HiddenInode, expected_links: int) -> None:
    opened = os.fstat(hidden.fd)
    if identity(opened) != hidden.token or opened.st_nlink != expected_links:
        raise GateError("HIDDEN_INODE_FD_IDENTITY_DRIFT")
    if entry_identity(hidden.root, hidden.name) != hidden.token:
        raise GateError("HIDDEN_INODE_ENTRY_IDENTITY_DRIFT")


def cleanup_hidden(hidden: HiddenInode) -> bool:
    if entry_identity(hidden.root, hidden.name) != hidden.token:
        return False
    os.unlink(hidden.name, dir_fd=hidden.root.fd)
    os.fsync(hidden.root.fd)
    return True


def publish_complete_payload(final: RootBinding, output_name: str, data: bytes) -> dict[str, Any]:
    if not SAFE_NAME.fullmatch(output_name):
        raise GateError("OUTPUT_NAME_MUST_BE_SAFE_JSON_BASENAME")
    report = validate_report_bytes(data)
    hidden = create_hidden(final)
    try:
        write_all(hidden.fd, data)
        os.fsync(hidden.fd)
        assert_root_identity(final)
        assert_hidden_owned(hidden, 1)
        try:
            os.link(hidden.name, output_name, src_dir_fd=final.fd, dst_dir_fd=final.fd, follow_symlinks=False)
        except FileExistsError as exc:
            raise GateError("PUBLICATION_TARGET_EXISTS") from exc
        hidden.linked_public = True
        os.fsync(final.fd)
        public_stat = os.stat(output_name, dir_fd=final.fd, follow_symlinks=False)
        if identity(public_stat) != hidden.token or public_stat.st_nlink != 2:
            raise GateError("PUBLICATION_INODE_IDENTITY_MISMATCH")
        cleanup_hidden(hidden)
        hidden.linked_public = False
        public_stat = os.stat(output_name, dir_fd=final.fd, follow_symlinks=False)
        if identity(public_stat) != hidden.token or public_stat.st_nlink != 1:
            raise GateError("PUBLICATION_FINAL_LINK_COUNT_INVALID")
        return report
    except Exception:
        cleanup_hidden(hidden)
        raise
    finally:
        os.close(hidden.fd)


def build_validator_command(stage_name: str, staged_name: str) -> list[str]:
    return [
        sys.executable,
        str(VALIDATOR),
        "--contract",
        str(CONTRACT),
        "--out",
        str(STAGING_ROOT / stage_name / staged_name),
    ]


def run_validator(staging: RootBinding, stage_name: str, stage_fd: int, stage_token: tuple[int, int]) -> bytes:
    staged_name = "validated_report.json"
    assert_root_identity(staging)
    assert_stage_identity(staging, stage_name, stage_fd, stage_token)
    completed = subprocess.run(
        build_validator_command(stage_name, staged_name),
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
        (V16_AUDIT, V16_AUDIT_SHA256, "PINNED_V16_AUDIT_SHA_MISMATCH"),
        (V17_SPEC, V17_SPEC_SHA256, "PINNED_V17_SPEC_SHA_MISMATCH"),
    ]
    for path, expected, code in pins:
        if digest(path) != expected:
            raise GateError(code)


def execute(output_name: str) -> dict[str, Any]:
    if not SAFE_NAME.fullmatch(output_name):
        raise GateError("OUTPUT_NAME_MUST_BE_SAFE_JSON_BASENAME")
    verify_pins()
    final = open_bound_root(FINAL_ROOT)
    staging: RootBinding | None = None
    stage_name: str | None = None
    stage_fd: int | None = None
    stage_token: tuple[int, int] | None = None
    try:
        staging = open_bound_root(STAGING_ROOT)
        assert_distinct_roots(final, staging)
        if entry_identity(final, output_name) is not None:
            raise GateError("PUBLICATION_TARGET_EXISTS")
        stage_name, stage_fd, stage_token = create_stage(staging)
        data = run_validator(staging, stage_name, stage_fd, stage_token)
        cleanup_stage(staging, stage_name, stage_fd, stage_token)
        stage_name = None
        stage_fd = None
        stage_token = None
        report = publish_complete_payload(final, output_name, data)
        output = FINAL_ROOT / output_name
        return {
            "wrapper_status": "PASS_ATOMIC_LINK_PUBLICATION_FAIL_CLOSED_NO_SUBMIT",
            "output": str(output),
            "output_sha256": digest(output),
            "validator_status": report["status"],
            "execution_permitted": False,
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
        }
    except Exception:
        if staging is not None and stage_name is not None and stage_fd is not None and stage_token is not None:
            cleanup_stage(staging, stage_name, stage_fd, stage_token)
        raise
    finally:
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
