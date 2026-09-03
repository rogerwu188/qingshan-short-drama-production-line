#!/usr/bin/env python3
"""Validate that writer/director production fields survive into the contract.

This gate runs before a new four-layer writer seal.  It does not require model
syntax, but it prevents downstream builders from reconstructing omitted camera,
performance, environment, weather, sound or action-space meaning with generic
templates.
"""

from __future__ import annotations

from typing import Any

try:
    from tools.grouped_performance_contract import validate_grouped_beat_contract
    from tools.visual_culture_contract import validate_visual_culture_contract
    from tools.character_entity_contract import validate_character_entity_contract
except ModuleNotFoundError:
    from grouped_performance_contract import validate_grouped_beat_contract
    from visual_culture_contract import validate_visual_culture_contract
    from character_entity_contract import validate_character_entity_contract


def _text(value: Any) -> str:
    return str(value or "").strip()


def validate_generation_contract(payload: dict[str, Any]) -> dict[str, Any]:
    episode = _text(payload.get("episode")) or "UNKNOWN"
    failures: list[str] = []
    culture = validate_visual_culture_contract(payload)
    failures.extend(culture["failures"])
    identity = validate_character_entity_contract(payload)
    failures.extend(identity["failures"])
    scenes = payload.get("scene_states") or []
    scenes_by_id = {_text(row.get("scene_id")): row for row in scenes}
    shots = payload.get("shots") or []
    if not scenes:
        failures.append("SCENE_STATES_MISSING")
    if not shots:
        failures.append("SHOTS_MISSING")
    for scene in scenes:
        scene_id = _text(scene.get("scene_id")) or "UNKNOWN_SCENE"
        for field in (
            "location_id", "time_of_day_state", "weather_state", "visual_zone",
            "interior_exterior", "palette_temperature",
        ):
            if not _text(scene.get(field)):
                failures.append(f"{scene_id}_{field.upper()}_MISSING")
        ambient = scene.get("ambient_life")
        if not isinstance(ambient, dict):
            failures.append(f"{scene_id}_AMBIENT_LIFE_MISSING")
        else:
            if _text(ambient.get("grade")) not in {"A", "B", "C"}:
                failures.append(f"{scene_id}_AMBIENT_LIFE_GRADE_INVALID")
            for field in ("motion_trend", "first_frame_state", "reaction_progression"):
                if not _text(ambient.get(field)):
                    failures.append(f"{scene_id}_AMBIENT_LIFE_{field.upper()}_MISSING")
        weather = scene.get("weather_provenance")
        if not isinstance(weather, dict):
            failures.append(f"{scene_id}_WEATHER_PROVENANCE_MISSING")
        else:
            for field in ("source_type", "source_ref", "visibility_mode"):
                if not _text(weather.get(field)):
                    failures.append(f"{scene_id}_WEATHER_PROVENANCE_{field.upper()}_MISSING")

    for shot in shots:
        shot_id = _text(shot.get("shot_id")) or "UNKNOWN_SHOT"
        for field in (
            "scene_id", "first_frame_motion_state", "camera", "subspace_id",
            "frame_content", "shot_treatment", "expression_arc",
        ):
            if not _text(shot.get(field)):
                failures.append(f"{shot_id}_{field.upper()}_MISSING")
        action = shot.get("action_visualization")
        if not isinstance(action, dict):
            failures.append(f"{shot_id}_ACTION_VISUALIZATION_MISSING")
        else:
            for field in ("purpose_and_stake", "invisible_factor", "visible_phenomenon", "readability_self_check"):
                if not _text(action.get(field)):
                    failures.append(f"{shot_id}_ACTION_VISUALIZATION_{field.upper()}_MISSING")
        negatives = shot.get("negative_prompts")
        if not isinstance(negatives, list) or not negatives or any(not _text(value) for value in negatives):
            failures.append(f"{shot_id}_NEGATIVE_PROMPTS_MISSING")

        # The writer is the source of creative decisions.  A downstream
        # builder may serialize or regroup them, but may not invent a missing
        # action/performance/camera/role/sound contract from a generic template.
        spec = shot.get("prompt_spec")
        if not isinstance(spec, dict):
            failures.append(f"{shot_id}_PROMPT_SPEC_MISSING")
            continue
        try:
            validate_grouped_beat_contract(spec, source_id=shot_id)
        except ValueError as exc:
            failures.append(f"{shot_id}_PROMPT_SPEC_INVALID:{exc}")
        for field, source_field in (
            ("writer_camera_instruction", "camera"),
            ("writer_shot_treatment", "shot_treatment"),
            ("writer_expression_arc", "expression_arc"),
            ("source_first_frame_motion_state", "first_frame_motion_state"),
        ):
            if _text(spec.get(field)) != _text(shot.get(source_field)):
                failures.append(f"{shot_id}_{field.upper()}_SOURCE_BINDING_MISMATCH")
        if _text(spec.get("dialogue")) != _text(shot.get("dialogue")):
            failures.append(f"{shot_id}_DIALOGUE_SOURCE_BINDING_MISMATCH")
        if list(spec.get("negative_prompts") or []) != list(negatives or []):
            failures.append(f"{shot_id}_NEGATIVE_PROMPT_SOURCE_BINDING_MISMATCH")
        space = spec.get("space") or {}
        if _text(space.get("subspace")) != _text(shot.get("subspace_id")):
            failures.append(f"{shot_id}_SUBSPACE_SOURCE_BINDING_MISMATCH")
        if not _text(space.get("global")) or not _text(space.get("location")):
            failures.append(f"{shot_id}_COMPLETE_MAP_SPACE_BINDING_MISSING")
        scene = scenes_by_id.get(_text(shot.get("scene_id"))) or {}
        scene_state = spec.get("scene_state") or {}
        if _text(scene_state.get("weather")) != _text(scene.get("weather_state")):
            failures.append(f"{shot_id}_WEATHER_SOURCE_BINDING_MISMATCH")
        if _text(scene_state.get("time")) != _text(scene.get("time_of_day_state")):
            failures.append(f"{shot_id}_TIME_SOURCE_BINDING_MISMATCH")
        if scene_state.get("ambient_life") != scene.get("ambient_life"):
            failures.append(f"{shot_id}_AMBIENT_LIFE_SOURCE_BINDING_MISMATCH")
        if scene_state.get("weather_provenance") != scene.get("weather_provenance"):
            failures.append(f"{shot_id}_WEATHER_PROVENANCE_SOURCE_BINDING_MISMATCH")
        role = spec.get("role_semantic_disambiguation")
        if not isinstance(role, dict) or role.get("status") != "PASS":
            failures.append(f"{shot_id}_ROLE_SEMANTIC_DISAMBIGUATION_MISSING")
        if _text(spec.get("audio_contract")) not in {
            "SAME_VIDEO_TASK_NATIVE_AUDIO",
            "DIEGETIC_OR_SILENT_NO_TTS",
            "SAME_VIDEO_TASK_NATIVE_DIALOGUE_AMBIENCE_FOLEY_ACTION_SOUND",
        }:
            failures.append(f"{shot_id}_AUDIO_CONTRACT_INVALID")

    audio = payload.get("audio_contract") or {}
    if "bgm" not in audio:
        failures.append("AUDIO_BGM_CREATIVE_DECISION_MISSING")
    ambient_by_scene = audio.get("ambient_by_scene")
    if not isinstance(ambient_by_scene, dict):
        failures.append("AUDIO_AMBIENT_BY_SCENE_MISSING")
    else:
        scene_ids = {_text(scene.get("scene_id")) for scene in scenes}
        if set(ambient_by_scene) != scene_ids:
            failures.append("AUDIO_AMBIENT_SCENE_COVERAGE_MISMATCH")
        if any(not isinstance(value, dict) for value in ambient_by_scene.values()):
            failures.append("AUDIO_AMBIENT_SCENE_VALUE_MUST_BE_STRUCTURED_NOT_WEATHER_STRING")
    return {
        "schema": "qingshan.writer_production_field_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "episode": episode,
        "scene_count": len(scenes),
        "shot_count": len(shots),
        "failures": failures,
    }
