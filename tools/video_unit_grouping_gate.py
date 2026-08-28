#!/usr/bin/env python3
"""Registered gate preventing editorial shots from becoming one paid video each."""

from __future__ import annotations

from typing import Any


def evaluate(plan: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    units = plan.get("units") or []
    editorial_count = plan.get("editorial_shot_count")
    unit_count = plan.get("video_unit_count")
    derivation = plan.get("derivation") or {}
    preferred = plan.get("preferred_duration_seconds") or {}
    preferred_minimum = float(preferred.get("minimum", 5))
    preferred_maximum = float(preferred.get("maximum", 8))

    accepted_schemas = {
        "qingshan.video_unit_grouping_plan.v1",
        "qingshan.video_unit_grouping_plan.v2_transition_contract",
    }
    if plan.get("schema") not in accepted_schemas:
        failures.append("grouping_plan_schema_invalid")
    if not isinstance(editorial_count, int) or not isinstance(unit_count, int):
        failures.append("grouping_counts_missing")
    elif unit_count != len(units):
        failures.append("video_unit_count_mismatch")
    elif editorial_count >= 12 and unit_count >= editorial_count:
        failures.append("editorial_shot_to_video_unit_one_to_one_forbidden")
    if derivation.get("unit_count_selected_in_advance") is not False:
        failures.append("unit_count_must_emerge_from_semantic_groups")
    if derivation.get("formula_division_used") is not False:
        failures.append("runtime_division_formula_forbidden")

    seen: list[str] = []
    short = 0
    for unit in units:
        shot_ids = unit.get("editorial_shot_ids") or []
        if not shot_ids:
            failures.append(f"editorial_shots_missing:{unit.get('unit_id')}")
        seen.extend(str(value) for value in shot_ids)
        duration = float(unit.get("duration_seconds") or 0)
        if duration < preferred_minimum:
            short += 1
            if not unit.get("duration_exception_reason"):
                failures.append(f"short_unit_exception_missing:{unit.get('unit_id')}")
        if duration > preferred_maximum and not unit.get("duration_exception_reason"):
            failures.append(f"long_unit_exception_missing:{unit.get('unit_id')}")
    if editorial_count != len(seen) or len(seen) != len(set(seen)):
        failures.append("editorial_shot_coverage_not_exact")
    if len(units) >= 8 and short / len(units) > 0.25:
        failures.append("excessive_short_video_units")

    return {
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
        "editorial_shot_count": editorial_count,
        "video_unit_count": unit_count,
        "average_video_unit_duration_seconds": plan.get("average_video_unit_duration_seconds"),
    }


def validate_task_bindings(plan: dict[str, Any], tasks: list[dict[str, Any]]) -> list[str]:
    by_id = {str(unit.get("unit_id")): unit for unit in plan.get("units") or []}
    failures: list[str] = []
    for task in tasks:
        unit_id = str(task.get("unit_id") or task.get("source_id") or "")
        unit = by_id.get(unit_id)
        if unit is None:
            failures.append(f"video_unit_missing_from_grouping_plan:{unit_id or 'UNKNOWN'}")
            continue
        declared_shots = task.get("editorial_shot_ids")
        if declared_shots is not None and declared_shots != unit.get("editorial_shot_ids"):
            failures.append(f"editorial_shot_binding_mismatch:{unit_id}")
        if task.get("duration_seconds") is not None and abs(
            float(task["duration_seconds"]) - float(unit["duration_seconds"])
        ) > 0.001:
            failures.append(f"video_unit_duration_binding_mismatch:{unit_id}")
    return failures
