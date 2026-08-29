#!/usr/bin/env python3
"""Fail-closed continuity contracts between adjacent generated video units.

Camera variety and transition continuity are different concerns.  The camera
sequence gate prevents repetitive movement inside a run of units; this module
binds the terminal state of one unit to the initial state of the next so that
independently generated clips cannot be treated as edit-ready merely because
each clip passes in isolation.
"""

from __future__ import annotations

from typing import Any


CUT_REASONS = {
    "CONTINUOUS_ACTION",
    "SAME_SPACE_COVERAGE",
    "REACTION_CUT",
    "NEW_SPACE_MATCH_CUT",
    "NEW_SPACE_ESTABLISH",
    "SOUND_BRIDGE_NEW_SPACE",
}
SPACE_RELATIONS = {
    "SAME_SUBSPACE",
    "SAME_LOCATION_NEW_SUBSPACE",
    "NEW_LOCATION_SAME_GLOBAL",
    "NEW_GLOBAL_SPACE",
}
NEW_SPACE_REASONS = {
    "NEW_SPACE_MATCH_CUT",
    "NEW_SPACE_ESTABLISH",
    "SOUND_BRIDGE_NEW_SPACE",
}
AUTHORSHIP_VALUES = {"DIRECTOR_AUTHORED", "EDITOR_AUTHORED"}
TRANSITION_DEVICES = {
    "ACTION_MATCH",
    "GAZE_MATCH",
    "PROP_MATCH",
    "OCCLUSION_WIPE",
    "SOUND_BRIDGE",
    "ENVIRONMENT_BRIDGE",
    "MOTIVATED_CUT",
}
STATE_KEYS = {"scene_id", "space", "camera_framing", "camera_side", "blocking"}
SPACE_KEYS = {"global", "location", "subspace"}
MIN_TRANSITION_HANDLE_SECONDS = 0.6
MAX_TRANSITION_HANDLE_SECONDS = 1.5


def _text(value: Any, label: str, minimum: int = 1) -> str:
    text = str(value or "").strip()
    if len(text) < minimum:
        raise ValueError(f"{label} is required and must contain at least {minimum} characters")
    return text


def boundary_id(previous_id: str, current_id: str) -> str:
    return f"BND-{previous_id}-{current_id}"


