#!/usr/bin/env python3
"""Read-only V43 closed-keyset and cross-field audit for V23-V38 projections."""
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

V41_AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v41_projection_field_schema_integrity_v1/E40_U29C_V41_SCHEDULER_PROJECTION_FIELD_SCHEMA_INTEGRITY_AUDIT_V2.json"
V41_AUDIT_SHA = "b9c7c8371d5d133ec84623320f10895a4b75f1505c950608f1fcce7d4f166f68"
V42_RUNNER = ROOT / "tools/run_e40_u29c_v42_pinned_projection_field_schema_regression.py"
V42_RUNNER_SHA = "1d561a3b063658e8afd804fa30738010838257c3e5fcf6d448efcc1e91c1f7dc"
V42_MATRIX = ROOT / "qa/e40_preproduction_20260808/u29c_v42_pinned_projection_schema_regression_v1/E40_U29C_V42_PINNED_PROJECTION_FIELD_SCHEMA_REGRESSION_MATRIX_V1.json"
V42_MATRIX_SHA = "2e504170c5e2124556481e4bc2389f55668fe6cfcd11c23b3e9973551c56eae5"
SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v43_projection_keyset_crossfield_integrity_v1/E40_U29C_V43_PROJECTION_KEYSET_CROSSFIELD_INTEGRITY_SPEC_V1.json"
SPEC_SHA = "f289d3a47ba562c6f1c5259d6a8b004268d78b47ef8811127ab8ca4139f40dfc"
MEMORY = ROOT / "workflow/prompt_memory/E40_U29C_V41_QA_FALSE_NEGATIVE_MEMORY_V1.md"
MEMORY_SHA = "ac9e7b03d1362d185d17b7ab436306fd5ceb407a0b0f88be495c52a2462da00f"
CANON = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CANON_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
CANON_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
CANON_MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
SCHED = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
REPORT = SPEC.parent / "E40_U29C_V43_PROJECTION_KEYSET_CROSSFIELD_INTEGRITY_AUDIT_V1.json"
PASS = "PASS_V23_TO_V38_EXACT_15_KEY_PROJECTIONS_CROSSFIELD_16_OF_16_NO_MUTATION_NO_SUBMIT"


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


def load_v41():
    path = ROOT / "tools/audit_e40_u29c_v41_scheduler_projection_field_schema_integrity.py"
    module_spec = importlib.util.spec_from_file_location("e40_u29c_v41_key_authority", path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError("V41_AUDITOR_IMPORT_UNAVAILABLE")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def negatives() -> list[dict]:
    rows = []
    for flag in ("--v41-audit", "--v42-runner", "--v42-matrix", "--spec", "--memory", "--scheduler", "--canonical", "--canonical-manifest"):
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), flag, "/tmp/forbidden-substitution"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        rows.append({"argument": flag, "exit_code": proc.returncode,
                     "rejected_before_audit": proc.returncode == 2,
                     "report_created": REPORT.exists()})
    return rows


