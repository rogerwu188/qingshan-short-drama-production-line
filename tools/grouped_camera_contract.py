#!/usr/bin/env python3
"""Structured cinematography contract for grouped Seedance video units.

The grouped multi-reference route must not collapse camera direction into a
generic "follow the action" sentence.  This module keeps camera authorship in
machine-readable fields, compiles it into concise Chinese prompt language, and
fails closed on repetitive unmotivated movement.
"""

from __future__ import annotations

from typing import Any


SHOT_SCALES = {"EXTREME_CLOSE_UP", "CLOSE_UP", "MEDIUM_CLOSE_UP", "MEDIUM", "MEDIUM_WIDE", "WIDE"}
CAMERA_HEIGHTS = {"LOW", "EYE_LEVEL", "HIGH", "OVERHEAD"}
CAMERA_SIDES = {"AXIS_A", "AXIS_B", "NEUTRAL"}
MOTION_DIRECTIONS = {
    "NONE", "LEFT_TO_RIGHT", "RIGHT_TO_LEFT", "PUSH_IN", "PULL_OUT",
    "RISE", "FALL", "CLOCKWISE", "COUNTERCLOCKWISE",
}
MOTION_FAMILIES = {"LOCKED", "PAN", "TRACK", "DOLLY", "CRANE", "ARC"}
SELECTION_MODES = {"AUTO", "HYBRID", "LOCKED"}
SHUTTER_VISUAL_INTENTS = {
    "NATURAL_MOTION_CLARITY", "CRISP_ACTION_DIRECTION", "DIRECTIONAL_ACTION_BLUR",
}
DEPTH_OF_FIELD_INTENTS = {
    "DEEP_SPATIAL_READABILITY", "BALANCED_SUBJECT_SPACE", "CONTROLLED_SUBJECT_SEPARATION",
}

_MOTION_DIRECTION_COMPATIBILITY = {
    "LOCKED": {"NONE"},
    "PAN": {"LEFT_TO_RIGHT", "RIGHT_TO_LEFT"},
    "TRACK": {"LEFT_TO_RIGHT", "RIGHT_TO_LEFT"},
    "DOLLY": {"PUSH_IN", "PULL_OUT"},
    "CRANE": {"RISE", "FALL"},
    "ARC": {"CLOCKWISE", "COUNTERCLOCKWISE"},
}

_GENERIC_CAMERA_PHRASES = {
    "镜头随主要动作平稳调整景别",
    "跟随主要动作",
    "平稳调整景别",
    "smoothly follow the action",
}

_ZH = {
    "EXTREME_CLOSE_UP": "大特写",
    "CLOSE_UP": "特写",
    "MEDIUM_CLOSE_UP": "中近景",
    "MEDIUM": "中景",
    "MEDIUM_WIDE": "中全景",
    "WIDE": "全景",
    "LOW": "低机位",
    "EYE_LEVEL": "平视",
    "HIGH": "高机位",
    "OVERHEAD": "俯拍",
    "AXIS_A": "轴线A侧",
    "AXIS_B": "轴线B侧",
    "NEUTRAL": "中性轴位",
    "LOCKED": "固定机位",
    "PAN": "摇镜",
    "TRACK": "横向跟拍",
    "DOLLY": "轨道推拉",
    "CRANE": "升降",
    "ARC": "有限弧线移动",
    "NONE": "不移动",
    "LEFT_TO_RIGHT": "由画面左向右",
    "RIGHT_TO_LEFT": "由画面右向左",
    "PUSH_IN": "向主体推进",
    "PULL_OUT": "从主体拉开",
    "RISE": "上升",
    "FALL": "下降",
    "CLOCKWISE": "顺时针",
    "COUNTERCLOCKWISE": "逆时针",
}

