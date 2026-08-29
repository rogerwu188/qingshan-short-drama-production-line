#!/usr/bin/env python3
"""Require a pose/result reference when a unit changes body support state."""

from __future__ import annotations

from typing import Any


SCHEMA = "qingshan.pose_transition_anchor_gate.v1"
POSE_GROUPS = {
    "STANDING": ("站立", "站直", "直立", "站姿", "起身", "立定"),
    "SQUATTING": ("下蹲", "蹲下", "蹲姿", "半蹲", "马步", "蹲到"),
    "SITTING": ("坐下", "坐姿", "落座", "倚坐", "坐稳"),
    "KNEELING": ("跪下", "跪姿", "单膝", "双膝"),
    "LYING": ("躺下", "卧倒", "俯卧", "仰卧", "倒地"),
    "BENDING": ("弯腰", "俯身", "躬身", "伏低"),
}
RESULT_ROLE_MARKERS = ("RESULT", "TERMINAL", "POSE", "INTERMEDIATE", "KEYFRAME")


def posture(value: object) -> str | None:
    text = str(value or "")
    for name, tokens in POSE_GROUPS.items():
        if any(token in text for token in tokens):
            return name
    return None


def evaluate(unit: dict[str, Any]) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    for index, spec in enumerate(unit.get("ordered_prompt_specs") or []):
        action = spec.get("action") or {}
        start = posture(action.get("start_state"))
        end = posture(action.get("completion_state"))
        if start and end and start != end:
            changes.append({"spec_index": index, "from_posture": start, "to_posture": end})
    roles = [str(row.get("role") or "").upper() for row in unit.get("reference_images") or []]
    has_pose_result_anchor = any(any(marker in role for marker in RESULT_ROLE_MARKERS) for role in roles[1:])
    failures: list[str] = []
    if changes and not has_pose_result_anchor:
        failures.append(
            f"{unit.get('unit_id')}:POSE_STATE_CHANGE_REQUIRES_INTERMEDIATE_OR_RESULT_ANCHOR"
        )
    return {
        "schema": SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "unit_id": str(unit.get("unit_id") or "UNKNOWN"),
        "pose_changes": changes,
        "reference_roles": roles,
        "pose_result_anchor_present": has_pose_result_anchor,
        "failures": failures,
    }
