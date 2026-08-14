#!/usr/bin/env python3
"""Publish a fail-closed gate with exact-owned-inode post-link recovery."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base  # noqa: E402


QA_EPISODE_ROOT = ROOT / "qa/e40_preproduction_20260808"
FINAL_ROOT = QA_EPISODE_ROOT / "u29c_v20_post_link_recovery_final_output_v1"
STAGING_ROOT = QA_EPISODE_ROOT / "u29c_v20_post_link_recovery_private_staging_v1"
VALIDATOR = ROOT / "tools/validate_e40_u29c_v6_capability_contract.py"
VALIDATOR_SHA256 = "ebf2275931a09cd51dbb00af8268959faea62e1885b5b3a24be11d6c00fd87e5"
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u29c_v6_changed_representation_no_submit_v1/E40_U29C_V6_PROVIDER_CAPABILITY_AND_EXECUTION_CONTRACT_V1.json"
CONTRACT_SHA256 = "10d38f21b46d37819f4205a265662d011beebc1e778d6f658a97ad394fe935a2"
V19_AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v19_atomic_link_exception_safety_audit_v1/E40_U29C_V19_ATOMIC_LINK_EXCEPTION_SAFETY_AUDIT_V1.json"
V19_AUDIT_SHA256 = "5b872fe948e6516bbfa571dd135fd8e02216800658a87a0c9f2ade8155b76ca5"
V20_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v20_post_link_recovery_writer_v1/E40_U29C_V20_POST_LINK_OUTCOME_RECOVERY_WRITER_SPEC_V1.json"
V20_SPEC_SHA256 = "576a3eef1621100fe656c9aba2ca79781ddfc8bc41ae160d9379a33eda116bbd"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_pins() -> None:
    pins = [
        (VALIDATOR, VALIDATOR_SHA256, "PINNED_VALIDATOR_SHA_MISMATCH"),
        (CONTRACT, CONTRACT_SHA256, "PINNED_CONTRACT_SHA_MISMATCH"),
        (V19_AUDIT, V19_AUDIT_SHA256, "PINNED_V19_AUDIT_SHA_MISMATCH"),
        (V20_SPEC, V20_SPEC_SHA256, "PINNED_V20_SPEC_SHA_MISMATCH"),
    ]
    for path, expected, code in pins:
        if digest(path) != expected:
            raise base.GateError(code)


def create_hidden(binding: base.RootBinding) -> base.HiddenInode:
    for _ in range(16):
        name = f".u29c-v20-hidden-{secrets.token_hex(12)}.json"
        try:
            fd = os.open(name, base.create_flags(), 0o600, dir_fd=binding.fd)
        except FileExistsError:
            continue
        opened = os.fstat(fd)
        token = base.identity(opened)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or base.entry_identity(binding, name) != token:
            os.close(fd)
            raise base.GateError("HIDDEN_INODE_IDENTITY_INVALID")
        return base.HiddenInode(binding, name, fd, token)
    raise base.GateError("HIDDEN_EXCLUSIVE_CREATE_EXHAUSTED")


def cleanup_owned_hidden(hidden: base.HiddenInode) -> bool:
    if base.entry_identity(hidden.root, hidden.name) != hidden.token:
        return False
    os.unlink(hidden.name, dir_fd=hidden.root.fd)
    os.fsync(hidden.root.fd)
    return True


def read_entry(binding: base.RootBinding, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=binding.fd)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise base.GateError("PUBLICATION_ENTRY_NOT_REGULAR")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 65536):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def owned_public_exact(final: base.RootBinding, output_name: str, token: tuple[int, int], data: bytes) -> bool:
    try:
        value = os.stat(output_name, dir_fd=final.fd, follow_symlinks=False)
        if base.identity(value) != token or not stat.S_ISREG(value.st_mode):
            return False
        observed = read_entry(final, output_name)
        if observed != data:
            return False
        base.validate_report_bytes(observed)
        return True
    except (FileNotFoundError, base.GateError):
        return False


def recover_owned_public(hidden: base.HiddenInode, output_name: str, data: bytes) -> bool:
    final = hidden.root
    if not owned_public_exact(final, output_name, hidden.token, data):
        return False
    cleanup_owned_hidden(hidden)
    os.fsync(final.fd)
    value = os.stat(output_name, dir_fd=final.fd, follow_symlinks=False)
    return base.identity(value) == hidden.token and value.st_nlink == 1 and owned_public_exact(final, output_name, hidden.token, data)


def publish_complete_payload(final: base.RootBinding, output_name: str, data: bytes) -> tuple[dict[str, Any], bool, str | None]:
    if not base.SAFE_NAME.fullmatch(output_name):
        raise base.GateError("OUTPUT_NAME_MUST_BE_SAFE_JSON_BASENAME")
    report = base.validate_report_bytes(data)
    hidden = create_hidden(final)
    linked = False
    try:
        base.write_all(hidden.fd, data)
        os.fsync(hidden.fd)
        base.assert_root_identity(final)
        base.assert_hidden_owned(hidden, 1)
        try:
            os.link(hidden.name, output_name, src_dir_fd=final.fd, dst_dir_fd=final.fd, follow_symlinks=False)
        except FileExistsError as exc:
            raise base.GateError("PUBLICATION_TARGET_EXISTS") from exc
        linked = True
        try:
            os.fsync(final.fd)
            value = os.stat(output_name, dir_fd=final.fd, follow_symlinks=False)
            if base.identity(value) != hidden.token or value.st_nlink != 2 or not owned_public_exact(final, output_name, hidden.token, data):
                raise base.GateError("PUBLICATION_INODE_OR_PAYLOAD_MISMATCH")
            cleanup_owned_hidden(hidden)
            value = os.stat(output_name, dir_fd=final.fd, follow_symlinks=False)
            if base.identity(value) != hidden.token or value.st_nlink != 1:
                raise base.GateError("PUBLICATION_FINAL_LINK_COUNT_INVALID")
            return report, False, None
        except Exception as exc:
            try:
                if recover_owned_public(hidden, output_name, data):
                    return report, True, type(exc).__name__
            except Exception as recovery_exc:
                raise base.GateError("POST_LINK_RECOVERY_FAILED") from recovery_exc
            raise base.GateError("POST_LINK_PUBLIC_OUTCOME_NOT_OWNED_OR_COMPLETE") from exc
    except Exception:
        if not linked:
            cleanup_owned_hidden(hidden)
        raise
    finally:
        os.close(hidden.fd)


def run_validator(staging: base.RootBinding, stage_name: str, stage_fd: int, stage_token: tuple[int, int]) -> bytes:
    staged_name = "validated_report.json"
    base.assert_root_identity(staging)
    base.assert_stage_identity(staging, stage_name, stage_fd, stage_token)
    completed = subprocess.run(
        [sys.executable, str(VALIDATOR), "--contract", str(CONTRACT), "--out", str(STAGING_ROOT / stage_name / staged_name)],
        cwd=ROOT,
        close_fds=True,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise base.GateError(f"PINNED_VALIDATOR_FAILED_EXIT_{completed.returncode}")
    base.assert_root_identity(staging)
    base.assert_stage_identity(staging, stage_name, stage_fd, stage_token)
    return base.read_stage_file(stage_fd, staged_name)


def execute(output_name: str) -> dict[str, Any]:
    if not base.SAFE_NAME.fullmatch(output_name):
        raise base.GateError("OUTPUT_NAME_MUST_BE_SAFE_JSON_BASENAME")
    verify_pins()
    final = base.open_bound_root(FINAL_ROOT)
    staging: base.RootBinding | None = None
    stage_name: str | None = None
    stage_fd: int | None = None
    stage_token: tuple[int, int] | None = None
    try:
        staging = base.open_bound_root(STAGING_ROOT)
        base.assert_distinct_roots(final, staging)
        if base.entry_identity(final, output_name) is not None:
            raise base.GateError("PUBLICATION_TARGET_EXISTS")
        stage_name, stage_fd, stage_token = base.create_stage(staging)
        data = run_validator(staging, stage_name, stage_fd, stage_token)
        base.cleanup_stage(staging, stage_name, stage_fd, stage_token)
        stage_name = None
        stage_fd = None
        stage_token = None
        report, recovered, recovery_cause = publish_complete_payload(final, output_name, data)
        output = FINAL_ROOT / output_name
        return {
            "wrapper_status": "PASS_POST_LINK_OUTCOME_RECOVERY_FAIL_CLOSED_NO_SUBMIT",
            "output": str(output),
            "output_sha256": digest(output),
            "validator_status": report["status"],
            "post_link_recovered": recovered,
            "recovery_cause": recovery_cause,
            "execution_permitted": False,
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
        }
    except Exception:
        if staging is not None and stage_name is not None and stage_fd is not None and stage_token is not None:
            base.cleanup_stage(staging, stage_name, stage_fd, stage_token)
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
    except base.GateError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