_SHUTTER_ZH = {
    "NATURAL_MOTION_CLARITY": "自然实速与清晰动作轮廓",
    "CRISP_ACTION_DIRECTION": "保留清楚的动作方向与接触瞬间，不拖成长残影",
    "DIRECTIONAL_ACTION_BLUR": "仅快速运动肢体保留顺运动方向的轻微动态模糊，主体身份仍清楚",
}
_DOF_ZH = {
    "DEEP_SPATIAL_READABILITY": "较深景深，人物、接触路径与空间关系同时可读",
    "BALANCED_SUBJECT_SPACE": "中等景深，主体清楚且保留必要环境关系",
    "CONTROLLED_SUBJECT_SEPARATION": "受控主体分离，人物清楚但不得虚化关键道具或对手",
}


def _required_text(plan: dict[str, Any], key: str, source_id: str) -> str:
    value = str(plan.get(key) or "").strip()
    if not value:
        raise ValueError(f"{source_id} camera_plan.{key} is required")
    return value


def camera_signature(plan: dict[str, Any]) -> str:
    return f"{plan['motion_family']}:{plan['motion_direction']}"


def validate_camera_plan(plan: Any, *, source_id: str) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ValueError(f"{source_id} camera_plan must be an object")
    shot_scale = _required_text(plan, "shot_scale", source_id)
    camera_height = _required_text(plan, "camera_height", source_id)
    camera_side = _required_text(plan, "camera_side", source_id)
    motion_family = _required_text(plan, "motion_family", source_id)
    motion_direction = _required_text(plan, "motion_direction", source_id)
    lens_intent = _required_text(plan, "lens_intent", source_id)
    axis_relation = _required_text(plan, "axis_relation", source_id)
    start_framing = _required_text(plan, "start_framing", source_id)
    end_framing = _required_text(plan, "end_framing", source_id)
    motivation = _required_text(plan, "motivation", source_id)

    if shot_scale not in SHOT_SCALES:
        raise ValueError(f"{source_id} unsupported camera shot_scale: {shot_scale}")
    if camera_height not in CAMERA_HEIGHTS:
        raise ValueError(f"{source_id} unsupported camera_height: {camera_height}")
    if camera_side not in CAMERA_SIDES:
        raise ValueError(f"{source_id} unsupported camera_side: {camera_side}")
    if motion_family not in MOTION_FAMILIES:
        raise ValueError(f"{source_id} unsupported motion_family: {motion_family}")
    if motion_direction not in MOTION_DIRECTIONS:
        raise ValueError(f"{source_id} unsupported motion_direction: {motion_direction}")
    if motion_direction not in _MOTION_DIRECTION_COMPATIBILITY[motion_family]:
        raise ValueError(
            f"{source_id} motion direction {motion_direction} is invalid for {motion_family}"
        )
    combined = " ".join((lens_intent, axis_relation, start_framing, end_framing, motivation)).lower()
    if any(phrase.lower() in combined for phrase in _GENERIC_CAMERA_PHRASES):
        raise ValueError(f"{source_id} camera_plan contains generic camera language")
    if len(motivation) < 6:
        raise ValueError(f"{source_id} camera movement motivation is not specific enough")
    if motion_family == "LOCKED" and start_framing != end_framing:
        raise ValueError(f"{source_id} locked camera must keep identical start/end framing")
    if motion_family != "LOCKED" and start_framing == end_framing:
        raise ValueError(f"{source_id} moving camera must declare distinct start/end framing")

    selection_mode = str(plan.get("selection_mode") or "HYBRID").upper()
    if selection_mode not in SELECTION_MODES:
        raise ValueError(f"{source_id} unsupported camera selection_mode: {selection_mode}")
    shutter_intent = str(plan.get("shutter_visual_intent") or "").upper()
    if shutter_intent and shutter_intent not in SHUTTER_VISUAL_INTENTS:
        raise ValueError(f"{source_id} unsupported shutter_visual_intent: {shutter_intent}")
    dof_intent = str(plan.get("depth_of_field_intent") or "").upper()
    if dof_intent and dof_intent not in DEPTH_OF_FIELD_INTENTS:
        raise ValueError(f"{source_id} unsupported depth_of_field_intent: {dof_intent}")
    lens_mm = plan.get("lens_mm")
    if lens_mm not in (None, "") and not (18 <= int(lens_mm) <= 135):
        raise ValueError(f"{source_id} camera lens_mm out of range: {lens_mm}")

    normalized = dict(plan)
    normalized.update({
        "shot_scale": shot_scale,
        "lens_intent": lens_intent,
        "camera_height": camera_height,
        "camera_side": camera_side,
        "axis_relation": axis_relation,
        "motion_family": motion_family,
        "motion_direction": motion_direction,
        "start_framing": start_framing,
        "end_framing": end_framing,
        "motivation": motivation,
        "signature": f"{motion_family}:{motion_direction}",
        "selection_mode": selection_mode,
    })
    return normalized


