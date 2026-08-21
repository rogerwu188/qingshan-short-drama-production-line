#!/usr/bin/env python3
"""Promote a no-submit image precheck manifest after an exact reroll budget gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def resolve(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def portable(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def authorize(
    source_path: Path,
    output_path: Path,
    gate_path: Path,
    *,
    authorization_ref: str,
    total_paid_tasks: int,
    observed_paid_rerolls: int,
    fraction: float,
) -> tuple[dict, dict]:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    tasks = deepcopy(source.get("tasks") or [])
    if not tasks:
        raise ValueError("source manifest has no tasks")
    if any(task.get("status") != "READY_FOR_PRECHECK_NO_PROVIDER_POST" for task in tasks):
        raise ValueError("source tasks are not all precheck-only")
    limit = math.floor(total_paid_tasks * fraction)
    projected = observed_paid_rerolls + len(tasks)
    if projected > limit:
        raise ValueError(f"paid reroll budget exceeded: projected={projected} limit={limit}")

    for task in tasks:
        task["status"] = "READY_TO_SUBMIT"
        task["provider_post_allowed"] = True
        task["maximum_new_submissions"] = 1
    manifest = deepcopy(source)
    manifest.update({
        "schema": "qingshan.authorized_image_submission_manifest.v1",
        "status": "READY_TO_SUBMIT",
        "authorization_ref": authorization_ref,
        "source_precheck_manifest": portable(source_path),
        "source_precheck_manifest_sha256": sha256(source_path),
        "provider_post_allowed": True,
        "maximum_new_submissions": len(tasks),
        "tasks": tasks,
    })
    gate_ref = portable(gate_path)
    reports = [path for path in manifest.get("machine_gate_reports") or [] if path != gate_ref]
    manifest["machine_gate_reports"] = [*reports, gate_ref]
    write_json(output_path, manifest)

    gate = {
        "schema": "qingshan.registered_reroll_cost_gate.v1",
        "gate_id": "GIGGLE-REROLL-COST-GUARD",
        "status": "PASS",
        "authorization_ref": authorization_ref,
        "reviewed_manifest": portable(output_path),
        "reviewed_manifest_sha256": sha256(output_path),
        "total_paid_tasks": total_paid_tasks,
        "episode_paid_reroll_fraction": fraction,
        "maximum_paid_rerolls": limit,
        "observed_paid_rerolls": observed_paid_rerolls,
        "planned_new_paid_rerolls": len(tasks),
        "projected_paid_rerolls": projected,
        "provider_posts": 0,
        "credits": 0,
    }
    write_json(gate_path, gate)
    return manifest, gate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--gate-out", required=True)
    parser.add_argument("--authorization-ref", required=True)
    parser.add_argument("--total-paid-tasks", required=True, type=int)
    parser.add_argument("--observed-paid-rerolls", required=True, type=int)
    parser.add_argument("--fraction", type=float, default=0.15)
    args = parser.parse_args()
    manifest, gate = authorize(
        resolve(args.source),
        resolve(args.output),
        resolve(args.gate_out),
        authorization_ref=args.authorization_ref,
        total_paid_tasks=args.total_paid_tasks,
        observed_paid_rerolls=args.observed_paid_rerolls,
        fraction=args.fraction,
    )
    print(json.dumps({
        "status": manifest["status"],
        "task_count": len(manifest["tasks"]),
        "projected_paid_rerolls": gate["projected_paid_rerolls"],
        "maximum_paid_rerolls": gate["maximum_paid_rerolls"],
        "provider_posts": 0,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
