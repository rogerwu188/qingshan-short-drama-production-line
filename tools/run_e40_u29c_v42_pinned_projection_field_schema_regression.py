#!/usr/bin/env python3
"""Pinned V42 regression over the corrected V41 projection schema authority."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base

AUDITOR = ROOT / "tools/audit_e40_u29c_v41_scheduler_projection_field_schema_integrity.py"
AUDITOR_SHA = "5ec2bab6acd2dda995fe3dea16348e173e6a6e855593a72ead7ca77105f94e76"
AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v41_projection_field_schema_integrity_v1/E40_U29C_V41_SCHEDULER_PROJECTION_FIELD_SCHEMA_INTEGRITY_AUDIT_V2.json"
AUDIT_SHA = "b9c7c8371d5d133ec84623320f10895a4b75f1505c950608f1fcce7d4f166f68"
FAILED = ROOT / "qa/e40_preproduction_20260808/u29c_v41_projection_field_schema_integrity_v1/E40_U29C_V41_SCHEDULER_PROJECTION_FIELD_SCHEMA_INTEGRITY_AUDIT_V1.json"
FAILED_SHA = "8e82958011ebc4985a8f1de34d41a6903651bd91e8dd6b92c1438d63c05fb948"
MEMORY = ROOT / "workflow/prompt_memory/E40_U29C_V41_QA_FALSE_NEGATIVE_MEMORY_V1.md"
MEMORY_SHA = "ac9e7b03d1362d185d17b7ab436306fd5ceb407a0b0f88be495c52a2462da00f"
SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v42_pinned_projection_schema_regression_v1/E40_U29C_V42_PINNED_PROJECTION_FIELD_SCHEMA_REGRESSION_SPEC_V1.json"
SPEC_SHA = "6f6cbca0b28d7a1b407a94633d94ef8f396763b7a2981dec7f0f9910738a0207"
CANON = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CANON_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
CANON_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
CANON_MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
SCHED = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
REPORT = SPEC.parent / "E40_U29C_V42_PINNED_PROJECTION_FIELD_SCHEMA_REGRESSION_MATRIX_V1.json"
PASS = "PASS_PINNED_V41_PROJECTION_FIELD_SCHEMA_16_OF_16_FAILED_MEMORY_PRESERVED_NO_MUTATION_NO_SUBMIT"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    stat = os.lstat(path)
    return {
        "path": str(path.relative_to(ROOT)), "sha256": digest(path),
        "device": stat.st_dev, "inode": stat.st_ino, "mode": oct(stat.st_mode & 0o7777),
        "nlink": stat.st_nlink, "uid": stat.st_uid, "gid": stat.st_gid,
        "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns,
    }


def load_auditor():
    spec = importlib.util.spec_from_file_location("e40_u29c_v41_fixed_auditor", AUDITOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("AUDITOR_IMPORT_SPEC_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def substitutions() -> list[dict]:
    rows = []
    for flag in ("--auditor", "--audit", "--failed-audit", "--memory", "--spec", "--scheduler", "--canonical", "--canonical-manifest"):
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), flag, "/tmp/forbidden-substitution"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        rows.append({
            "argument": flag, "exit_code": proc.returncode,
            "rejected_before_regression": proc.returncode == 2,
            "report_created": REPORT.exists(),
        })
    return rows


def main() -> int:
    argparse.ArgumentParser(
        description="Fixed V42 pinned schema regression; substitutions forbidden.",
        allow_abbrev=False,
    ).parse_args()
    if REPORT.exists():
        raise SystemExit("REPORT_ALREADY_EXISTS")
    pins = [
        (AUDITOR, AUDITOR_SHA), (AUDIT, AUDIT_SHA), (FAILED, FAILED_SHA),
        (MEMORY, MEMORY_SHA), (SPEC, SPEC_SHA), (CANON, CANON_SHA),
        (CANON_MANIFEST, CANON_MANIFEST_SHA),
    ]
    before_pins = [identity(path) for path, _ in pins]
    pin_matches = [row["sha256"] == expected for row, (_, expected) in zip(before_pins, pins)]
    if not all(pin_matches):
        print(json.dumps({"status": "FAIL_CLOSED_PIN_MISMATCH", "pin_matches": pin_matches}))
        return 1

    failures: list[str] = []
    negative_rows = substitutions()
    if REPORT.exists() or not all(row["rejected_before_regression"] and not row["report_created"] for row in negative_rows):
        failures.append("SUBSTITUTION_NOT_REJECTED")

    auditor = load_auditor()
    authority = json.loads(AUDIT.read_text())
    failed = json.loads(FAILED.read_text())
    authority_valid = (
        authority.get("status") == auditor.PASS and authority.get("failures") == []
        and authority.get("projection_task_count") == 16
        and authority.get("required_fields_exact_count") == 16
        and authority.get("exact_json_types_count") == 16
        and authority.get("syntax_exact_count") == 16
        and authority.get("utc_timestamp_syntax_count") == 16
        and authority.get("strict_timestamp_order_count") == 16
        and authority.get("physical_evidence_match_count") == 16
        and authority.get("zero_authority_count") == 16
    )
    memory_preserved = (
        failed.get("status") == "FAIL"
        and failed.get("failures") == ["FIELD_SCHEMA_NOT_16_OF_16_EXACT"]
        and "status syntax" in MEMORY.read_text()
        and auditor.STATUS_RE.pattern == r"^PASS_[A-Z0-9_]+$"
    )
    if not authority_valid:
        failures.append("V41_PASSING_AUTHORITY_NOT_EXACT")
    if not memory_preserved:
        failures.append("FAILED_ATTEMPT_MEMORY_NOT_PRESERVED")

    sched_before = json.loads(SCHED.read_text())
    task_map = {task["task_id"]: task for task in sched_before["tasks"]}
    expected_rows = authority.get("projection_after") or []
    projection_before = [auditor.project(task_map.get(row.get("task_id"))) for row in expected_rows]
    rows = []
    previous_time = None
    for ordinal, expected in enumerate(expected_rows, start=23):
        task = task_map.get(expected.get("task_id"))
        required = task is not None and all(field in task for field in auditor.FIELDS)
        types = required and all(auditor.exact_type(task[field], field) for field in auditor.FIELDS)
        stamp = auditor.parse_utc(task.get("completed_at") if task else None)
        utc = stamp is not None
        ordered = utc and (previous_time is None or stamp > previous_time)
        if stamp is not None:
            previous_time = stamp
        syntax = bool(
            task and auditor.TASK_RE.fullmatch(task.get("task_id", ""))
            and auditor.SHA_RE.fullmatch(task.get("evidence_sha256", ""))
            and auditor.canonical_repo_json_path(task.get("evidence_ref"))
            and auditor.STATUS_RE.fullmatch(task.get("terminal_status", ""))
        )
        authority_exact = auditor.project(task) == expected if task else False
        evidence = bool(task and syntax and digest(ROOT / task["evidence_ref"]) == task["evidence_sha256"])
        zero = bool(
            task and task["zero_cost"] is True and task["maximum_new_submissions"] == 0
            and task["authorization"] is False and task["provider_post_allowed"] is False
            and task["provider_calls"] == task["transactions"] == task["credits"] == 0
        )
        passed = all((required, types, utc, ordered, syntax, authority_exact, evidence, zero))
        rows.append({
            "ordinal": ordinal, "task_id": expected.get("task_id"),
            "required_fields_present": required, "exact_json_types": types,
            "syntax_exact": syntax, "utc_timestamp_syntax": utc,
            "strictly_after_previous_timestamp": ordered,
            "v41_projection_authority_exact": authority_exact,
            "physical_evidence_sha_exact": evidence, "explicit_zero_authority": zero,
            "passed": passed, "projection": auditor.project(task),
        })
    if len(rows) != 16 or not all(row["passed"] for row in rows):
        failures.append("PINNED_SCHEMA_REGRESSION_NOT_16_OF_16")
    canonical_exact = (
        sched_before.get("canonical_script_sha256") == CANON_SHA
        and sched_before.get("canonical_manifest_sha256") == CANON_MANIFEST_SHA
    )
    if not canonical_exact:
        failures.append("CANONICAL_BINDING_NOT_EXACT")

    sched_after = json.loads(SCHED.read_text())
    after_map = {task["task_id"]: task for task in sched_after["tasks"]}
    projection_after = [auditor.project(after_map.get(row.get("task_id"))) for row in expected_rows]
    after_pins = [identity(path) for path, _ in pins]
    if projection_before != projection_after:
        failures.append("U29_PROJECTION_MUTATION")
    if before_pins != after_pins:
        failures.append("PIN_IDENTITY_MUTATION")

    status = PASS if not failures else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29c.v42.pinned_projection_field_schema_regression_matrix.v1",
        "episode": "E40", "unit_id": "U29C",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status, "execution_permitted": False, "provider_post_allowed": False,
        "maximum_new_submissions": 0, "pins_before": before_pins,
        "pin_expected_sha256": [expected for _, expected in pins],
        "pin_match_count": sum(pin_matches), "pins_after": after_pins,
        "v41_passing_authority_valid": authority_valid,
        "failed_attempt_and_memory_preserved": memory_preserved,
        "corrected_status_syntax_pattern": auditor.STATUS_RE.pattern,
        "canonical_binding_exact": canonical_exact, "projection_task_count": len(rows),
        "required_fields_exact_count": sum(row["required_fields_present"] for row in rows),
        "exact_json_types_count": sum(row["exact_json_types"] for row in rows),
        "syntax_exact_count": sum(row["syntax_exact"] for row in rows),
        "utc_timestamp_syntax_count": sum(row["utc_timestamp_syntax"] for row in rows),
        "strict_timestamp_order_count": sum(row["strictly_after_previous_timestamp"] for row in rows),
        "physical_evidence_match_count": sum(row["physical_evidence_sha_exact"] for row in rows),
        "zero_authority_count": sum(row["explicit_zero_authority"] for row in rows),
        "projection_rows": rows, "projection_before": projection_before,
        "projection_after": projection_after, "no_authority_elevation": True,
        "substitution_negatives": negative_rows,
        "substitution_negative_count": sum(row["rejected_before_regression"] for row in negative_rows),
        "blind_replay_allowed": False, "failures": failures,
        "side_effects": {"provider_calls": 0, "transactions": 0, "credits": 0, "retries": 0, "agentcut": 0, "assembly": 0},
        "next_action": "Register V43 projection schema closed-set key integrity audit.",
    }
    fd = os.open(REPORT, base.create_flags(), 0o600)
    base.write_all(fd, (json.dumps(payload, indent=2) + "\n").encode())
    os.fsync(fd)
    os.close(fd)
    print(json.dumps({
        "status": status, "pins": payload["pin_match_count"], "projection": len(rows),
        "fields": payload["required_fields_exact_count"], "types": payload["exact_json_types_count"],
        "syntax": payload["syntax_exact_count"], "utc_order": payload["strict_timestamp_order_count"],
        "evidence": payload["physical_evidence_match_count"], "zero_authority": payload["zero_authority_count"],
        "memory_preserved": memory_preserved,
        "substitution_negatives": payload["substitution_negative_count"], "failures": failures,
    }))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
