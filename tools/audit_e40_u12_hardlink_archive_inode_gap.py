#!/usr/bin/env python3
"""Audit V22/V23 archive gate behavior against a no-write hard-link alias."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INVOKER = ROOT / "tools/run_e40_u12_immutable_snapshot_upgrade_gate.py"
INVOKER_SHA256 = "f87da30d588ad1a6447f9c4bcb24cf2673474b10fe22957dac24b58202888389"
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v29_hardlink_inode_audit_v1/E40_U12_V29_HARDLINK_ARCHIVE_INODE_INDEPENDENCE_AUDIT_CONTRACT_V1.json"
CONTRACT_SHA256 = "b9c7cd9b2af9f2a94c99a74ae437b5a429e8bd456e178da48cfcadc8d717c1ce"
REQUEST = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v29_hardlink_inode_audit_v1/E40_U12_V29_HARDLINK_ARCHIVE_PRE_UPGRADE_GAP_REQUEST_V1.json"
REQUEST_SHA256 = "c7cc687f14620d79fa6aa9ea5919f03a714c51f80e0a4661befa82dd0601bf22"
TARGET = ROOT / "tools/validate_e40_u12_source_layer_package.py"
CANONICAL_ARCHIVE = ROOT / "workflow/archive/e40_u12_v8_validator_snapshot_6c7fcd/validate_e40_u12_source_layer_package_v8_historical.py"
EXPECTED_SHA256 = "6c7fcd2923166c909b07e8d108e7efb75b1d070edd99a4bc998096565e0c70d2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"repo-relative path required: {raw}")
    resolved = (ROOT / path).resolve()
    resolved.relative_to(ROOT)
    return resolved


def stat_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.relative_to(ROOT)),
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "st_nlink": stat.st_nlink,
        "st_size": stat.st_size,
        "st_mtime_ns": stat.st_mtime_ns,
        "sha256": sha256(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--gate-out", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    gate_out = repo_path(args.gate_out)
    out = repo_path(args.out)
    request = json.loads(REQUEST.read_text())
    fixture = repo_path(request["prior_version"]["archive_path"])
    if fixture.exists() or fixture.is_symlink():
        raise SystemExit(f"HARDLINK_FIXTURE_PREEXISTS:{fixture}")

    pins = {
        "invoker": {"expected": INVOKER_SHA256, "actual": sha256(INVOKER)},
        "contract": {"expected": CONTRACT_SHA256, "actual": sha256(CONTRACT)},
        "request": {"expected": REQUEST_SHA256, "actual": sha256(REQUEST)},
        "target": {"expected": EXPECTED_SHA256, "actual": sha256(TARGET)},
        "canonical_archive": {"expected": EXPECTED_SHA256, "actual": sha256(CANONICAL_ARCHIVE)},
    }
    pins_ok = all(item["expected"] == item["actual"] for item in pins.values())
    target_before = stat_record(TARGET)
    canonical_before = stat_record(CANONICAL_ARCHIVE)
    fixture_during: dict[str, Any] | None = None
    target_during: dict[str, Any] | None = None
    gate: dict[str, Any] | None = None
    process_exit_code: int | None = None
    process_stdout = ""
    process_stderr = ""
    execution_error: str | None = None
    fixture_removed = False
    try:
        fixture.parent.mkdir(parents=True, exist_ok=True)
        os.link(TARGET, fixture, follow_symlinks=False)
        fixture_during = stat_record(fixture)
        target_during = stat_record(TARGET)
        gate_out.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                sys.executable,
                str(INVOKER),
                "--request",
                str(REQUEST.relative_to(ROOT)),
                "--out",
                str(gate_out.relative_to(ROOT)),
                "--expect-status",
                "PASS_ARCHIVE_PRECONDITION_PROVEN_NO_MUTATION",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        process_exit_code = completed.returncode
        process_stdout = completed.stdout.strip()
        process_stderr = completed.stderr.strip()
        if gate_out.is_file():
            gate = json.loads(gate_out.read_text())
    except Exception as exc:
        execution_error = f"{type(exc).__name__}:{exc}"
    finally:
        if fixture.exists() and not fixture.is_symlink():
            fixture.unlink()
        fixture_removed = not fixture.exists() and not fixture.is_symlink()

    target_after = stat_record(TARGET)
    canonical_after = stat_record(CANONICAL_ARCHIVE)
    same_inode = bool(
        fixture_during
        and target_during
        and fixture_during["st_dev"] == target_during["st_dev"]
        and fixture_during["st_ino"] == target_during["st_ino"]
    )
    link_count_incremented = bool(
        target_during and target_during["st_nlink"] == target_before["st_nlink"] + 1
    )
    link_count_restored = target_after["st_nlink"] == target_before["st_nlink"]
    content_unchanged = all(
        [
            target_before["sha256"] == target_after["sha256"] == EXPECTED_SHA256,
            canonical_before["sha256"] == canonical_after["sha256"] == EXPECTED_SHA256,
            target_before["st_size"] == target_after["st_size"],
            target_before["st_mtime_ns"] == target_after["st_mtime_ns"],
            canonical_before["st_size"] == canonical_after["st_size"],
            canonical_before["st_mtime_ns"] == canonical_after["st_mtime_ns"],
        ]
    )
    gate_accepted = bool(
        gate
        and gate.get("status") == "PASS_ARCHIVE_PRECONDITION_PROVEN_NO_MUTATION"
        and gate.get("failure_count") == 0
        and gate.get("target_validator_mutated") is False
        and process_exit_code == 0
    )
    gap_confirmed = all(
        [
            pins_ok,
            execution_error is None,
            same_inode,
            link_count_incremented,
            gate_accepted,
            fixture_removed,
            link_count_restored,
            content_unchanged,
        ]
    )
    status = (
        "FAIL_CLOSED_INODE_INDEPENDENCE_GAP_CONFIRMED_NO_UPGRADE"
        if gap_confirmed
        else "FAIL_CLOSED_HARDLINK_AUDIT_INCONCLUSIVE_NO_UPGRADE"
    )
    receipt = {
        "schema": "qingshan.e40.u12.v29.hardlink_archive_inode_gap_audit.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "pins": pins,
        "pins_ok": pins_ok,
        "target_before": target_before,
        "target_during": target_during,
        "target_after": target_after,
        "fixture_during": fixture_during,
        "fixture_path": str(fixture.relative_to(ROOT)),
        "fixture_removed": fixture_removed,
        "fixture_recoverability": "EPHEMERAL_DIRECTORY_ENTRY_ONLY_NO_CONTENT_DELETED",
        "same_device_and_inode": same_inode,
        "link_count_incremented_exactly_one": link_count_incremented,
        "link_count_restored": link_count_restored,
        "canonical_before": canonical_before,
        "canonical_after": canonical_after,
        "file_content_unchanged": content_unchanged,
        "gate": str(gate_out.relative_to(ROOT)),
        "gate_sha256": sha256(gate_out) if gate_out.is_file() else None,
        "gate_status": gate.get("status") if gate else None,
        "gate_failure_count": gate.get("failure_count") if gate else None,
        "gate_accepted_hardlink_alias": gate_accepted,
        "process_exit_code": process_exit_code,
        "process_stdout": process_stdout,
        "process_stderr": process_stderr,
        "execution_error": execution_error,
        "classification": "CURRENT_V22_V23_GATE_LACKS_ST_DEV_ST_INO_INDEPENDENCE_CHECK",
        "upgrade_authorized": False,
        "authorization": False,
        "maximum_new_submissions": 0,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": status, "same_inode": same_inode, "gate_accepted": gate_accepted, "fixture_removed": fixture_removed, "content_unchanged": content_unchanged}))
    return 0 if gap_confirmed else 1


if __name__ == "__main__":
    raise SystemExit(main())
