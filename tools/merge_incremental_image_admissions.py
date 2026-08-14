#!/usr/bin/env python3
"""Merge newly harvested still candidates into an existing admission ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_ID_RE = re.compile(r"^(E\d+-CW-S\d+-SH\d+-C\d+)")


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state_id(task_key: str) -> str:
    match = STATE_ID_RE.match(task_key)
    if not match:
        raise ValueError(f"Cannot derive state id from task key: {task_key}")
    return match.group(1)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--full-state-plan", required=True)
    parser.add_argument("--harvest", action="append", required=True)
    parser.add_argument("--adjudication", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    base_path = resolve(args.base)
    plan_path = resolve(args.full_state_plan)
    adjudication_path = resolve(args.adjudication)
    out_path = resolve(args.out)
    base = load(base_path)
    plan = load(plan_path)
    adjudication = load(adjudication_path)
    planned = {str(row["shot_id"]) for row in plan.get("tasks", [])}
    overrides = adjudication.get("task_overrides") or {}
    default_decision = adjudication.get("default_completed_candidate_decision")
    default_confidence = float(adjudication.get("default_confidence", 0.0))
    capability_failure = adjudication.get("capability_failure") or {}

    candidates: dict[str, list[dict[str, Any]]] = {}
    source_paths: list[str] = []
    for priority, value in enumerate(args.harvest):
        source_path = resolve(value)
        source_paths.append(str(source_path))
        source = load(source_path)
        for row in source.get("results", []):
            if row.get("remote_status") != "completed" or not row.get("output_path"):
                continue
            candidate_state = state_id(str(row["task_key"]))
            if candidate_state not in planned:
                continue
            path = resolve(row["output_path"])
            if not path.is_file():
                raise FileNotFoundError(path)
            actual_sha = sha256(path)
            expected_sha = row.get("sha256")
            if expected_sha and actual_sha != expected_sha:
                raise ValueError(f"SHA mismatch for {row['task_key']}: {expected_sha} != {actual_sha}")
            override = overrides.get(row["task_key"], {})
            decision = override.get("decision", default_decision)
            if decision not in {"PASS", "CONDITIONAL_MACHINE_ADMISSION", "REJECT"}:
                raise ValueError(f"Missing or invalid decision for {row['task_key']}: {decision}")
            candidates.setdefault(candidate_state, []).append({
                "state_id": candidate_state,
                "task_key": row["task_key"],
                "path": str(path),
                "sha256": actual_sha,
                "task_id": row.get("task_id"),
                "source_harvest": str(source_path),
                "source_priority": priority,
                "decision": decision,
                "confidence": float(override.get("confidence", default_confidence)),
                "selection_reason": override.get("selection_reason") or adjudication.get("default_selection_reason"),
                "failure_items": override.get("failure_items", []),
                "replacement_condition": override.get("replacement_condition") or adjudication.get("default_replacement_condition"),
            })

    selected = {str(row.get("state_id") or row.get("shot_id")): dict(row) for row in base.get("selections", [])}
    rejected: list[dict[str, Any]] = list(base.get("rejected_candidates", []))
    merged_states: list[str] = []
    for candidate_state, rows in candidates.items():
        accepted = [row for row in rows if row["decision"] != "REJECT"]
        if not accepted:
            continue
        winner = max(accepted, key=lambda row: row["source_priority"])
        selected[candidate_state] = {
            "shot_id": candidate_state,
            "state_id": candidate_state,
            "path": winner["path"],
            "sha256": winner["sha256"],
            "task_id": winner["task_id"],
            "raw_status": capability_failure.get("status", "CAPABILITY_FAIL"),
            "blocking_checks": capability_failure.get("failure_items", []),
            "source_review": str(adjudication_path),
            "admission": winner["decision"],
            "selection_reason": winner["selection_reason"],
            "confidence": winner["confidence"],
            "rollback_point": winner["sha256"],
            "replacement_condition": winner["replacement_condition"],
            "candidate_count": len(rows),
            "source_harvest": winner["source_harvest"],
        }
        merged_states.append(candidate_state)
        for row in rows:
            if row is winner:
                continue
            rejected.append({
                "state_id": candidate_state,
                "task_key": row["task_key"],
                "path": row["path"],
                "sha256": row["sha256"],
                "task_id": row["task_id"],
                "decision": row["decision"],
                "failure_items": row["failure_items"],
                "reason": row["selection_reason"] or "Superseded by a later admitted candidate for the same state.",
                "source_harvest": row["source_harvest"],
            })

    missing = sorted(planned - set(selected))
    selections = [selected[key] for key in sorted(selected)]
    payload = {
        "schema": "qingshan.incremental_image_admission.v1",
        "episode": base.get("episode") or plan.get("episode"),
        "status": "COMPLETE" if not missing else "PARTIAL",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "base_admission": str(base_path),
        "full_state_plan": str(plan_path),
        "source_harvests": source_paths,
        "adjudication": str(adjudication_path),
        "planned_state_count": len(planned),
        "selection_count": len(selections),
        "merged_state_count": len(merged_states),
        "missing_state_ids": missing,
        "raw_failures_preserved": True,
        "selections": selections,
        "rejected_candidates": rejected,
    }
    atomic_json(out_path, payload)
    print(json.dumps({
        "status": payload["status"],
        "selection_count": len(selections),
        "merged_state_count": len(merged_states),
        "missing_state_ids": missing,
        "out": str(out_path),
    }, ensure_ascii=False))
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
