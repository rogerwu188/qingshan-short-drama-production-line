#!/usr/bin/env python3
"""Reject action prompts whose entry or planned exit geometry is infeasible."""

from __future__ import annotations

from typing import Any


def _ratio(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0.0 <= number <= 1.0 else None


def evaluate_batch(tasks: list[dict[str, Any]], prompts: dict[str, str]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for task in tasks:
        if not task.get("requires_spatial_feasibility_gate"):
            continue
        key = str(task.get("task_key") or task.get("source_id") or "unknown")
        contract = task.get("action_spatial_feasibility_contract") or {}
        prompt = prompts.get(key, "")
        task_failures: list[str] = []
        if contract.get("entry_geometry_derived_from_start_frame") is not True:
            task_failures.append("START_FRAME_GEOMETRY_NOT_VERIFIED")
        if contract.get("entry_pose_compatible") is not True:
            task_failures.append("ENTRY_POSE_INCOMPATIBLE_WITH_ACTION")
        if contract.get("exit_geometry_planned") is not True:
            task_failures.append("EXIT_FRAME_GEOMETRY_NOT_PLANNED")
        if contract.get("exit_pose_compatible_with_next_shot") is not True:
            task_failures.append("EXIT_POSE_INCOMPATIBLE_WITH_NEXT_SHOT")
        if contract.get("exit_preserves_protected_props") is not True:
            task_failures.append("EXIT_FRAME_DAMAGES_OR_OCCLUDES_PROTECTED_PROP")

        corridor = contract.get("collision_corridor") or {}
        x_min, x_max = _ratio(corridor.get("x_min")), _ratio(corridor.get("x_max"))
        y_min, y_max = _ratio(corridor.get("y_min")), _ratio(corridor.get("y_max"))
        if None in {x_min, x_max, y_min, y_max} or x_min >= x_max or y_min >= y_max:
            task_failures.append("COLLISION_CORRIDOR_INVALID")
            corridor_width = corridor_height = 0.0
        else:
            corridor_width = x_max - x_min
            corridor_height = y_max - y_min
        if corridor.get("clear_of_protected_props") is not True:
            task_failures.append("COLLISION_CORRIDOR_INTERSECTS_PROTECTED_PROP")
        if corridor.get("limb_path_clear") is not True:
            task_failures.append("CONTACT_LIMB_PATH_NOT_CLEAR")

        effect = contract.get("effect_geometry") or {}
        effect_width = _ratio(effect.get("max_width_ratio"))
        effect_height = _ratio(effect.get("max_height_ratio"))
        if effect_width is None or effect_height is None:
            task_failures.append("EFFECT_SIZE_RATIO_INVALID")
        else:
            if effect_width > corridor_width:
                task_failures.append("EFFECT_TOO_WIDE_FOR_COLLISION_CORRIDOR")
            if effect_height > corridor_height:
                task_failures.append("EFFECT_TOO_TALL_FOR_COLLISION_CORRIDOR")
        if not str(effect.get("plane_orientation") or "").strip():
            task_failures.append("EFFECT_PLANE_ORIENTATION_MISSING")
        if not str(effect.get("depth_order") or "").strip():
            task_failures.append("EFFECT_DEPTH_ORDER_MISSING")

        occlusion = _ratio(contract.get("maximum_subject_occlusion_ratio"))
        if occlusion is None or occlusion > 0.35:
            task_failures.append("SUBJECT_OCCLUSION_BUDGET_EXCEEDED")
        if contract.get("first_contact_before_effect_feedback") is not True:
            task_failures.append("CONTACT_FEEDBACK_ORDER_NOT_LOCKED")
        required_clauses = contract.get("required_prompt_clauses") or []
        missing_clauses = [clause for clause in required_clauses if clause not in prompt]
        if missing_clauses:
            task_failures.append("SPATIAL_CONTRACT_NOT_COMPILED_INTO_PROMPT")

        rows.append({"task_key": key, "status": "PASS" if not task_failures else "FAIL"})
        failures.extend({"task_key": key, "code": code} for code in task_failures)
    return {
        "schema": "qingshan.action_spatial_feasibility_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "fail_closed": True,
        "rows": rows,
        "failures": failures,
        "policy": "Before submission, the exact entry frame and planned exit frame must support the contact corridor, effect footprint, protected props and next-shot handoff.",
    }
