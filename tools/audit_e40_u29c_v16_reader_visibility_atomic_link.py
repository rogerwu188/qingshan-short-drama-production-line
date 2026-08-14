#!/usr/bin/env python3
"""Audit reader-visible incomplete output and prove atomic link publication."""

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
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v12_separate_stage_capability_gate as writer  # noqa: E402


WRITER = ROOT / "tools/run_e40_u29c_v12_separate_stage_capability_gate.py"
WRITER_SHA256 = "00696e5c81a5e41510fad9f2244c8068c35d373c09f55c2911e21e47e65d23f9"
V15_MATRIX = ROOT / "qa/e40_preproduction_20260808/u29c_v15_same_basename_contention_v1/E40_U29C_V15_SAME_BASENAME_CONTENTION_MATRIX_V1.json"
V15_MATRIX_SHA256 = "c499dff6beab308a5a2385841c4b112d0ec42044f8eeb931d9ecfa3bedc8d181"
V16_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v16_reader_visibility_atomic_publish_v1/E40_U29C_V16_READER_VISIBILITY_AND_ATOMIC_LINK_PUBLISH_SPEC_V1.json"
V16_SPEC_SHA256 = "50640c5954f32cb7192d90b083b250177ab8f82c62c2630d378bff3597161f6b"
REPORT = ROOT / "qa/e40_preproduction_20260808/u29c_v16_reader_visibility_atomic_publish_v1/E40_U29C_V16_READER_VISIBILITY_ATOMIC_LINK_AUDIT_V1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise RuntimeError("FIXTURE_WRITE_FAILED")
        view = view[written:]


def write_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def execute_call_order() -> dict[str, Any]:
    source = WRITER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls: dict[str, list[int]] = {"reserve_output": [], "run_validator": [], "commit_report": []}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "execute":
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in calls:
                calls[child.func.id].append(child.lineno)
    ordered = (
        len(calls["reserve_output"]) == 1
        and len(calls["run_validator"]) == 1
        and len(calls["commit_report"]) == 1
        and calls["reserve_output"][0] < calls["run_validator"][0] < calls["commit_report"][0]
    )
    return {"calls": calls, "public_reservation_precedes_validation_and_commit": ordered}


def public_reservation_visibility_case(base: Path) -> dict[str, Any]:
    root_path = base / "current_writer_visibility"
    binding = writer.open_bound_root(root_path)
    reservation = writer.reserve_output(binding, "public_gate.json")
    try:
        public = root_path / "public_gate.json"
        data = public.read_bytes()
        parse_failed = False
        try:
            json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parse_failed = True
        observed = {
            "exists_before_validation": public.exists(),
            "size_before_validation": len(data),
            "json_parse_failed": parse_failed,
            "reservation_nlink": os.fstat(reservation.fd).st_nlink,
        }
        return {
            "case_id": "CURRENT_PUBLIC_BASENAME_VISIBLE_INCOMPLETE",
            "passed": observed == {
                "exists_before_validation": True,
                "size_before_validation": 0,
                "json_parse_failed": True,
                "reservation_nlink": 1,
            },
            **observed,
        }
    finally:
        writer.cleanup_reservation(reservation)
        os.close(reservation.fd)
        os.close(binding.fd)


def valid_payload() -> bytes:
    matrix = json.loads(V15_MATRIX.read_text(encoding="utf-8"))
    path = ROOT / matrix["shared_output"]
    if digest(path) != matrix["shared_output_sha256"]:
        raise SystemExit("V15_SHARED_OUTPUT_SHA_MISMATCH")
    writer.validate_report_bytes(path.read_bytes())
    return path.read_bytes()


def hidden_atomic_link_case(base: Path, payload: bytes) -> dict[str, Any]:
    root_path = base / "atomic_link_publish"
    binding = writer.open_bound_root(root_path)
    hidden = ".complete-hidden.json"
    public = "public_gate.json"
    hidden_fd = os.open(hidden, writer.create_flags(), 0o600, dir_fd=binding.fd)
    try:
        write_all(hidden_fd, payload)
        os.fsync(hidden_fd)
        hidden_stat = os.fstat(hidden_fd)
        public_absent_during_write = not (root_path / public).exists()
        writer.validate_report_bytes(payload)
        os.link(hidden, public, src_dir_fd=binding.fd, dst_dir_fd=binding.fd, follow_symlinks=False)
        os.fsync(binding.fd)
        public_stat = os.stat(public, dir_fd=binding.fd, follow_symlinks=False)
        same_inode = (hidden_stat.st_dev, hidden_stat.st_ino) == (public_stat.st_dev, public_stat.st_ino)
        complete_public = (root_path / public).read_bytes() == payload
        os.unlink(hidden, dir_fd=binding.fd)
        os.fsync(binding.fd)
        public_survives_hidden_cleanup = (root_path / public).read_bytes() == payload
        return {
            "case_id": "HIDDEN_COMPLETE_INODE_ATOMIC_LINK_PUBLICATION",
            "passed": public_absent_during_write and same_inode and complete_public and public_survives_hidden_cleanup,
            "public_absent_during_hidden_write": public_absent_during_write,
            "same_inode_at_publication": same_inode,
            "public_payload_complete": complete_public,
            "public_survives_hidden_cleanup": public_survives_hidden_cleanup,
        }
    finally:
        os.close(hidden_fd)
        for name in [hidden, public]:
            try:
                os.unlink(name, dir_fd=binding.fd)
            except FileNotFoundError:
                pass
        os.close(binding.fd)


