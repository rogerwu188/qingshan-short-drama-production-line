#!/usr/bin/env python3
"""Validate the boundary between editorial shots and video generation units."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from video_unit_anchor_count_gate import evaluate as evaluate_anchor_counts
except ModuleNotFoundError:
    from tools.video_unit_anchor_count_gate import evaluate as evaluate_anchor_counts


ROOT = Path(__file__).resolve().parents[1]


def resolve(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def load(path: str | Path) -> dict[str, Any]:
    return json.loads(resolve(path).read_text(encoding="utf-8"))


def sha256(path: str | Path) -> str:
    return hashlib.sha256(resolve(path).read_bytes()).hexdigest()


def duplicates(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def validate_plan(
    production: dict[str, Any],
    plan: dict[str, Any],
    image_manifests: list[dict[str, Any]],
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []

    def check(name: str, actual: Any, expected: Any) -> None:
        if actual != expected:
            failures.append({"check": name, "actual": actual, "expected": expected})

    episode = production.get("episode")
    script_sha = production.get("source", {}).get("script_sha256")
    shots = production.get("shots") or []
    shot_by_id = {row.get("shot_id"): row for row in shots}
    expected_shot_ids = [row.get("shot_id") for row in shots]
    units = plan.get("units") or []
    duration_policy = plan.get("duration_policy_seconds") or {}
    minimum_duration = int(duration_policy.get("minimum", 8))
    maximum_duration = int(duration_policy.get("maximum", 15))
    preferred_duration = plan.get("preferred_duration_seconds") or {}
    preferred_minimum = int(preferred_duration.get("minimum", minimum_duration))
    preferred_maximum = int(preferred_duration.get("maximum", maximum_duration))

    check("episode", plan.get("episode"), episode)
    check("source_script_sha256", plan.get("source_script_sha256"), script_sha)
    check("editorial_shot_count", plan.get("editorial_shot_count"), len(shots))
    check("video_unit_count", plan.get("video_unit_count"), len(units))
    check("runtime_seconds", plan.get("runtime_seconds"), production.get("runtime_seconds"))

    unit_ids = [row.get("unit_id") for row in units]
    if None in unit_ids or duplicates(unit_ids):
        failures.append({"check": "unique_unit_ids", "duplicates": duplicates(unit_ids), "has_null": None in unit_ids})

    assigned_shots: list[str] = []
    assigned_states: list[str] = []
    duration_total = 0
    unit_summary: list[dict[str, Any]] = []
    duration_exceptions: list[dict[str, Any]] = []
    for unit in units:
        unit_id = unit.get("unit_id")
        duration = unit.get("duration_seconds")
        editorial_shot_ids = unit.get("editorial_shot_ids") or []
        state_task_keys = unit.get("state_task_keys") or []
        action_unit = bool(unit.get("action_unit"))
        planned_state_count = unit.get("planned_reference_image_count")

        script_duration = sum(
            int(shot_by_id[shot_id].get("duration_seconds", 0))
            for shot_id in editorial_shot_ids
            if shot_id in shot_by_id
        )
        if isinstance(duration, int):
            duration_total += duration
        if not isinstance(duration, int) or not minimum_duration <= duration <= maximum_duration:
            failures.append({
                "check": "unit_duration_range",
                "unit_id": unit_id,
                "actual": duration,
                "expected": [minimum_duration, maximum_duration],
            })
        if duration != script_duration:
            failures.append({
                "check": "unit_duration_exact_script_sum",
                "unit_id": unit_id,
                "actual": duration,
                "expected": script_duration,
                "editorial_shot_ids": editorial_shot_ids,
            })
        if isinstance(duration, int) and not preferred_minimum <= duration <= preferred_maximum:
            duration_exceptions.append({
                "unit_id": unit_id,
                "duration_seconds": duration,
                "reason": unit.get("duration_exception_reason"),
            })
            if not unit.get("duration_exception_reason"):
                failures.append({
                    "check": "preferred_duration_exception_reason",
                    "unit_id": unit_id,
                    "actual": duration,
                    "preferred": [preferred_minimum, preferred_maximum],
                })
        if not editorial_shot_ids:
            failures.append({"check": "unit_has_editorial_shots", "unit_id": unit_id})
        if not isinstance(planned_state_count, int) or isinstance(planned_state_count, bool) or planned_state_count < 1:
            failures.append({
                "check": "unit_dynamic_state_count_missing",
                "unit_id": unit_id,
                "actual": planned_state_count,
                "expected": "integer >= 1 derived per unit from action design and model capability",
            })
        elif len(state_task_keys) != planned_state_count:
            failures.append({
                "check": "unit_dynamic_state_count_mismatch",
                "unit_id": unit_id,
                "actual": len(state_task_keys),
                "expected": planned_state_count,
            })
        unit_scene_ids = {shot_by_id.get(shot_id, {}).get("scene_id") for shot_id in editorial_shot_ids}
        if unit_scene_ids != {unit.get("scene_id")}:
            failures.append({
                "check": "unit_scene_consistency",
                "unit_id": unit_id,
                "actual": sorted(str(value) for value in unit_scene_ids),
                "expected": unit.get("scene_id"),
            })
        assigned_shots.extend(editorial_shot_ids)
        assigned_states.extend(state_task_keys)
        unit_summary.append({
            "unit_id": unit_id,
            "duration_seconds": duration,
            "script_duration_seconds": script_duration,
            "editorial_shot_count": len(editorial_shot_ids),
            "state_count": len(state_task_keys),
            "planned_reference_image_count": planned_state_count,
            "action_unit": action_unit,
        })

    anchor_plan = {
        "units": [
            {
                **unit,
                "reference_image_task_keys": unit.get("state_task_keys") or [],
            }
            for unit in units
        ],
        "planned_reference_image_count": sum(
            int(unit.get("planned_reference_image_count") or 0) for unit in units
        ),
        "uniform_count_independence_audit": plan.get("uniform_count_independence_audit"),
    }
    anchor_gate = evaluate_anchor_counts(anchor_plan)
    for row in anchor_gate.get("failures") or []:
        failures.append({"check": "dynamic_anchor_count_gate", **row})

    check("duration_sum", duration_total, production.get("runtime_seconds"))
    missing_shots = sorted(set(expected_shot_ids) - set(assigned_shots))
    unknown_shots = sorted(set(assigned_shots) - set(expected_shot_ids))
    duplicate_shots = duplicates(assigned_shots)
    if missing_shots or unknown_shots or duplicate_shots:
        failures.append({
            "check": "editorial_shot_exact_coverage",
            "missing": missing_shots,
            "unknown": unknown_shots,
            "duplicates": duplicate_shots,
        })
    if assigned_shots != expected_shot_ids:
        failures.append({
            "check": "editorial_shot_order_and_contiguity",
            "actual": assigned_shots,
            "expected": expected_shot_ids,
        })

    expected_states: list[str] = []
    for image_manifest in image_manifests:
        check("image_manifest_episode", image_manifest.get("episode"), episode)
        check("image_manifest_script_sha256", image_manifest.get("source_script_sha256"), script_sha)
        expected_states.extend(task.get("task_key") for task in image_manifest.get("tasks") or [])
    missing_states = sorted(set(expected_states) - set(assigned_states))
    unknown_states = sorted(set(assigned_states) - set(expected_states))
    duplicate_states = duplicates(assigned_states)
    if missing_states or unknown_states or duplicate_states:
        failures.append({
            "check": "state_task_exact_coverage",
            "missing": missing_states,
            "unknown": unknown_states,
            "duplicates": duplicate_states,
        })
    check("state_pool_count", plan.get("state_pool_count"), len(expected_states))

    return {
        "schema": "qingshan.video_unit_state_plan_gate.v1",
        "episode": episode,
        "status": "PASS" if not failures else "FAIL",
        "distinction": {
            "editorial_shots": len(shots),
            "video_generation_units": len(units),
            "reference_states": len(expected_states),
        },
        "runtime": {
            "declared_seconds": production.get("runtime_seconds"),
            "planned_seconds": duration_total,
            "unit_duration_range_seconds": [minimum_duration, maximum_duration],
            "preferred_unit_duration_range_seconds": [preferred_minimum, preferred_maximum],
            "documented_preferred_range_exceptions": duration_exceptions,
        },
        "coverage": {
            "editorial_shots_assigned": len(assigned_shots),
            "reference_states_assigned": len(assigned_states),
        },
        "dynamic_anchor_count_gate": anchor_gate,
        "units": unit_summary,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-manifest", required=True)
    parser.add_argument("--video-unit-plan", required=True)
    parser.add_argument("--image-manifest", action="append", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    report = validate_plan(
        load(args.production_manifest),
        load(args.video_unit_plan),
        [load(path) for path in args.image_manifest],
    )
    report["evidence"] = {
        "production_manifest": args.production_manifest,
        "production_manifest_sha256": sha256(args.production_manifest),
        "video_unit_plan": args.video_unit_plan,
        "video_unit_plan_sha256": sha256(args.video_unit_plan),
        "image_manifests": [
            {"path": path, "sha256": sha256(path)} for path in args.image_manifest
        ],
    }
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        **report["distinction"],
        "runtime_seconds": report["runtime"]["planned_seconds"],
        "failure_count": len(report["failures"]),
        "out": str(out),
    }, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
