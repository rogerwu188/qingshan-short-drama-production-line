#!/usr/bin/env python3
"""Authorize an exact prechecked E40 keyframe wave under Roger's 5000-credit grant."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION_REF = "ROGER-20260821-E40-REBUILD-BUDGET-5000"
MAX_ATTEMPTS = 3
IMAGE_CREDITS_PER_TASK = 11


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def portable(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def belongs_to_original_unit(task_key: str, unit_id: str) -> bool:
    """Count the original shot lineage, never its SWITCH_COVERAGE children."""
    normalized = task_key.upper()
    if "SWITCH" in normalized or "-COV-" in normalized or "COVERAGE" in normalized:
        return False
    return re.search(rf"(?:^|-){re.escape(unit_id.upper())}(?:-|$)", normalized) is not None


def bound_prior_attempts(unit_id: str) -> list[dict[str, str]]:
    transaction_dir = ROOT / "workflow/tasks/giggle_submit_transactions"
    rows: list[dict[str, str]] = []
    for path in sorted(transaction_dir.rglob(f"*{unit_id}*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        task_key = str(row.get("task_key") or "")
        if (
            row.get("model") == "gpt-image-2-pro"
            and row.get("state") == "SUBMITTED_TASK_ID_BOUND"
            and belongs_to_original_unit(task_key, unit_id)
        ):
            rows.append({
                "task_key": str(row.get("task_key")),
                "task_id": str(row.get("task_id")),
                "transaction": portable(path),
            })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--precheck", required=True)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--gate-out", required=True)
    parser.add_argument("--switch-coverage", action="store_true")
    args = parser.parse_args()

    source_path = resolve(args.source)
    precheck_path = resolve(args.precheck)
    authorization_path = resolve(args.authorization)
    output_path = resolve(args.out)
    gate_path = resolve(args.gate_out)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    precheck = json.loads(precheck_path.read_text(encoding="utf-8"))
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))

    if precheck.get("status") != "PASS" or precheck.get("precheck_pass") != len(source.get("tasks") or []):
        raise ValueError("Exact source wave has not passed complete precheck")
    if authorization.get("status") != "AUTHORIZED" or authorization.get("authorization_ref") != AUTHORIZATION_REF:
        raise ValueError("E40 5000-credit authorization is missing or mismatched")

    tasks = source.get("tasks") or []
    attempt_evidence: dict[str, list[dict[str, str]]] = {}
    if args.switch_coverage:
        for task in tasks:
            if task.get("coverage_mode") != "SWITCH_COVERAGE" or not task.get("material_change"):
                raise ValueError(f"{task.get('task_key')} lacks material SWITCH_COVERAGE evidence")
            parent = str(task.get("replaces_unit") or "")
            if parent not in {"R01", "R06A"}:
                raise ValueError(f"{task.get('task_key')} has an unauthorized coverage parent")
            prior = bound_prior_attempts(parent)
            if len(prior) != MAX_ATTEMPTS:
                raise ValueError(f"{parent} must be capped at three attempts before SWITCH_COVERAGE, found {len(prior)}")
            attempt_evidence.setdefault(parent, prior)
            if list((ROOT / "workflow/tasks/giggle_submit_transactions").rglob(f"{task['task_key']}__*.json")):
                raise ValueError(f"{task['task_key']} already has a transaction")
    else:
        if {str(task.get("unit_id")) for task in tasks} != {"R01", "R06A"}:
            raise ValueError("The final-attempt wave must contain exactly R01 and R06A")
        for task in tasks:
            unit_id = str(task["unit_id"])
            prior = bound_prior_attempts(unit_id)
            if len(prior) != MAX_ATTEMPTS - 1:
                raise ValueError(f"{unit_id} must have exactly two authoritative prior paid attempts, found {len(prior)}")
            attempt_evidence[unit_id] = prior

    manifest = deepcopy(source)
    manifest.update({
        "episode": "E40",
        "status": "READY_TO_SUBMIT",
        "authorization_ref": AUTHORIZATION_REF,
        "provider_post_allowed": True,
        "maximum_new_submissions": len(tasks),
        "retry_policy": (
            "MATERIALLY_DIFFERENT_SWITCH_COVERAGE_FIRST_ATTEMPT; NO_VERSION_RENAME_BYPASS"
            if args.switch_coverage else
            "THIRD_AND_FINAL_PAID_KEYFRAME_ATTEMPT; NO_VERSION_RENAME_BYPASS"
        ),
        "excluded_retry_cap_units": [],
    })
    for task in manifest["tasks"]:
        task.update({
            "status": "READY_TO_SUBMIT",
            "provider_post_allowed": True,
            "maximum_new_submissions": 1,
            "authorization_ref": AUTHORIZATION_REF,
            "paid_attempt_ordinal": 1 if args.switch_coverage else MAX_ATTEMPTS,
            "terminal_if_not_admitted": True,
        })
    machine_gates = list(manifest.get("machine_gate_reports") or [])
    machine_gates.extend([portable(precheck_path), portable(gate_path)])
    manifest["machine_gate_reports"] = list(dict.fromkeys(machine_gates))
    write_json(output_path, manifest)

    projected = len(tasks) * IMAGE_CREDITS_PER_TASK
    if projected > int(authorization.get("maximum_additional_credits") or 0):
        raise ValueError("Projected wave cost exceeds the explicit authorization")
    gate = {
        "schema": "qingshan.e40.full_coverage_keyframe_wave_budget_gate.v1",
        "gate_id": "GIGGLE-REROLL-COST-GUARD",
        "episode": "E40",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS",
        "authorization_ref": AUTHORIZATION_REF,
        "authorization_file": portable(authorization_path),
        "authorization_file_sha256": sha256(authorization_path),
        "reviewed_manifest": portable(output_path),
        "reviewed_manifest_sha256": sha256(output_path),
        "task_count": len(tasks),
        "projected_credits": projected,
        "maximum_additional_credits": int(authorization["maximum_additional_credits"]),
        "max_paid_attempts_per_shot": MAX_ATTEMPTS,
        "attempt_evidence": attempt_evidence,
        "decision": (
            "ALLOW_MATERIALLY_DIFFERENT_SWITCH_COVERAGE_FIRST_ATTEMPT"
            if args.switch_coverage else
            "ALLOW_EXACT_TWO_TASK_THIRD_AND_FINAL_KEYFRAME_ATTEMPT"
        ),
    }
    write_json(gate_path, gate)
    print(json.dumps({"status": "PASS", "tasks": len(tasks), "projected_credits": projected}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
