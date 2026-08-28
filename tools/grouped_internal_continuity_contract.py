#!/usr/bin/env python3
"""Fail-closed continuity contracts inside one grouped video unit.

The cross-unit transition contract cannot protect boundaries between editorial
beats that have been packed into a single provider request.  Without an
internal contract, a multi-reference model may treat a new character occupying
the old character's screen position as an identity transformation, or silently
change location, prop ownership, ambience, or dialogue speaker.  This module
requires every internal editorial boundary to say exactly how the handoff is
performed and compiles that information into the model-visible prompt.
"""

from __future__ import annotations

from typing import Any


TRANSITION_MODES = {
    "CONTINUOUS_ACTION",
    "CAMERA_REFRAME",
    "PAN_REVEAL",
    "OCCLUSION_REVEAL",
    "MOTIVATED_CUT",
    "REACTION_CUT",
    "MATCH_CUT",
}
CUT_MODES = {"MOTIVATED_CUT", "REACTION_CUT", "MATCH_CUT"}
AUTHORSHIP_VALUES = {"DIRECTOR_AUTHORED", "EDITOR_AUTHORED"}


def _text(value: Any, label: str, minimum: int = 1) -> str:
    result = str(value or "").strip()
    if len(result) < minimum:
        raise ValueError(f"{label} is required and must contain at least {minimum} characters")
    return result


def _visible_characters(spec: dict[str, Any]) -> list[str]:
    return sorted({
        str(row.get("character") or "").strip()
        for row in spec.get("cast") or []
        if row.get("character") and str(row.get("face_visibility") or "") != "OFFSCREEN_VOICE_ONLY"
    })


def _all_characters(spec: dict[str, Any]) -> list[str]:
    return sorted({str(row.get("character") or "").strip() for row in spec.get("cast") or [] if row.get("character")})


def _props(spec: dict[str, Any]) -> list[str]:
    return sorted({str(row.get("prop") or "").strip() for row in spec.get("props") or [] if row.get("prop")})


def _space(spec: dict[str, Any]) -> dict[str, str]:
    source = spec.get("space") or {}
    return {key: str(source.get(key) or "").strip() for key in ("global", "location", "subspace")}


def _sound(spec: dict[str, Any]) -> dict[str, str]:
    source = spec.get("sound_design") or {}
    return {key: str(source.get(key) or "").strip() for key in ("ambience", "foley", "action_sound")}


def _speaker(spec: dict[str, Any]) -> str | None:
    raw = str(spec.get("dialogue") or "").strip()
    if not raw:
        return None
    speaker, separator, spoken = raw.partition("：")
    if not separator or not speaker.strip() or not spoken.strip():
        raise ValueError(f"dialogue must use speaker：text format: {raw}")
    if speaker.strip() not in _all_characters(spec):
        raise ValueError(f"dialogue speaker is absent from the beat cast: {speaker.strip()}")
    return speaker.strip()


def internal_boundary_id(unit_id: str, from_shot_id: str, to_shot_id: str) -> str:
    return f"INT-{unit_id}-{from_shot_id}-{to_shot_id}"


