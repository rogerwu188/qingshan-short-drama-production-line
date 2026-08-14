#!/usr/bin/env python3
"""Audit V17 atomic-link exception safety and descriptor closure locally."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as writer  # noqa: E402


WRITER = ROOT / "tools/run_e40_u29c_v17_atomic_link_publish_gate.py"
WRITER_SHA256 = "7728588e210ae17f61cc1c08eef6a18fdd3dfdba3e6cc1e77e61e2f8ae1778d8"
V18_INVOKER = ROOT / "tools/run_e40_u29c_v18_pinned_atomic_link_regression.py"
V18_INVOKER_SHA256 = "ca8224744d7a8f3b71a30d5dcb2c13a3f10f21605f3c293e0698d104b4b02329"
V18_MATRIX = ROOT / "qa/e40_preproduction_20260808/u29c_v18_pinned_atomic_link_regression_v1/E40_U29C_V18_PINNED_ATOMIC_LINK_REGRESSION_MATRIX_V1.json"
V18_MATRIX_SHA256 = "5246c31e789c116b0dfe7fb21cbeb1b9812d77f7f95fcf4ca323862894afca2a"
V19_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v19_atomic_link_exception_safety_audit_v1/E40_U29C_V19_ATOMIC_LINK_EXCEPTION_SAFETY_AND_DESCRIPTOR_CLOSURE_SPEC_V1.json"
V19_SPEC_SHA256 = "b3aba0ae9a06792d13ca2df5aa1d6768369fd2fec3bede1d2de55df4026aa931"
V18_CANONICAL = writer.FINAL_ROOT / "E40_U29C_V18_PINNED_READER_CANONICAL_GATE_V1.json"
REPORT = ROOT / "qa/e40_preproduction_20260808/u29c_v19_atomic_link_exception_safety_audit_v1/E40_U29C_V19_ATOMIC_LINK_EXCEPTION_SAFETY_AUDIT_V1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fd_snapshot() -> list[int]:
    return sorted(int(name) for name in os.listdir("/dev/fd") if name.isdigit())


def static_descriptor_audit() -> dict[str, Any]:
    source = WRITER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: ast.get_source_segment(source, node) or "" for node in tree.body if isinstance(node, ast.FunctionDef)}
    requirements = {
        "child_close_fds_true": "close_fds=True" in functions.get("run_validator", ""),
        "stage_read_fd_closed_in_finally": "finally:" in functions.get("read_stage_file", "") and "os.close(fd)" in functions.get("read_stage_file", ""),
        "stage_directory_fd_closed_in_cleanup_finally": "finally:" in functions.get("cleanup_stage", "") and "os.close(fd)" in functions.get("cleanup_stage", ""),
        "hidden_inode_fd_closed_in_publish_finally": "finally:" in functions.get("publish_complete_payload", "") and "os.close(hidden.fd)" in functions.get("publish_complete_payload", ""),
        "final_and_staging_root_fds_closed_in_execute_finally": (
            "finally:" in functions.get("execute", "")
            and "os.close(staging.fd)" in functions.get("execute", "")
            and "os.close(final.fd)" in functions.get("execute", "")
        ),
        "subprocess_receives_no_pass_fds": "pass_fds" not in functions.get("run_validator", ""),
    }
    return {"case_id": "STATIC_DESCRIPTOR_CLOSURE_AND_CHILD_BOUNDARY", "passed": all(requirements.values()), "requirements": requirements}


def run_bound_case(base: Path, name: str, action: Callable[[writer.RootBinding, Path], dict[str, Any]]) -> dict[str, Any]:
    before = fd_snapshot()
    root_path = base / name
    binding = writer.open_bound_root(root_path)
    try:
        result = action(binding, root_path)
    finally:
        os.close(binding.fd)
    after = fd_snapshot()
    result["descriptor_snapshot_before"] = before
    result["descriptor_snapshot_after"] = after
    result["descriptor_set_stable"] = before == after
    result["passed"] = bool(result.get("passed")) and before == after
    return result


def malformed_pre_link(binding: writer.RootBinding, root_path: Path) -> dict[str, Any]:
    error = None
    try:
        writer.publish_complete_payload(binding, "public.json", b"{malformed-json")
    except writer.GateError as exc:
        error = str(exc)
    entries = sorted(path.name for path in root_path.iterdir())
    return {
        "case_id": "MALFORMED_PRE_LINK_FAILURE_PUBLISHES_NOTHING",
        "passed": error == "STAGED_REPORT_INVALID_JSON" and entries == [],
        "error": error,
        "entries_after": entries,
    }


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        size = os.write(fd, view)
        if size <= 0:
            raise RuntimeError("FIXTURE_WRITE_FAILED")
        view = view[size:]


def competing_public(binding: writer.RootBinding, root_path: Path, payload: bytes) -> dict[str, Any]:
    sentinel = b"COMPETING_PUBLIC_MUST_REMAIN\n"
    fd = os.open("public.json", writer.create_flags(), 0o600, dir_fd=binding.fd)
    try:
        write_all(fd, sentinel)
        os.fsync(fd)
    finally:
        os.close(fd)
    error = None
    try:
        writer.publish_complete_payload(binding, "public.json", payload)
    except writer.GateError as exc:
        error = str(exc)
    entries = sorted(path.name for path in root_path.iterdir())
    preserved = (root_path / "public.json").read_bytes() == sentinel
    return {
        "case_id": "PRE_LINK_COMPETITOR_PRESERVED_AND_OWNED_HIDDEN_CLEANED",
        "passed": error == "PUBLICATION_TARGET_EXISTS" and preserved and entries == ["public.json"],
        "error": error,
        "competitor_preserved": preserved,
        "entries_after": entries,
    }


def injected_post_link_fsync(binding: writer.RootBinding, root_path: Path, payload: bytes) -> dict[str, Any]:
    original_fsync = writer.os.fsync
    fired = False

    def one_shot_fsync(fd: int) -> None:
        nonlocal fired
        if fd == binding.fd and not fired:
            fired = True
            raise OSError("INJECTED_POST_LINK_DIRECTORY_FSYNC_FAILURE")
        original_fsync(fd)

    writer.os.fsync = one_shot_fsync
    error = None
    try:
        writer.publish_complete_payload(binding, "public.json", payload)
    except OSError as exc:
        error = str(exc)
    finally:
        writer.os.fsync = original_fsync
    public = root_path / "public.json"
    entries = sorted(path.name for path in root_path.iterdir())
    public_valid = public.is_file() and writer.validate_report_bytes(public.read_bytes()).get("execution_permitted") is False
    value = os.stat(public, follow_symlinks=False) if public.is_file() else None
    return {
        "case_id": "POST_LINK_FSYNC_FAILURE_LEAVES_COMPLETE_PUBLIC_COMMIT_AMBIGUITY",
        "passed": fired and error == "INJECTED_POST_LINK_DIRECTORY_FSYNC_FAILURE" and public_valid and entries == ["public.json"] and value is not None and value.st_nlink == 1,
        "injected": fired,
        "error": error,
        "complete_valid_public_remains": public_valid,
        "public_link_count": value.st_nlink if value else None,
        "entries_after": entries,
        "gap_found": True,
    }


def injected_owned_cleanup(binding: writer.RootBinding, root_path: Path, payload: bytes) -> dict[str, Any]:
    original_cleanup = writer.cleanup_hidden
    calls = 0

    def one_shot_cleanup(hidden: writer.HiddenInode) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("INJECTED_OWNED_HIDDEN_CLEANUP_FAILURE")
        return original_cleanup(hidden)

    writer.cleanup_hidden = one_shot_cleanup
    error = None
    try:
        writer.publish_complete_payload(binding, "public.json", payload)
    except OSError as exc:
        error = str(exc)
    finally:
        writer.cleanup_hidden = original_cleanup
    public = root_path / "public.json"
    entries = sorted(path.name for path in root_path.iterdir())
    public_valid = public.is_file() and writer.validate_report_bytes(public.read_bytes()).get("execution_permitted") is False
    value = os.stat(public, follow_symlinks=False) if public.is_file() else None
    return {
        "case_id": "OWNED_HIDDEN_CLEANUP_ONE_SHOT_FAILURE_RECOVERS_WITHOUT_RESIDUE",
        "passed": calls == 2 and error == "INJECTED_OWNED_HIDDEN_CLEANUP_FAILURE" and public_valid and entries == ["public.json"] and value is not None and value.st_nlink == 1,
        "cleanup_calls": calls,
        "error": error,
        "complete_valid_public_remains": public_valid,
        "public_link_count": value.st_nlink if value else None,
        "entries_after": entries,
        "gap_found": True,
    }


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
    pins = [WRITER, V18_INVOKER, V18_MATRIX, V19_SPEC]
    expected = {
        str(WRITER.relative_to(ROOT)): WRITER_SHA256,
        str(V18_INVOKER.relative_to(ROOT)): V18_INVOKER_SHA256,
        str(V18_MATRIX.relative_to(ROOT)): V18_MATRIX_SHA256,
        str(V19_SPEC.relative_to(ROOT)): V19_SPEC_SHA256,
    }
    pins_before = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    if not V18_CANONICAL.is_file():
        raise SystemExit("PINNED_V18_CANONICAL_MISSING")
    payload = V18_CANONICAL.read_bytes()
    writer.validate_report_bytes(payload)
    writer.QA_EPISODE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".u29c-v19-audit-", dir=writer.QA_EPISODE_ROOT) as temporary:
        base = Path(temporary)
        cases = [
            static_descriptor_audit(),
            run_bound_case(base, "malformed-pre-link", malformed_pre_link),
            run_bound_case(base, "competing-public", lambda binding, path: competing_public(binding, path, payload)),
            run_bound_case(base, "post-link-fsync", lambda binding, path: injected_post_link_fsync(binding, path, payload)),
            run_bound_case(base, "owned-cleanup", lambda binding, path: injected_owned_cleanup(binding, path, payload)),
        ]
    pins_after = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    failures = [case["case_id"] for case in cases if not case["passed"]]
    failures.extend(name for name, value in expected.items() if pins_before.get(name) != value)
    if pins_before != pins_after:
        failures.append("PINNED_INPUT_MUTATION")
    gap_found = any(case.get("gap_found") for case in cases)
    status = "PASS_AUDIT_POST_LINK_COMMIT_AMBIGUITY_GAP_FOUND_FAIL_CLOSED" if not failures and gap_found else "FAIL"
    report = {
        "schema": "qingshan.e40.u29c.v19.atomic_link_exception_safety_audit.v1",
        "episode": "E40",
        "unit_id": "U29C",
        "recorded_at": stamp(),
        "status": status,
        "execution_permitted": False,
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "pins_before": pins_before,
        "pins_after": pins_after,
        "v18_canonical": str(V18_CANONICAL.relative_to(ROOT)),
        "v18_canonical_sha256": digest(V18_CANONICAL),
        "cases": cases,
        "exception_safety_gap_found": gap_found,
        "gap_classification": {
            "code": "COMPLETE_PUBLIC_INODE_MAY_EXIST_AFTER_REPORTED_POST_LINK_FAILURE",
            "risk": "A caller sees failure while a complete valid public basename already exists; blind replay is forbidden and would deterministically collide.",
            "admission": "FAIL_CLOSED_NEW_VERSIONED_RECOVERY_WRITER_REQUIRED",
        },
        "failures": failures,
        "side_effects": {"provider_calls": 0, "transactions": 0, "credits": 0, "retries": 0, "agentcut": 0, "assembly": 0},
        "next_action": "Keep execution closed. Register a new versioned writer that resolves post-link outcome by exact owned inode/complete-payload inspection and never blindly retries.",
    }
    write_exclusive(REPORT, report)
    print(json.dumps({"status": status, "report": str(REPORT), "failures": failures}, ensure_ascii=False))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
