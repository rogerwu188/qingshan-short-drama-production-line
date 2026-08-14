#!/usr/bin/env python3
"""Run eight unique V14 local outputs with at most four workers."""

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
V13_MATRIX = ROOT / "qa/e40_preproduction_20260808/u29c_v13_pinned_separate_stage_regression_v1/E40_U29C_V13_PINNED_RESIDUE_PARENT_CONTAINMENT_MATRIX_V1.json"
V13_MATRIX_SHA256 = "bfe3b8279390c59ed8ca572ae299645da5d81164c188c5de41f45a925f9c7ee3"
V14_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v14_concurrent_stage_isolation_v1/E40_U29C_V14_BOUNDED_CONCURRENT_STAGE_ISOLATION_SPEC_V1.json"
V14_SPEC_SHA256 = "1f5e803d07ee466a271ed8d0a47c772787ad5de945aa29a05c85653e62969aaa"
CANONICAL = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CANONICAL_SHA256 = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
MANIFEST_SHA256 = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
OUTPUT_NAMES = [f"E40_U29C_V14_CONCURRENT_UNIQUE_{index:02d}_GATE_V1.json" for index in range(1, 9)]
MAX_WORKERS = 4
REPORT = ROOT / "qa/e40_preproduction_20260808/u29c_v14_concurrent_stage_isolation_v1/E40_U29C_V14_CONCURRENT_STAGE_ISOLATION_MATRIX_V1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stage_entries() -> list[str]:
    return sorted(path.name for path in writer.STAGING_ROOT.iterdir())


def root_snapshot(path: Path) -> dict[str, Any]:
    value = os.stat(path, follow_symlinks=False)
    return {
        "path": str(path.relative_to(ROOT)),
        "device": value.st_dev,
        "inode": value.st_ino,
        "mode": oct(stat.S_IMODE(value.st_mode)),
        "is_directory": stat.S_ISDIR(value.st_mode),
        "is_symlink": path.is_symlink(),
    }


def normalized_report(report: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(report))
    value.pop("recorded_at", None)
    return value