def _exact_list(value: Any, expected: list[str], label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    normalized = sorted({str(item).strip() for item in value if str(item).strip()})
    if normalized != expected:
        raise ValueError(f"{label} must exactly match authored beat state: {normalized} != {expected}")
    return normalized


def validate_internal_transition_contract(
    contract: Any,
    *,
    unit_id: str,
    from_shot_id: str,
    to_shot_id: str,
    previous_spec: dict[str, Any],
    current_spec: dict[str, Any],
) -> dict[str, Any]:
    label = f"{unit_id}:{from_shot_id}->{to_shot_id} internal_transition_contract"
    if not isinstance(contract, dict):
        raise ValueError(f"{label} is required")
    expected_id = internal_boundary_id(unit_id, from_shot_id, to_shot_id)
    if contract.get("boundary_id") != expected_id:
        raise ValueError(f"{label}.boundary_id must be {expected_id}")
    if contract.get("from_shot_id") != from_shot_id or contract.get("to_shot_id") != to_shot_id:
        raise ValueError(f"{label} shot binding mismatch")
    mode = _text(contract.get("transition_mode"), f"{label}.transition_mode")
    if mode not in TRANSITION_MODES:
        raise ValueError(f"{label} unsupported transition_mode: {mode}")
    authorship = _text(contract.get("authorship"), f"{label}.authorship")
    if authorship not in AUTHORSHIP_VALUES:
        raise ValueError(f"{label}.authorship must be director- or editor-authored")

    cast = contract.get("cast_bridge")
    if not isinstance(cast, dict):
        raise ValueError(f"{label}.cast_bridge is required")
    previous_cast = _visible_characters(previous_spec)
    current_cast = _visible_characters(current_spec)
    _exact_list(cast.get("from_visible_characters"), previous_cast, f"{label}.cast_bridge.from_visible_characters")
    _exact_list(cast.get("to_visible_characters"), current_cast, f"{label}.cast_bridge.to_visible_characters")
    identity = _text(cast.get("identity_preservation"), f"{label}.cast_bridge.identity_preservation", 8)
    handoff = _text(cast.get("entry_exit_or_reveal"), f"{label}.cast_bridge.entry_exit_or_reveal", 8)
    if previous_cast != current_cast and handoff in {"保持不变", "无需交接"}:
        raise ValueError(f"{label} changes visible cast but has no entry/exit/reveal/cut handoff")

    previous_space, current_space = _space(previous_spec), _space(current_spec)
    scene = contract.get("scene_bridge")
    if not isinstance(scene, dict):
        raise ValueError(f"{label}.scene_bridge is required")
    if scene.get("from_space") != previous_space or scene.get("to_space") != current_space:
        raise ValueError(f"{label}.scene_bridge is not exactly bound to both beat spaces")
    scene_continuity = _text(scene.get("continuity"), f"{label}.scene_bridge.continuity", 8)
    if previous_space != current_space and mode == "CONTINUOUS_ACTION":
        raise ValueError(f"{label} changes map space but declares CONTINUOUS_ACTION")

    props = contract.get("prop_bridge")
    if not isinstance(props, dict):
        raise ValueError(f"{label}.prop_bridge is required")
    previous_props, current_props = _props(previous_spec), _props(current_spec)
    _exact_list(props.get("from_props"), previous_props, f"{label}.prop_bridge.from_props")
    _exact_list(props.get("to_props"), current_props, f"{label}.prop_bridge.to_props")
    prop_handoff = _text(props.get("ownership_or_handoff"), f"{label}.prop_bridge.ownership_or_handoff", 6)

    previous_sound, current_sound = _sound(previous_spec), _sound(current_spec)
    sound = contract.get("sound_bridge")
    if not isinstance(sound, dict):
        raise ValueError(f"{label}.sound_bridge is required")
    if sound.get("from_sound") != previous_sound or sound.get("to_sound") != current_sound:
        raise ValueError(f"{label}.sound_bridge is not exactly bound to both beat sound designs")
    sound_handoff = _text(sound.get("bridge"), f"{label}.sound_bridge.bridge", 8)

    camera = contract.get("camera_bridge")
    if not isinstance(camera, dict):
        raise ValueError(f"{label}.camera_bridge is required")
    axis = _text(camera.get("axis_strategy"), f"{label}.camera_bridge.axis_strategy", 8)
    execution = _text(camera.get("transition_execution"), f"{label}.camera_bridge.transition_execution", 8)

    previous_terminal = str((previous_spec.get("action") or {}).get("completion_state") or "").strip()
    current_start = str((current_spec.get("action") or {}).get("start_state") or "").strip()
    action_bridge = _text(contract.get("action_bridge"), f"{label}.action_bridge", 12)
    if previous_terminal not in action_bridge or current_start not in action_bridge:
        raise ValueError(f"{label}.action_bridge must name the exact previous terminal and current initial states")

    reference = contract.get("reference_bridge")
    if not isinstance(reference, dict):
        raise ValueError(f"{label}.reference_bridge is required")
    if reference.get("different_character_same_slot_forbidden") is not True:
        raise ValueError(f"{label}.reference_bridge must forbid different-character same-slot replacement")
    reference_mapping = _text(reference.get("entity_mapping"), f"{label}.reference_bridge.entity_mapping", 8)
    same_slot_reuse_allowed = reference.get("same_slot_reuse_allowed")
    if not isinstance(same_slot_reuse_allowed, bool):
        raise ValueError(f"{label}.reference_bridge.same_slot_reuse_allowed must be boolean")
    if same_slot_reuse_allowed and mode not in CUT_MODES:
        raise ValueError(f"{label} may reuse a screen slot only across an explicit cut")

    normalized = dict(contract)
    normalized.update({
        "boundary_id": expected_id,
        "from_shot_id": from_shot_id,
        "to_shot_id": to_shot_id,
        "transition_mode": mode,
        "authorship": authorship,
        "cast_bridge": {
            "from_visible_characters": previous_cast,
            "to_visible_characters": current_cast,
            "identity_preservation": identity,
            "entry_exit_or_reveal": handoff,
        },
        "scene_bridge": {"from_space": previous_space, "to_space": current_space, "continuity": scene_continuity},
        "prop_bridge": {"from_props": previous_props, "to_props": current_props, "ownership_or_handoff": prop_handoff},
        "sound_bridge": {"from_sound": previous_sound, "to_sound": current_sound, "bridge": sound_handoff},
        "camera_bridge": {"axis_strategy": axis, "transition_execution": execution},
        "action_bridge": action_bridge,
        "reference_bridge": {
            "entity_mapping": reference_mapping,
            "different_character_same_slot_forbidden": True,
            "same_slot_reuse_allowed": same_slot_reuse_allowed,
        },
        "from_dialogue_speaker": _speaker(previous_spec),
        "to_dialogue_speaker": _speaker(current_spec),
    })
    return normalized


def validate_internal_transition_sequence(
    unit: dict[str, Any], *, editorial_shot_ids: list[str] | None = None
) -> list[dict[str, Any]]:
    unit_id = str(unit.get("unit_id") or "UNKNOWN")
    specs = unit.get("ordered_prompt_specs") or []
    shot_ids = list(editorial_shot_ids or unit.get("editorial_shot_ids") or [])
    if len(shot_ids) != len(specs):
        raise ValueError(f"{unit_id} internal continuity requires one editorial shot id per prompt beat")
    contracts = unit.get("internal_transition_contracts") or []
    expected_count = max(0, len(specs) - 1)
    if len(contracts) != expected_count:
        raise ValueError(
            f"{unit_id} requires {expected_count} authored internal transition contracts; got {len(contracts)}"
        )
    return [
        validate_internal_transition_contract(
            contract,
            unit_id=unit_id,
            from_shot_id=shot_ids[index],
            to_shot_id=shot_ids[index + 1],
            previous_spec=specs[index],
            current_spec=specs[index + 1],
        )
        for index, contract in enumerate(contracts)
    ]


def compile_internal_transition_prompt(unit: dict[str, Any]) -> str:
    contracts = unit.get("internal_transition_contracts") or []
    if not contracts:
        return "单节拍，无节拍内角色、场景、道具或声音交接。"
    lines: list[str] = []
    for row in contracts:
        cast = row["cast_bridge"]
        scene = row["scene_bridge"]
        props = row["prop_bridge"]
        sound = row["sound_bridge"]
        camera = row["camera_bridge"]
        lines.append(
            f"{row['boundary_id']}={row['transition_mode']}；"
            f"人物={cast['entry_exit_or_reveal']}，{cast['identity_preservation']}；"
            f"场景={scene['continuity']}；道具={props['ownership_or_handoff']}；"
            f"动作={row['action_bridge']}；声音={sound['bridge']}；"
            f"镜头={camera['transition_execution']}，{camera['axis_strategy']}；"
            f"参考图={row['reference_bridge']['entity_mapping']}；禁止用变脸、换衣或同位置替换代替交接。"
        )
    return "\n".join(lines)


def find_same_slot_character_replacements(
    unit: dict[str, Any], map_rows: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return adjacent map boundaries that replace one identity in one exact slot."""
    shot_ids = [str(value) for value in unit.get("editorial_shot_ids") or []]
    findings: list[dict[str, Any]] = []
    for index in range(len(shot_ids) - 1):
        source_id, target_id = shot_ids[index], shot_ids[index + 1]
        source = map_rows[source_id].get("blocking") or {}
        target = map_rows[target_id].get("blocking") or {}
        source_slots = {
            (str(row.get("zone_id") or ""), tuple(row.get("position") or [])): str(row.get("character_id") or "")
            for row in source.get("characters") or [] if row.get("character_id")
        }
        target_slots = {
            (str(row.get("zone_id") or ""), tuple(row.get("position") or [])): str(row.get("character_id") or "")
            for row in target.get("characters") or [] if row.get("character_id")
        }
        for slot in sorted(set(source_slots) & set(target_slots)):
            if source_slots[slot] != target_slots[slot]:
                findings.append({
                    "from_shot_id": source_id,
                    "to_shot_id": target_id,
                    "zone_id": slot[0],
                    "position": list(slot[1]),
                    "from_character_id": source_slots[slot],
                    "to_character_id": target_slots[slot],
                })
    return findings
