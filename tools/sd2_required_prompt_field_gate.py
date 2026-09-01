#!/usr/bin/env python3
"""End-to-end non-bypassable field coverage gate for Seedance 2.0 units."""

from __future__ import annotations

from typing import Any

try:
    from tools.dialogue_cut_safety import compile_dialogue_windows
    from tools.grouped_camera_contract import compile_camera_prompt
    from tools.grouped_internal_continuity_contract import compile_internal_transition_prompt
    from tools.grouped_transition_contract import compile_transition_prompt
    from tools.role_semantic_prompt_gate import role_semantic_compact_prompt_block
    from tools.sd2_background_ecology_contract import (
        compile_background_ecology_prompt_block,
        compile_weather_visibility_prompt_block,
    )
    from tools.speaker_voice_contract import speaker_voice_prompt_block
    from tools.wardrobe_identity_contract import wardrobe_prompt_block
except ModuleNotFoundError:
    from dialogue_cut_safety import compile_dialogue_windows
    from grouped_camera_contract import compile_camera_prompt
    from grouped_internal_continuity_contract import compile_internal_transition_prompt
    from grouped_transition_contract import compile_transition_prompt
    from role_semantic_prompt_gate import role_semantic_compact_prompt_block
    from sd2_background_ecology_contract import (
        compile_background_ecology_prompt_block,
        compile_weather_visibility_prompt_block,
    )
    from speaker_voice_contract import speaker_voice_prompt_block
    from wardrobe_identity_contract import wardrobe_prompt_block


REQUIRED_PROMPT_SECTIONS = {
    "camera": "【镜头硬合同】",
    "map_space": "【地图与空间硬合同】",
    "transition": "【转场硬合同】",
    "internal_continuity": "【节拍内连续性硬合同】",
    "visual_sound": "【视觉与现场声硬合同】",
    "ecology": "【背景生态硬合同】",
    "weather_visibility": "【天气可见性硬合同】",
    "negative_constraints": "【逐拍负面限制】",
    "wardrobe": "【服装身份硬合同】",
    "voice": "【角色声线与发声实体硬合同】",
    "role_semantics": "【角色语义消歧硬锁】",
    "performance": "【表演连续性】",
    "physical_topology": "【肢体与接触拓扑】",
    "dialogue_cut": "【对白安全切点】",
    "native_audio": "【同任务原生声音】",
}