def competing_public_no_overwrite_case(base: Path, payload: bytes) -> dict[str, Any]:
    root_path = base / "competing_public"
    binding = writer.open_bound_root(root_path)
    hidden = ".complete-hidden.json"
    public = "public_gate.json"
    sentinel = b"COMPETING_PUBLIC_MUST_REMAIN\n"
    hidden_fd = os.open(hidden, writer.create_flags(), 0o600, dir_fd=binding.fd)
    public_fd = os.open(public, writer.create_flags(), 0o600, dir_fd=binding.fd)
    try:
        write_all(hidden_fd, payload)
        os.fsync(hidden_fd)
        write_all(public_fd, sentinel)
        os.fsync(public_fd)
        rejected = False
        try:
            os.link(hidden, public, src_dir_fd=binding.fd, dst_dir_fd=binding.fd, follow_symlinks=False)
        except FileExistsError:
            rejected = True
        preserved = (root_path / public).read_bytes() == sentinel
        return {
            "case_id": "COMPETING_PUBLIC_ATOMIC_LINK_NO_OVERWRITE",
            "passed": rejected and preserved,
            "link_rejected_existing_public": rejected,
            "competing_public_preserved": preserved,
        }
    finally:
        os.close(hidden_fd)
        os.close(public_fd)
        for name in [hidden, public]:
            try:
                os.unlink(name, dir_fd=binding.fd)
            except FileNotFoundError:
                pass
        os.close(binding.fd)


def malformed_never_published_case(base: Path) -> dict[str, Any]:
    root_path = base / "malformed_never_publish"
    binding = writer.open_bound_root(root_path)
    hidden = ".malformed-hidden.json"
    public = "public_gate.json"
    hidden_fd = os.open(hidden, writer.create_flags(), 0o600, dir_fd=binding.fd)
    try:
        malformed = b"{malformed-json"
        write_all(hidden_fd, malformed)
        os.fsync(hidden_fd)
        error = None
        try:
            writer.validate_report_bytes(malformed)
        except writer.GateError as exc:
            error = str(exc)
        public_absent = not (root_path / public).exists()
        return {
            "case_id": "MALFORMED_HIDDEN_PAYLOAD_NEVER_PUBLISHED",
            "passed": error == "STAGED_REPORT_INVALID_JSON" and public_absent,
            "validation_error": error,
            "public_basename_absent": public_absent,
        }
    finally:
        os.close(hidden_fd)
        try:
            os.unlink(hidden, dir_fd=binding.fd)
        except FileNotFoundError:
            pass
        os.close(binding.fd)


def main() -> int:
    if REPORT.exists() or REPORT.is_symlink():
        raise SystemExit("REPORT_ALREADY_EXISTS")
    pins = [WRITER, V15_MATRIX, V16_SPEC]
    expected = {
        str(WRITER.relative_to(ROOT)): WRITER_SHA256,
        str(V15_MATRIX.relative_to(ROOT)): V15_MATRIX_SHA256,
        str(V16_SPEC.relative_to(ROOT)): V16_SPEC_SHA256,
    }
    pins_before = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    pin_failures = [name for name, value in expected.items() if pins_before.get(name) != value]
    order = execute_call_order()
    payload_bytes = valid_payload()
    writer.QA_EPISODE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bounded-u29c-v16-", dir=writer.QA_EPISODE_ROOT) as temporary:
        base = Path(temporary)
        cases = [
            public_reservation_visibility_case(base),
            hidden_atomic_link_case(base, payload_bytes),
            competing_public_no_overwrite_case(base, payload_bytes),
            malformed_never_published_case(base),
        ]
    pins_after = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    failures = [case["case_id"] for case in cases if not case["passed"]]
    failures.extend(pin_failures)
    if not order["public_reservation_precedes_validation_and_commit"]:
        failures.append("STATIC_PUBLIC_RESERVATION_ORDER_NOT_PROVEN")
    if pins_before != pins_after:
        failures.append("PINNED_INPUT_MUTATION")
    status = "PASS_AUDIT_READER_VISIBLE_INCOMPLETE_AND_ATOMIC_LINK_FEASIBLE_FAIL_CLOSED" if not failures else "FAIL"
    report = {
        "schema": "qingshan.e40.u29c.v16.reader_visibility_atomic_link_audit.v1",
        "episode": "E40",
        "unit_id": "U29C",
        "recorded_at": stamp(),
        "status": status,
        "execution_permitted": False,
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "pins_before": pins_before,
        "pins_after": pins_after,
        "static_call_order": order,
        "reader_visibility_gap_found": True,
        "atomic_link_publication_feasible": all(case["passed"] for case in cases[1:]),
        "cases": cases,
        "admission_contract": {
            "public_basename_existence_is_authority": False,
            "hidden_complete_inode_required": True,
            "hidden_inode_mode": "0600",
            "hidden_inode_link_count_before_publish": 1,
            "payload_validation_and_fsync_before_publish": True,
            "publication_operation": "ATOMIC_NO_OVERWRITE_HARD_LINK",
            "same_device_required": True,
            "directory_fsync_before_and_after_hidden_unlink": True,
            "consumer_requires_parseable_pinned_fail_closed_json": True,
        },
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
            "Keep execution closed. Implement a new-path writer that publishes complete verified JSON by "
            "atomic no-overwrite hard link, then run reader, contention, substitution and cleanup negatives."
        ),
    }
    write_exclusive(REPORT, report)
    print(json.dumps({"status": status, "report": str(REPORT), "failures": failures}, ensure_ascii=False))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