def main() -> int:
    argparse.ArgumentParser(
        description="Fixed V43 closed-keyset/cross-field audit; substitutions forbidden.",
        allow_abbrev=False,
    ).parse_args()
    if REPORT.exists():
        raise SystemExit("REPORT_ALREADY_EXISTS")
    pins = [(V41_AUDIT, V41_AUDIT_SHA), (V42_RUNNER, V42_RUNNER_SHA),
            (V42_MATRIX, V42_MATRIX_SHA), (SPEC, SPEC_SHA), (MEMORY, MEMORY_SHA),
            (CANON, CANON_SHA), (CANON_MANIFEST, CANON_MANIFEST_SHA)]
    pins_before = [identity(path) for path, _ in pins]
    matches = [row["sha256"] == expected for row, (_, expected) in zip(pins_before, pins)]
    if not all(matches):
        print(json.dumps({"status": "FAIL_CLOSED_PIN_MISMATCH", "pin_matches": matches}))
        return 1

    failures: list[str] = []
    substitution_rows = negatives()
    if REPORT.exists() or not all(row["rejected_before_audit"] and not row["report_created"] for row in substitution_rows):
        failures.append("SUBSTITUTION_NOT_REJECTED")
    v41 = load_v41()
    authority = json.loads(V41_AUDIT.read_text())
    v42 = json.loads(V42_MATRIX.read_text())
    authority_valid = authority.get("status") == v41.PASS and authority.get("failures") == []
    v42_valid = v42.get("status") == "PASS_PINNED_V41_PROJECTION_FIELD_SCHEMA_16_OF_16_FAILED_MEMORY_PRESERVED_NO_MUTATION_NO_SUBMIT" and v42.get("failures") == []
    memory_exact = "status syntax is exactly `^PASS_[A-Z0-9_]+$`" in MEMORY.read_text()
    if not authority_valid:
        failures.append("V41_AUTHORITY_NOT_PASS_CLOSED")
    if not v42_valid:
        failures.append("V42_AUTHORITY_NOT_PASS_CLOSED")
    if not memory_exact or v41.STATUS_RE.pattern != r"^PASS_[A-Z0-9_]+$":
        failures.append("SYNTAX_SEMANTICS_SEPARATION_NOT_EXACT")

    expected_rows = authority.get("projection_after") or []
    sched_before = json.loads(SCHED.read_text())
    task_map = {task["task_id"]: task for task in sched_before["tasks"]}
    projection_before = [v41.project(task_map.get(row.get("task_id"))) for row in expected_rows]
    exact_keys = set(v41.FIELDS)
    rows = []
    for index, expected in enumerate(expected_rows):
        task = task_map.get(expected.get("task_id"))
        projection = v41.project(task)
        predecessor = "E40-U29C-V22-RECOVERED-SUCCESS-RECEIPT-AND-CRASH-BOUNDARY-AUDIT-NO-SUBMIT" if index == 0 else expected_rows[index - 1]["task_id"]
        keyset = projection is not None and set(projection) == exact_keys and len(projection) == 15
        no_nulls = projection is not None and all(value is not None for value in projection.values())
        no_undeclared = projection is not None and not (set(projection) - exact_keys)
        terminal = bool(task and task["state"] == "TERMINAL" and v41.parse_utc(task["completed_at"]) is not None and v41.STATUS_RE.fullmatch(task["terminal_status"]))
        evidence = bool(task and v41.canonical_repo_json_path(task["evidence_ref"]) and v41.SHA_RE.fullmatch(task["evidence_sha256"]) and digest(ROOT / task["evidence_ref"]) == task["evidence_sha256"])
        topology = bool(task and task["exact_predecessor_task_id"] == predecessor)
        zero = bool(task and task["zero_cost"] is True and task["maximum_new_submissions"] == 0 and task["authorization"] is False and task["provider_post_allowed"] is False and task["provider_calls"] == task["transactions"] == task["credits"] == 0)
        exact = projection == expected
        passed = all((keyset, no_nulls, no_undeclared, terminal, evidence, topology, zero, exact))
        rows.append({"ordinal": index + 23, "task_id": expected.get("task_id"),
                     "exact_closed_15_key_set": keyset, "no_null_values": no_nulls,
                     "no_undeclared_keys": no_undeclared,
                     "terminal_completion_status_invariant": terminal,
                     "evidence_path_sha_invariant": evidence,
                     "predecessor_topology_invariant": topology,
                     "explicit_zero_authority_invariant": zero,
                     "v41_projection_authority_exact": exact, "passed": passed,
                     "projection": projection})
    if len(rows) != 16 or not all(row["passed"] for row in rows):
        failures.append("KEYSET_CROSSFIELD_NOT_16_OF_16")
    canonical_exact = sched_before.get("canonical_script_sha256") == CANON_SHA and sched_before.get("canonical_manifest_sha256") == CANON_MANIFEST_SHA
    if not canonical_exact:
        failures.append("CANONICAL_BINDING_NOT_EXACT")

    sched_after = json.loads(SCHED.read_text())
    after_map = {task["task_id"]: task for task in sched_after["tasks"]}
    projection_after = [v41.project(after_map.get(row.get("task_id"))) for row in expected_rows]
    pins_after = [identity(path) for path, _ in pins]
    if projection_before != projection_after:
        failures.append("U29_PROJECTION_MUTATION")
    if pins_before != pins_after:
        failures.append("PIN_IDENTITY_MUTATION")
    status = PASS if not failures else "FAIL"
    payload = {"schema": "qingshan.e40.u29c.v43.projection_keyset_crossfield_integrity_audit.v1",
               "episode": "E40", "unit_id": "U29C",
               "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
               "status": status, "execution_permitted": False, "provider_post_allowed": False,
               "maximum_new_submissions": 0, "pins_before": pins_before,
               "pin_expected_sha256": [expected for _, expected in pins],
               "pin_match_count": sum(matches), "pins_after": pins_after,
               "v41_authority_valid": authority_valid, "v42_authority_valid": v42_valid,
               "failed_memory_and_syntax_semantics_separation_exact": memory_exact,
               "canonical_binding_exact": canonical_exact, "projection_task_count": len(rows),
               "exact_closed_15_keyset_count": sum(row["exact_closed_15_key_set"] for row in rows),
               "no_null_count": sum(row["no_null_values"] for row in rows),
               "no_undeclared_key_count": sum(row["no_undeclared_keys"] for row in rows),
               "terminal_crossfield_count": sum(row["terminal_completion_status_invariant"] for row in rows),
               "evidence_crossfield_count": sum(row["evidence_path_sha_invariant"] for row in rows),
               "predecessor_topology_count": sum(row["predecessor_topology_invariant"] for row in rows),
               "zero_authority_count": sum(row["explicit_zero_authority_invariant"] for row in rows),
               "projection_rows": rows, "projection_before": projection_before,
               "projection_after": projection_after, "no_authority_elevation": True,
               "substitution_negatives": substitution_rows,
               "substitution_negative_count": sum(row["rejected_before_audit"] for row in substitution_rows),
               "blind_replay_allowed": False, "failures": failures,
               "side_effects": {"provider_calls": 0, "transactions": 0, "credits": 0, "retries": 0, "agentcut": 0, "assembly": 0},
               "next_action": "Register V44 pinned projection keyset/cross-field regression."}
    fd = os.open(REPORT, base.create_flags(), 0o600)
    base.write_all(fd, (json.dumps(payload, indent=2) + "\n").encode())
    os.fsync(fd); os.close(fd)
    print(json.dumps({"status": status, "pins": payload["pin_match_count"],
                      "projection": len(rows), "keysets": payload["exact_closed_15_keyset_count"],
                      "no_nulls": payload["no_null_count"], "crossfield_terminal": payload["terminal_crossfield_count"],
                      "crossfield_evidence": payload["evidence_crossfield_count"],
                      "topology": payload["predecessor_topology_count"], "zero_authority": payload["zero_authority_count"],
                      "substitution_negatives": payload["substitution_negative_count"], "failures": failures}))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