FORBIDDEN_GENERIC_PLACEHOLDERS = (
    "风只推动帘、衣摆、柳枝或蒸汽中的相关一项",
    "水面或街面反光低幅连续变化",
    "池水、风、远席或街市按所在场景保持空间混响",
    "眼神/布料/手部从既定起点沿单一方向到达结果态",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _require_value_in_prompt(
    failures: list[str], prompt: str, source: str, field: str, value: Any
) -> None:
    normalized = _text(value)
    if not normalized:
        failures.append(f"{source}_{field.upper()}_MISSING")
    elif normalized not in prompt and normalized.rstrip("。！？；,.!?; ") not in prompt:
        failures.append(f"{source}_{field.upper()}_NOT_COMPILED")


def validate_required_sd2_field_coverage(unit: dict[str, Any], prompt: str) -> dict[str, Any]:
    failures: list[str] = []
    specs = unit.get("ordered_prompt_specs") or []
    for name, marker in REQUIRED_PROMPT_SECTIONS.items():
        if prompt.count(marker) != 1:
            failures.append(f"SECTION_{name.upper()}_COUNT:{prompt.count(marker)}")
    for phrase in FORBIDDEN_GENERIC_PLACEHOLDERS:
        if phrase in prompt:
            failures.append(f"GENERIC_PLACEHOLDER_SURVIVED:{phrase}")

    if not unit.get("reference_images"):
        failures.append("REFERENCE_IMAGE_BINDING_MISSING")
    start = unit.get("start_frame_semantic_contract") or {}
    if start.get("status") != "PASS" or not start.get("space_match") or start.get("empty_establishing_frame"):
        failures.append("START_FRAME_SEMANTIC_MOTION_SPACE_GATE_MISSING")
    if not unit.get("camera_plan"):
        failures.append("CAMERA_PLAN_MISSING")
    if not unit.get("wardrobe_contract"):
        failures.append("WARDROBE_IDENTITY_CONTRACT_MISSING")
    if not unit.get("speaker_voice_contract"):
        failures.append("SPEAKER_VOICE_CONTRACT_MISSING")
    if not unit.get("background_ecology_contract"):
        failures.append("BACKGROUND_ECOLOGY_CONTRACT_MISSING")
    if not unit.get("weather_visibility_contract"):
        failures.append("WEATHER_VISIBILITY_CONTRACT_MISSING")

    # Section markers alone are not evidence.  Recompile every structured
    # high-risk block and demand an exact match in the provider-facing text so
    # a stale/manual prompt cannot replace a real contract with empty prose.
    exact_blocks: list[tuple[str, str]] = []
    try:
        exact_blocks.extend([
            ("CAMERA", "【镜头硬合同】" + compile_camera_prompt(
                unit.get("camera_plan"), source_id=str(unit.get("unit_id") or "UNKNOWN")
            )),
            ("TRANSITION", "【转场硬合同】" + compile_transition_prompt(unit)),
            ("INTERNAL_CONTINUITY", "【节拍内连续性硬合同】" + compile_internal_transition_prompt(unit)),
            ("WARDROBE", "【服装身份硬合同】" + wardrobe_prompt_block(unit)),
            ("VOICE", "【角色声线与发声实体硬合同】" + speaker_voice_prompt_block(
                unit, model_family="seedance2"
            )),
            ("ECOLOGY", "【背景生态硬合同】" + compile_background_ecology_prompt_block(
                unit.get("background_ecology_contract") or {}
            )),
            ("WEATHER_VISIBILITY", "【天气可见性硬合同】" + compile_weather_visibility_prompt_block(
                unit.get("weather_visibility_contract") or {}
            )),
        ])
    except (KeyError, TypeError, ValueError) as exc:
        failures.append(f"STRUCTURED_BLOCK_RECOMPILE_FAILED:{exc}")
    for name, block in exact_blocks:
        count = prompt.count(block)
        if count != 1:
            failures.append(f"EXACT_{name}_BLOCK_COUNT:{count}")

    for index, spec in enumerate(specs, start=1):
        role = spec.get("role_semantic_disambiguation")
        if isinstance(role, dict):
            block = role_semantic_compact_prompt_block(role)
            if prompt.count(block) != 1:
                failures.append(f"BEAT_{index}_EXACT_ROLE_SEMANTIC_BLOCK_COUNT:{prompt.count(block)}")

    try:
        dialogue_windows = compile_dialogue_windows(unit)
    except (KeyError, TypeError, ValueError) as exc:
        failures.append(f"DIALOGUE_WINDOW_RECOMPILE_FAILED:{exc}")
        dialogue_windows = []
    if dialogue_windows:
        for row in dialogue_windows:
            expected = (
                f"节拍{row['spec_index'] + 1}对白仅在{row['start_seconds']:g}–{row['end_seconds']:g}秒，"
                f"随后闭口并至少保留{row['safety_pad_seconds']:g}秒安全尾柄"
            )
            if prompt.count(expected) != 1:
                failures.append(
                    f"DIALOGUE_SAFE_WINDOW_NOT_EXACTLY_BOUND:BEAT_{row['spec_index'] + 1}"
                )
    elif "【对白安全切点】本单元无对白；转场预留内只保留现场声与动作结果。" not in prompt:
        failures.append("NO_DIALOGUE_SAFE_CUT_BLOCK_MISSING")

    for index, spec in enumerate(specs, start=1):
        source = f"BEAT_{index}"
        for field in ("space", "scene_state", "action", "performance", "visual_design", "sound_design"):
            if not isinstance(spec.get(field), dict) or not spec[field]:
                failures.append(f"{source}_{field.upper()}_MISSING")
        role = spec.get("role_semantic_disambiguation")
        if not isinstance(role, dict):
            failures.append(f"{source}_ROLE_SEMANTICS_MISSING")
            role = {}
        if not isinstance(spec.get("negative_prompts"), list) or not spec.get("negative_prompts"):
            failures.append(f"{source}_NEGATIVE_CONSTRAINTS_MISSING")
        action = spec.get("action") or {}
        if not _text(action.get("action_kind")):
            failures.append(f"{source}_ACTION_KIND_MISSING")
        for field in ("start_state", "primary_action", "completion_state", "contact_point", "motion_direction", "physical_causality"):
            if not _text(action.get(field)):
                failures.append(f"{source}_ACTION_{field.upper()}_MISSING")
            else:
                _require_value_in_prompt(failures, prompt, source, f"ACTION_{field}", action.get(field))
        for field in ("action_kind", "microexpression_design", "physical_action_design"):
            _require_value_in_prompt(failures, prompt, source, f"ACTION_{field}", action.get(field))
        for field in ("global", "location", "subspace"):
            if not _text((spec.get("space") or {}).get(field)):
                failures.append(f"{source}_SPACE_{field.upper()}_MISSING")
        for field in ("time", "weather", "palette"):
            _require_value_in_prompt(
                failures, prompt, source, f"SCENE_{field}", (spec.get("scene_state") or {}).get(field)
            )
        for field in ("writer_camera_instruction", "writer_shot_treatment", "writer_expression_arc"):
            _require_value_in_prompt(failures, prompt, source, field, spec.get(field))
        performance = spec.get("performance") or {}
        for field in ("expression_arc", "continuous_micro_action", "event_reaction", "body_sync"):
            if not _text(performance.get(field)):
                failures.append(f"{source}_PERFORMANCE_{field.upper()}_MISSING")
            else:
                _require_value_in_prompt(failures, prompt, source, f"PERFORMANCE_{field}", performance.get(field))
        visualization = spec.get("action_visualization")
        if not isinstance(visualization, dict):
            failures.append(f"{source}_ACTION_VISUALIZATION_MISSING")
        else:
            for field in ("purpose_and_stake", "invisible_factor", "visible_phenomenon", "readability_self_check"):
                if not _text(visualization.get(field)):
                    failures.append(f"{source}_ACTION_VISUALIZATION_{field.upper()}_MISSING")
                else:
                    _require_value_in_prompt(
                        failures, prompt, source, f"ACTION_VISUALIZATION_{field}", visualization.get(field)
                    )
        visual = spec.get("visual_design") or {}
        for field in ("scale_anchor", "key_light", "atmosphere", "still_prompt_contract", "video_motion_contract"):
            _require_value_in_prompt(failures, prompt, source, f"VISUAL_{field}", visual.get(field))
        for field in ("depth_layers", "environmental_motion", "material_detail"):
            values = visual.get(field) or []
            if not isinstance(values, list) or not values:
                failures.append(f"{source}_VISUAL_{field.upper()}_MISSING")
            else:
                for value in values:
                    _require_value_in_prompt(failures, prompt, source, f"VISUAL_{field}", value)
        palette = visual.get("palette") or {}
        for field in ("dominant", "contrast", "accent"):
            _require_value_in_prompt(failures, prompt, source, f"VISUAL_PALETTE_{field}", palette.get(field))
        sound = spec.get("sound_design") or {}
        for field in ("ambience", "foley", "action_sound"):
            _require_value_in_prompt(failures, prompt, source, f"SOUND_{field}", sound.get(field))
        ambient = spec.get("ambient_life") or {}
        for field in ("grade", "motion_trend", "first_frame_state", "reaction_progression"):
            _require_value_in_prompt(failures, prompt, source, f"AMBIENT_LIFE_{field}", ambient.get(field))
        provenance = (spec.get("scene_state") or {}).get("weather_provenance") or {}
        for field in ("source_type", "source_ref", "visibility_mode"):
            _require_value_in_prompt(failures, prompt, source, f"WEATHER_PROVENANCE_{field}", provenance.get(field))
        for value in spec.get("negative_prompts") or []:
            _require_value_in_prompt(failures, prompt, source, "NEGATIVE_CONSTRAINT", value)
        audio_contract = _text(spec.get("audio_contract"))
        if audio_contract not in {
            "SAME_VIDEO_TASK_NATIVE_AUDIO",
            "DIEGETIC_OR_SILENT_NO_TTS",
            "SAME_VIDEO_TASK_NATIVE_DIALOGUE_AMBIENCE_FOLEY_ACTION_SOUND",
        }:
            failures.append(f"{source}_AUDIO_CONTRACT_INVALID:{audio_contract or 'MISSING'}")
        if "禁止 TTS" not in prompt or "【同任务原生声音】" not in prompt:
            failures.append(f"{source}_AUDIO_CONTRACT_NOT_COMPILED")
        visible_characters: set[str] = set()
        for row in spec.get("cast") or []:
            character = _text(row.get("character"))
            if character:
                visible_characters.add(character)
            if character and character not in prompt:
                failures.append(f"{source}_VISIBLE_CHARACTER_NOT_BOUND:{character}")
        speaker = _text(role.get("dialogue_speaker"))
        listener = _text(role.get("dialogue_listener"))
        actor = _text(role.get("primary_actor"))
        actor_kind = _text(role.get("primary_actor_kind")).upper()
        if speaker and speaker not in visible_characters:
            failures.append(f"{source}_DIALOGUE_SPEAKER_NOT_IN_CAST:{speaker}")
        if listener and listener not in visible_characters:
            failures.append(f"{source}_DIALOGUE_LISTENER_NOT_IN_CAST:{listener}")
        if actor_kind in {"CHARACTER", "GROUP", "ANIMAL"} and actor and actor not in visible_characters:
            failures.append(f"{source}_PRIMARY_ACTOR_NOT_IN_CAST:{actor}")
        for row in spec.get("props") or []:
            prop = _text(row.get("prop"))
            if prop and prop not in prompt:
                failures.append(f"{source}_PROP_NOT_BOUND:{prop}")
        dialogue = _text(spec.get("dialogue"))
        if dialogue:
            dialogue_speaker, separator, spoken = dialogue.partition("：")
            if not separator or not dialogue_speaker.strip() or not spoken.strip():
                failures.append(f"{source}_DIALOGUE_NOT_SPEAKER_BOUND")
            elif dialogue_speaker.strip() != speaker:
                failures.append(
                    f"{source}_DIALOGUE_ROLE_SPEAKER_MISMATCH:{dialogue_speaker.strip()}!={speaker}"
                )
            elif dialogue_speaker.strip() not in prompt or spoken.strip() not in prompt:
                failures.append(f"{source}_DIALOGUE_PROMPT_BINDING_MISSING")
        if _text(action.get("action_kind")).upper() == "COMBAT" and not spec.get("combat_choreography"):
            failures.append(f"{source}_COMBAT_CHOREOGRAPHY_MISSING")

    return {
        "schema": "qingshan.sd2_required_prompt_field_coverage.v1",
        "status": "PASS" if not failures else "FAIL",
        "unit_id": unit.get("unit_id"),
        "covered_domains": sorted(REQUIRED_PROMPT_SECTIONS),
        "machine_bound_domains": ["complete_map", "reference_images", "start_frame_semantics"],
        "failures": failures,
    }