def _handle_seconds(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    seconds = round(float(value), 3)
    if not MIN_TRANSITION_HANDLE_SECONDS <= seconds <= MAX_TRANSITION_HANDLE_SECONDS:
        raise ValueError(
            f"{label} must be between {MIN_TRANSITION_HANDLE_SECONDS} and "
            f"{MAX_TRANSITION_HANDLE_SECONDS} seconds"
        )
    return seconds


def _state(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    missing = sorted(STATE_KEYS - set(value))
    if missing:
        raise ValueError(f"{label} missing fields: {missing}")
    space = value.get("space")
    if not isinstance(space, dict) or set(space) != SPACE_KEYS:
        raise ValueError(f"{label}.space must contain exactly global/location/subspace")
    normalized = dict(value)
    normalized["scene_id"] = _text(value.get("scene_id"), f"{label}.scene_id")
    normalized["camera_framing"] = _text(value.get("camera_framing"), f"{label}.camera_framing", 4)
    normalized["camera_side"] = _text(value.get("camera_side"), f"{label}.camera_side")
    normalized["blocking"] = _text(value.get("blocking"), f"{label}.blocking", 6)
    normalized["space"] = {
        key: _text(space.get(key), f"{label}.space.{key}") for key in ("global", "location", "subspace")
    }
    return normalized


def _visible_characters(spec: dict[str, Any]) -> list[str]:
    return sorted({
        str(row.get("character") or "").strip()
        for row in spec.get("cast") or []
        if row.get("character") and str(row.get("face_visibility") or "") != "OFFSCREEN_VOICE_ONLY"
    })


def _visible_props(spec: dict[str, Any]) -> list[str]:
    return sorted({str(row.get("prop") or "").strip() for row in spec.get("props") or [] if row.get("prop")})


def _requirements(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    required = {
        "target_visible_characters",
        "target_visible_props",
        "target_space_anchors",
        "empty_establishing_frame_allowed",
    }
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"{label} missing fields: {missing}")
    for key in ("target_visible_characters", "target_visible_props", "target_space_anchors"):
        if not isinstance(value.get(key), list) or any(not str(item).strip() for item in value[key]):
            raise ValueError(f"{label}.{key} must be a list of non-empty strings")
    if not value["target_space_anchors"]:
        raise ValueError(f"{label}.target_space_anchors cannot be empty")
    if not isinstance(value.get("empty_establishing_frame_allowed"), bool):
        raise ValueError(f"{label}.empty_establishing_frame_allowed must be boolean")
    return {
        "target_visible_characters": sorted(set(value["target_visible_characters"])),
        "target_visible_props": sorted(set(value["target_visible_props"])),
        "target_space_anchors": list(dict.fromkeys(value["target_space_anchors"])),
        "empty_establishing_frame_allowed": value["empty_establishing_frame_allowed"],
    }


def validate_transition_contract(
    contract: Any,
    *,
    previous: dict[str, Any],
    current: dict[str, Any],
    require_prompt_specs: bool = False,
) -> dict[str, Any]:
    previous_id = str(previous.get("unit_id") or "UNKNOWN")
    current_id = str(current.get("unit_id") or "UNKNOWN")
    label = f"{previous_id}->{current_id} transition_contract"
    if not isinstance(contract, dict):
        raise ValueError(f"{label} is required")
    if contract.get("from_unit_id") != previous_id or contract.get("to_unit_id") != current_id:
        raise ValueError(f"{label} unit binding mismatch")

    expected_boundary_id = boundary_id(previous_id, current_id)
    if contract.get("boundary_id") != expected_boundary_id:
        raise ValueError(f"{label} boundary_id must be {expected_boundary_id}")

    cut_reason = _text(contract.get("cut_reason"), f"{label}.cut_reason")
    space_relation = _text(contract.get("space_relation"), f"{label}.space_relation")
    authorship = _text(contract.get("authorship"), f"{label}.authorship")
    transition_device = _text(contract.get("transition_device"), f"{label}.transition_device")
    if cut_reason not in CUT_REASONS:
        raise ValueError(f"{label} unsupported cut_reason: {cut_reason}")
    if space_relation not in SPACE_RELATIONS:
        raise ValueError(f"{label} unsupported space_relation: {space_relation}")
    if authorship not in AUTHORSHIP_VALUES:
        raise ValueError(f"{label} must be explicitly director- or editor-authored")
    if transition_device not in TRANSITION_DEVICES:
        raise ValueError(f"{label} unsupported transition_device: {transition_device}")
    if space_relation != "SAME_SUBSPACE" and cut_reason not in NEW_SPACE_REASONS:
        raise ValueError(f"{label} changes space but lacks an explicit new-space transition reason")
    if space_relation == "SAME_SUBSPACE" and cut_reason in NEW_SPACE_REASONS:
        raise ValueError(f"{label} declares a new-space cut inside the same subspace")

    source = _state(contract.get("source_terminal_state"), label=f"{label}.source_terminal_state")
    target = _state(contract.get("target_initial_state"), label=f"{label}.target_initial_state")
    requirements = _requirements(
        contract.get("anchor_semantic_requirements"), label=f"{label}.anchor_semantic_requirements"
    )
    normalized = dict(contract)
    normalized.update({
        "cut_reason": cut_reason,
        "space_relation": space_relation,
        "authorship": authorship,
        "boundary_id": expected_boundary_id,
        "transition_device": transition_device,
        "outgoing_handle_seconds": _handle_seconds(
            contract.get("outgoing_handle_seconds"), f"{label}.outgoing_handle_seconds"
        ),
        "incoming_handle_seconds": _handle_seconds(
            contract.get("incoming_handle_seconds"), f"{label}.incoming_handle_seconds"
        ),
        "plot_motivation": _text(contract.get("plot_motivation"), f"{label}.plot_motivation", 12),
        "visual_bridge": _text(contract.get("visual_bridge"), f"{label}.visual_bridge", 12),
        "action_bridge": _text(contract.get("action_bridge"), f"{label}.action_bridge", 12),
        "sound_bridge": _text(contract.get("sound_bridge"), f"{label}.sound_bridge", 8),
        "axis_strategy": _text(contract.get("axis_strategy"), f"{label}.axis_strategy", 8),
        "continuity_intent": _text(contract.get("continuity_intent"), f"{label}.continuity_intent", 12),
        "source_terminal_state": source,
        "target_initial_state": target,
        "anchor_semantic_requirements": requirements,
    })

    previous_camera = previous.get("camera_plan") or {}
    current_camera = current.get("camera_plan") or {}
    if source["scene_id"] != str(previous.get("scene_id") or ""):
        raise ValueError(f"{label} source scene mismatch")
    if target["scene_id"] != str(current.get("scene_id") or ""):
        raise ValueError(f"{label} target scene mismatch")
    if source["camera_framing"] != previous_camera.get("end_framing"):
        raise ValueError(f"{label} source terminal framing is not bound to predecessor camera end")
    if target["camera_framing"] != current_camera.get("start_framing"):
        raise ValueError(f"{label} target initial framing is not bound to successor camera start")
    if source["camera_side"] != previous_camera.get("camera_side"):
        raise ValueError(f"{label} source camera side mismatch")
    if target["camera_side"] != current_camera.get("camera_side"):
        raise ValueError(f"{label} target camera side mismatch")

    if require_prompt_specs:
        previous_specs = previous.get("ordered_prompt_specs") or []
        current_specs = current.get("ordered_prompt_specs") or []
        if not previous_specs or not current_specs:
            raise ValueError(f"{label} requires ordered prompt specs for semantic binding")
        actual_source_space = previous_specs[-1].get("space") or {}
        actual_target_space = current_specs[0].get("space") or {}
        if source["space"] != {key: actual_source_space.get(key) for key in ("global", "location", "subspace")}:
            raise ValueError(f"{label} source space is not bound to predecessor terminal beat")
        if target["space"] != {key: actual_target_space.get(key) for key in ("global", "location", "subspace")}:
            raise ValueError(f"{label} target space is not bound to successor initial beat")
        actual_characters = _visible_characters(current_specs[0])
        actual_props = _visible_props(current_specs[0])
        if requirements["target_visible_characters"] != actual_characters:
            raise ValueError(f"{label} target character requirements do not match the initial beat")
        if requirements["target_visible_props"] != actual_props:
            raise ValueError(f"{label} target prop requirements do not match the initial beat")
        if actual_characters and requirements["empty_establishing_frame_allowed"]:
            raise ValueError(f"{label} cannot allow an empty establishing frame when the initial beat has visible cast")
    return normalized


def validate_transition_sequence(
    units: list[dict[str, Any]], *, require_prompt_specs: bool = False
) -> None:
    for index, current in enumerate(units):
        if index == 0:
            if current.get("transition_contract"):
                raise ValueError(f"{current.get('unit_id')} first unit must not declare an inbound transition")
            current["incoming_transition_contract"] = None
            continue
        previous = units[index - 1]
        normalized = validate_transition_contract(
            current.get("transition_contract"),
            previous=previous,
            current=current,
            require_prompt_specs=require_prompt_specs,
        )
        current["transition_contract"] = normalized
        current["incoming_transition_contract"] = normalized
        previous["outgoing_transition_contract"] = normalized
    if units:
        units[-1].setdefault("outgoing_transition_contract", None)


def compile_transition_prompt(unit: dict[str, Any]) -> str:
    incoming = unit.get("incoming_transition_contract")
    outgoing = unit.get("outgoing_transition_contract")
    clauses: list[str] = []
    if incoming:
        clauses.append(
            f"入场边界={incoming['boundary_id']}；入场预留={incoming['incoming_handle_seconds']:g}秒；"
            f"转场方式={incoming['transition_device']}；入场承接={incoming['visual_bridge']}；"
            f"动作承接={incoming['action_bridge']}；声桥={incoming['sound_bridge']}；"
            f"轴线={incoming['axis_strategy']}；剧情动机={incoming['plot_motivation']}；"
            "入场残余运动=从上一段末态的呼吸、衣料惯性、环境风声与既定视线继续，不复位、不重演"
        )
    else:
        clauses.append(
            "入场边界=SEQUENCE_START；入场预留=0秒；"
            "本单元为当前生成序列首段，首帧严格服从起始锚点与镜头起始构图"
        )
    if outgoing:
        clauses.append(
            f"出场边界={outgoing['boundary_id']}；片尾转场预留={outgoing['outgoing_handle_seconds']:g}秒；"
            f"转场方式={outgoing['transition_device']}；出场交棒={outgoing['visual_bridge']}；"
            f"片尾剧情动作={outgoing['action_bridge']}；末态必须保持="
            f"{outgoing['source_terminal_state']['blocking']}；声尾={outgoing['sound_bridge']}；"
            f"剧情动机={outgoing['plot_motivation']}；"
            "尾帧延续微动=动作结果落稳后仍保持自然呼吸、衣料惯性与环境微动，禁止冻结、循环或另起新动作"
        )
    else:
        specs = unit.get("ordered_prompt_specs") or []
        terminal = str(
            (((specs[-1] if specs else {}).get("action") or {}).get("completion_state"))
            or ((unit.get("camera_plan") or {}).get("end_framing"))
            or "本段已声明完成态"
        ).strip()
        clauses.append(
            "出场边界=SEQUENCE_END；片尾转场预留=0.8秒；转场方式=MOTIVATED_CUT；"
            f"出场交棒=把视觉注意力保持在“{terminal}”，供正片在剧情结果上切出；"
            f"片尾剧情动作=最后0.8秒完成并保持“{terminal}”，不复位、不另起动作；"
            f"末态必须保持={terminal}；"
            "声尾=保留当前真实接触声与空间混响自然衰减，供片尾切出，禁止默认BGM与突兀静音；"
            "剧情动机=以本段最终因果结果作为本集收束和下一集悬念的落点，不擅自制造下一场；"
            "轴线=保持本段既定轴侧到最终切点"
            "；尾帧延续微动=动作结果落稳后仍保持自然呼吸、衣料惯性与环境微动，禁止冻结、循环或另起新动作"
        )
    return "；".join(clauses) + "。"
