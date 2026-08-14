#!/usr/bin/env python3
"""Read-only V41 schema/type/syntax/time audit for V23-V38 projections."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base

V39 = ROOT / "qa/e40_preproduction_20260808/u29c_v39_scheduler_projection_integrity_v1/E40_U29C_V39_CANONICAL_CHAIN_SCHEDULER_PROJECTION_INTEGRITY_AUDIT_V1.json"
V39_SHA = "030862b95fe90beb3d47f2e0600724e9403d261a69b37b857b129d1a45b5a9d5"
V40_RUNNER = ROOT / "tools/run_e40_u29c_v40_pinned_scheduler_projection_regression.py"
V40_RUNNER_SHA = "a5a1419a5072874875f4d60594c9470ab3e9543325a1f998c32d3ab4cafe0de1"
V40_MATRIX = ROOT / "qa/e40_preproduction_20260808/u29c_v40_pinned_scheduler_projection_regression_v1/E40_U29C_V40_PINNED_SCHEDULER_PROJECTION_REGRESSION_MATRIX_V1.json"
V40_MATRIX_SHA = "4d9099808f8604ef00de15ff631fbddd1ab75c2b2555838d8fcea512a334e6b1"
SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v41_projection_field_schema_integrity_v1/E40_U29C_V41_SCHEDULER_PROJECTION_FIELD_SCHEMA_INTEGRITY_SPEC_V1.json"
SPEC_SHA = "b2c6354932b86e8f986ed72b2250574f7f2ef0db4e0fcf7ac49243e342044d25"
CANON = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CANON_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
CANON_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
CANON_MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
SCHED = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
REPORT = SPEC.parent / "E40_U29C_V41_SCHEDULER_PROJECTION_FIELD_SCHEMA_INTEGRITY_AUDIT_V2.json"
PASS = "PASS_V23_TO_V38_PROJECTION_FIELD_SCHEMA_16_OF_16_TYPES_SYNTAX_UTC_ORDER_NO_MUTATION_NO_SUBMIT"
FIELDS = (
    "task_id", "lane_id", "state", "zero_cost", "exact_predecessor_task_id",
    "evidence_ref", "evidence_sha256", "maximum_new_submissions", "authorization",
    "provider_post_allowed", "provider_calls", "transactions", "credits",
    "terminal_status", "completed_at",
)
STRING_FIELDS = {
    "task_id", "lane_id", "state", "exact_predecessor_task_id", "evidence_ref",
    "evidence_sha256", "terminal_status", "completed_at",
}
BOOL_FIELDS = {"zero_cost", "authorization", "provider_post_allowed"}
INT_FIELDS = {"maximum_new_submissions", "provider_calls", "transactions", "credits"}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TASK_RE = re.compile(r"^E40-U29C-V(?:2[3-9]|3[0-8])-[A-Z0-9-]+-NO-SUBMIT$")
STATUS_RE = re.compile(r"^PASS_[A-Z0-9_]+$")


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


def exact_type(value: object, field: str) -> bool:
    if field in STRING_FIELDS:
        return type(value) is str
    if field in BOOL_FIELDS:
        return type(value) is bool
    if field in INT_FIELDS:
        return type(value) is int
    return False


def parse_utc(value: object) -> datetime | None:
    if type(value) is not str or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.utcoffset() == timezone.utc.utcoffset(parsed) else None


def canonical_repo_json_path(value: object) -> bool:
    if type(value) is not str or not value.endswith(".json") or value.startswith("/"):
        return False
    path = PurePosixPath(value)
    if value != path.as_posix() or ".." in path.parts or "." in path.parts:
        return False
    resolved = (ROOT / value).resolve()
    return resolved.is_relative_to(ROOT.resolve()) and resolved.is_file()


def project(task: dict | None) -> dict | None:
    return {key: task.get(key) for key in FIELDS} if task else None


def substitution_negatives() -> list[dict]:
    rows = []
    for flag in ("--v39-audit", "--v40-runner", "--v40-matrix", "--spec", "--scheduler", "--canonical", "--canonical-manifest"):
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), flag, "/tmp/forbidden-substitution"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        rows.append({
            "argument": flag, "exit_code": proc.returncode,
            "rejected_before_audit": proc.returncode == 2,
            "report_created": REPORT.exists(),
        })
    return rows


def main() -> int:
    argparse.ArgumentParser(
        description="Fixed V41 projection schema integrity audit; substitutions forbidden.",
        allow_abbrev=False,
    ).parse_args()
    if REPORT.exists():
        raise SystemExit("REPORT_ALREADY_EXISTS")

    pins = [
        (V39, V39_SHA), (V40_RUNNER, V40_RUNNER_SHA), (V40_MATRIX, V40_MATRIX_SHA),
        (SPEC, SPEC_SHA), (CANON, CANON_SHA), (CANON_MANIFEST, CANON_MANIFEST_SHA),
    ]
    pins_before = [identity(path) for path, _ in pins]
    pin_matches = [item["sha256"] == expected for item, (_, expected) in zip(pins_before, pins)]
    if not all(pin_matches):
        print(json.dumps({"status": "FAIL_CLOSED_PIN_MISMATCH", "pin_matches": pin_matches}))
        return 1

    failures: list[str] = []
    negatives = substitution_negatives()
    if REPORT.exists() or not all(row["rejected_before_audit"] and not row["report_created"] for row in negatives):
        failures.append("SUBSTITUTION_NOT_REJECTED")

    v39 = json.loads(V39.read_text())
    authority = v39.get("projection_after")
    if not isinstance(authority, list) or len(authority) != 16:
        failures.append("V39_PROJECTION_AUTHORITY_NOT_16")
        authority = []

    sched_before = json.loads(SCHED.read_text())
    task_map_before = {task["task_id"]: task for task in sched_before["tasks"]}
    projection_before = [project(task_map_before.get(row.get("task_id"))) for row in authority]
    rows = []
    previous_time: datetime | None = None
    for ordinal, expected in enumerate(authority, start=23):
        task = task_map_before.get(expected.get("task_id"))
        required_present = task is not None and all(field in task for field in FIELDS)
        types_exact = required_present and all(exact_type(task[field], field) for field in FIELDS)
        timestamp = parse_utc(task.get("completed_at") if task else None)
        utc_syntax = timestamp is not None
        timestamp_ordered = utc_syntax and (previous_time is None or timestamp > previous_time)
        if timestamp is not None:
            previous_time = timestamp
        task_syntax = task is not None and bool(TASK_RE.fullmatch(task.get("task_id", "")))
        sha_syntax = task is not None and bool(SHA_RE.fullmatch(task.get("evidence_sha256", "")))
        path_syntax = task is not None and canonical_repo_json_path(task.get("evidence_ref"))
        status_syntax = task is not None and bool(STATUS_RE.fullmatch(task.get("terminal_status", "")))
        authority_exact = project(task) == expected if task else False
        physical_sha_exact = bool(
            task and path_syntax and digest(ROOT / task["evidence_ref"]) == task["evidence_sha256"]
        )
        zero_authority = bool(
            task and task["zero_cost"] is True and task["maximum_new_submissions"] == 0
            and task["authorization"] is False and task["provider_post_allowed"] is False
            and task["provider_calls"] == task["transactions"] == task["credits"] == 0
        )
        passed = all((required_present, types_exact, utc_syntax, timestamp_ordered, task_syntax,
                      sha_syntax, path_syntax, status_syntax, authority_exact, physical_sha_exact,
                      zero_authority))
        rows.append({
            "ordinal": ordinal, "task_id": expected.get("task_id"),
            "required_fields_present": required_present, "exact_json_types": types_exact,
            "task_id_syntax": task_syntax, "evidence_sha256_syntax": sha_syntax,
            "evidence_path_canonical_repo_json": path_syntax,
            "terminal_status_syntax": status_syntax, "utc_timestamp_syntax": utc_syntax,
            "strictly_after_previous_timestamp": timestamp_ordered,
            "v39_projection_authority_exact": authority_exact,
            "physical_evidence_sha_exact": physical_sha_exact,
            "explicit_zero_authority": zero_authority, "passed": passed,
            "projection": project(task),
        })

    if len(rows) != 16 or not all(row["passed"] for row in rows):
        failures.append("FIELD_SCHEMA_NOT_16_OF_16_EXACT")
    canonical_exact = (
        sched_before.get("canonical_script_sha256") == CANON_SHA
        and sched_before.get("canonical_manifest_sha256") == CANON_MANIFEST_SHA
    )
    if not canonical_exact:
        failures.append("CANONICAL_BINDING_NOT_EXACT")

    sched_after = json.loads(SCHED.read_text())
    task_map_after = {task["task_id"]: task for task in sched_after["tasks"]}
    projection_after = [project(task_map_after.get(row.get("task_id"))) for row in authority]
    pins_after = [identity(path) for path, _ in pins]
    if projection_before != projection_after:
        failures.append("U29_PROJECTION_MUTATION")
    if pins_before != pins_after:
        failures.append("PIN_IDENTITY_MUTATION")

    status = PASS if not failures else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29c.v41.scheduler_projection_field_schema_integrity_audit.v2",
        "episode": "E40", "unit_id": "U29C",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status, "execution_permitted": False, "provider_post_allowed": False,
        "maximum_new_submissions": 0, "pins_before": pins_before,
        "pin_expected_sha256": [expected for _, expected in pins],
        "pin_match_count": sum(pin_matches), "pins_after": pins_after,
        "canonical_binding_exact": canonical_exact, "projection_task_count": len(rows),
        "required_fields_exact_count": sum(row["required_fields_present"] for row in rows),
        "exact_json_types_count": sum(row["exact_json_types"] for row in rows),
        "syntax_exact_count": sum(all((row["task_id_syntax"], row["evidence_sha256_syntax"], row["evidence_path_canonical_repo_json"], row["terminal_status_syntax"])) for row in rows),
        "utc_timestamp_syntax_count": sum(row["utc_timestamp_syntax"] for row in rows),
        "strict_timestamp_order_count": sum(row["strictly_after_previous_timestamp"] for row in rows),
        "physical_evidence_match_count": sum(row["physical_evidence_sha_exact"] for row in rows),
        "zero_authority_count": sum(row["explicit_zero_authority"] for row in rows),
        "projection_rows": rows, "projection_before": projection_before,
        "projection_after": projection_after, "no_authority_elevation": True,
        "substitution_negatives": negatives,
        "substitution_negative_count": sum(row["rejected_before_audit"] for row in negatives),
        "blind_replay_allowed": False, "failures": failures,
        "side_effects": {"provider_calls": 0, "transactions": 0, "credits": 0, "retries": 0, "agentcut": 0, "assembly": 0},
        "next_action": "Register V42 pinned projection field-schema regression.",
    }
    fd = os.open(REPORT, base.create_flags(), 0o600)
    base.write_all(fd, (json.dumps(payload, indent=2) + "\n").encode())
    os.fsync(fd)
    os.close(fd)
    print(json.dumps({
        "status": status, "projection": len(rows),
        "fields": payload["required_fields_exact_count"], "types": payload["exact_json_types_count"],
        "syntax": payload["syntax_exact_count"], "utc_order": payload["strict_timestamp_order_count"],
        "evidence": payload["physical_evidence_match_count"],
        "zero_authority": payload["zero_authority_count"],
        "substitution_negatives": payload["substitution_negative_count"], "failures": failures,
    }))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