def run_one(index: int, name: str) -> dict[str, Any]:
    output = writer.FINAL_ROOT / name
    completed = subprocess.run(
        [sys.executable, str(INVOKER), "--output-name", name],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    value = os.stat(output, follow_symlinks=False) if output.is_file() else None
    passed = (
        completed.returncode == 0
        and "PASS_SEPARATE_STAGE_ATOMIC_RESERVED_FAIL_CLOSED_NO_SUBMIT" in completed.stdout
        and report.get("status") == "PASS_EXPECTED_FAIL_CLOSED_NO_SUBMIT"
        and report.get("execution_permitted") is False
        and value is not None
        and stat.S_ISREG(value.st_mode)
        and value.st_nlink == 1
    )
    return {
        "index": index,
        "name": name,
        "passed": passed,
        "returncode": completed.returncode,
        "stderr": completed.stderr.strip(),
        "output": str(output.relative_to(ROOT)),
        "output_sha256": digest(output) if output.is_file() else None,
        "device": value.st_dev if value else None,
        "inode": value.st_ino if value else None,
        "link_count": value.st_nlink if value else None,
        "report": report,
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
    if REPORT.exists() or REPORT.is_symlink():
        raise SystemExit("REPORT_ALREADY_EXISTS")
    if len(OUTPUT_NAMES) != 8 or len(set(OUTPUT_NAMES)) != 8 or MAX_WORKERS != 4:
        raise SystemExit("BOUNDED_LOAD_CONTRACT_MISMATCH")
    outputs = [writer.FINAL_ROOT / name for name in OUTPUT_NAMES]
    if any(path.exists() or path.is_symlink() for path in outputs):
        raise SystemExit("ONE_OR_MORE_TARGET_OUTPUTS_ALREADY_EXIST")
    pins = [INVOKER, V12_WRITER, V13_MATRIX, V14_SPEC, CANONICAL, MANIFEST]
    expected = {
        str(INVOKER.relative_to(ROOT)): INVOKER_SHA256,
        str(V12_WRITER.relative_to(ROOT)): V12_WRITER_SHA256,
        str(V13_MATRIX.relative_to(ROOT)): V13_MATRIX_SHA256,
        str(V14_SPEC.relative_to(ROOT)): V14_SPEC_SHA256,
        str(CANONICAL.relative_to(ROOT)): CANONICAL_SHA256,
        str(MANIFEST.relative_to(ROOT)): MANIFEST_SHA256,
    }
    pins_before = {str(path.relative_to(ROOT)): digest(path) for path in pins}
    pin_failures = [name for name, value in expected.items() if pins_before.get(name) != value]
    roots_before = {"final": root_snapshot(writer.FINAL_ROOT), "staging": root_snapshot(writer.STAGING_ROOT)}
    residue_before = stage_entries()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="u29c-v14") as executor:
        futures = {executor.submit(run_one, index, name): index for index, name in enumerate(OUTPUT_NAMES, 1)}
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item["index"])
    residue_after = stage_entries()
    roots_after = {"final": root_snapshot(writer.FINAL_ROOT), "staging": root_snapshot(writer.STAGING_ROOT)}
    pins_after = {str(path.relative_to(ROOT)): digest(path) for path in pins}

    inode_tokens = [(item["device"], item["inode"]) for item in results]
    normalized = [normalized_report(item["report"]) for item in results]
    all_valid = all(item["passed"] for item in results)
    distinct_inodes = len(set(inode_tokens)) == len(OUTPUT_NAMES)
    normalized_match = len({json.dumps(value, ensure_ascii=False, sort_keys=True) for value in normalized}) == 1
    roots_unchanged = roots_before == roots_after
    pins_unchanged = pins_before == pins_after
    failures: list[str] = []
    failures.extend(pin_failures)
    if not all_valid:
        failures.append("ONE_OR_MORE_CONCURRENT_OUTPUTS_INVALID")
    if not distinct_inodes:
        failures.append("OUTPUT_INODE_COLLISION")
    if not normalized_match:
        failures.append("CROSS_OUTPUT_NORMALIZED_CONTENT_MISMATCH")
    if residue_before != [] or residue_after != []:
        failures.append("SHARED_STAGING_RESIDUE_NONZERO")
    if not roots_unchanged:
        failures.append("ROOT_IDENTITY_OR_MODE_DRIFT")
    if not pins_unchanged:
        failures.append("PINNED_INPUT_MUTATION")
    status = "PASS_8_OUTPUT_4_WORKER_STAGE_ISOLATION_ZERO_RESIDUE_NO_SUBMIT" if not failures else "FAIL"
    compact_results = [{key: value for key, value in item.items() if key != "report"} for item in results]
    payload = {
        "schema": "qingshan.e40.u29c.v14.concurrent_stage_isolation_matrix.v1",
        "episode": "E40",
        "unit_id": "U29C",
        "recorded_at": stamp(),
        "status": status,
        "execution_permitted": False,
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "bounded_load": {"unique_output_count": len(OUTPUT_NAMES), "maximum_workers": MAX_WORKERS},
        "pins_before": pins_before,
        "pins_after": pins_after,
        "roots_before": roots_before,
        "roots_after": roots_after,
        "staging_entries_before": residue_before,
        "staging_entries_after": residue_after,
        "all_outputs_valid": all_valid,
        "distinct_output_inodes": distinct_inodes,
        "normalized_reports_match": normalized_match,
        "results": compact_results,
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
            "Keep execution closed. Register a bounded same-basename contention successor through the pinned "
            "invoker and require exactly one winner, all other O_EXCL losers, and zero stage residue."
        ),
    }
    write_exclusive(REPORT, payload)
    print(json.dumps({"status": status, "report": str(REPORT), "failures": failures}, ensure_ascii=False))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