def validate_camera_sequence(units: list[dict[str, Any]]) -> None:
    dynamic: list[tuple[int, str, str, str]] = []
    previous: tuple[str, str, str] | None = None
    for index, unit in enumerate(units):
        unit_id = str(unit.get("unit_id") or f"unit-{index + 1}")
        plan = validate_camera_plan(unit.get("camera_plan"), source_id=unit_id)
        unit["camera_plan"] = plan
        family = plan["motion_family"]
        direction = plan["motion_direction"]
        if family == "LOCKED":
            previous = None
            continue
        if previous and previous[0] == family and previous[1] == direction:
            raise ValueError(
                f"adjacent grouped units repeat camera motion {family}:{direction}: "
                f"{previous[2]} -> {unit_id}"
            )
        if previous and previous[1] == direction:
            raise ValueError(
                f"adjacent grouped units repeat camera direction {direction}: "
                f"{previous[2]} -> {unit_id}"
            )
        previous = (family, direction, unit_id)
        dynamic.append((index, direction, family, unit_id))

    for start in range(max(0, len(units) - 4) + 1):
        window = [row for row in dynamic if start <= row[0] < start + 5]
        counts: dict[str, int] = {}
        for _, direction, _, _ in window:
            counts[direction] = counts.get(direction, 0) + 1
        repeated = [direction for direction, count in counts.items() if count > 2]
        if repeated:
            raise ValueError(
                f"camera direction repeats more than twice in five units at {start + 1}: {repeated}"
            )


def compile_camera_prompt(plan: dict[str, Any], *, source_id: str) -> str:
    plan = validate_camera_plan(plan, source_id=source_id)
    stable = (
        "全段锁定机位，人物动作在构图内发生，禁止漂移、慢推、横移或环绕"
        if plan["motion_family"] == "LOCKED"
        else f"仅执行一次{_ZH[plan['motion_family']]}，{_ZH[plan['motion_direction']]}，禁止反向复位或重复运动"
    )
    optical = []
    if plan.get("lens_mm"):
        optical.append(f"估算{int(plan['lens_mm'])}mm焦段")
    if plan.get("shutter_visual_intent"):
        optical.append(_SHUTTER_ZH[plan["shutter_visual_intent"]])
    if plan.get("depth_of_field_intent"):
        optical.append(_DOF_ZH[plan["depth_of_field_intent"]])
    if plan.get("atmosphere_intent"):
        optical.append(f"仅执行已授权氛围效果{plan['atmosphere_intent']}")
    if plan.get("effect_intent"):
        optical.append(f"仅执行已授权视觉效果{plan['effect_intent']}")
    optical_clause = ("；" + "；".join(optical)) if optical else ""
    return (
        f"景别{_ZH[plan['shot_scale']]}，{plan['lens_intent']}，{_ZH[plan['camera_height']]}，"
        f"机位在{_ZH[plan['camera_side']]}并{plan['axis_relation']}；"
        f"起始{plan['start_framing']}，结束{plan['end_framing']}；{stable}；"
        f"运镜动机：{plan['motivation']}{optical_clause}。"
    )
