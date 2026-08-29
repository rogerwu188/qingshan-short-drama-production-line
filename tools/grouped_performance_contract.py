#!/usr/bin/env python3
"""Performance, visual and sound contracts for grouped Seedance beats."""

from __future__ import annotations

from typing import Any


PERFORMANCE_FIELDS = (
    "psychological_state", "emotion", "emotion_intensity", "expression_arc",
    "continuous_micro_action", "event_reaction", "body_sync",
)
DIALOGUE_DELIVERY_FIELDS = (
    "pace", "pause_map", "emphasis_words", "volume_arc", "breath_pattern",
    "delivery_transition",
)
VISUAL_FIELDS = (
    "depth_layers", "scale_anchor", "key_light", "atmosphere",
    "environmental_motion", "material_detail", "still_prompt_contract",
    "video_motion_contract",
)
SOUND_FIELDS = ("ambience", "foley", "action_sound")


def _text(mapping: dict[str, Any], key: str, source_id: str) -> str:
    value = str(mapping.get(key) or "").strip()
    if not value:
        raise ValueError(f"{source_id} {key} is required")
    return value


def _spoken_text(raw: str) -> str:
    speaker, separator, spoken = raw.partition("：")
    if not separator or not speaker.strip() or not spoken.strip():
        raise ValueError("dialogue must use speaker：text format")
    return spoken.strip()


def validate_grouped_beat_contract(spec: Any, *, source_id: str) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError(f"{source_id} prompt_spec must be an object")
    action = spec.get("action")
    if not isinstance(action, dict):
        raise ValueError(f"{source_id} action contract is required")
    for field in (
        "start_state", "primary_action", "completion_state", "contact_point",
        "motion_direction", "physical_causality",
    ):
        _text(action, field, f"{source_id} action.{field}")

    performance = spec.get("performance")
    if not isinstance(performance, dict):
        raise ValueError(f"{source_id} performance contract is required")
    for field in PERFORMANCE_FIELDS:
        if field == "emotion_intensity":
            continue
        _text(performance, field, f"{source_id} performance.{field}")
    intensity = performance.get("emotion_intensity")
    if isinstance(intensity, bool) or not isinstance(intensity, int) or not 1 <= intensity <= 5:
        raise ValueError(f"{source_id} performance.emotion_intensity must be an integer from 1 to 5")
    expression_arc = str(performance["expression_arc"])
    if "→" not in expression_arc and "->" not in expression_arc:
        raise ValueError(f"{source_id} performance.expression_arc must declare visible change")

    cast_names = [
        str(row.get("character") or "").strip()
        for row in spec.get("cast") or [] if row.get("character")
    ]
    actor_performance = performance.get("actor_performance")
    if cast_names:
        if not isinstance(actor_performance, dict):
            raise ValueError(f"{source_id} performance.actor_performance must cover every visible actor")
        missing = sorted(set(cast_names) - set(actor_performance))
        extra = sorted(set(actor_performance) - set(cast_names))
        if missing or extra:
            raise ValueError(
                f"{source_id} performance.actor_performance cast mismatch: missing={missing} extra={extra}"
            )
        for actor in cast_names:
            row = actor_performance[actor]
            if not isinstance(row, dict):
                raise ValueError(f"{source_id} actor performance for {actor} must be an object")
            for field in ("expression_arc", "continuous_micro_action", "event_reaction", "body_sync"):
                _text(row, field, f"{source_id} performance.actor_performance.{actor}.{field}")

    dialogue = str(spec.get("dialogue") or "").strip()
    delivery = spec.get("dialogue_delivery")
    if dialogue:
        spoken = _spoken_text(dialogue)
        if not isinstance(delivery, dict):
            raise ValueError(f"{source_id} dialogue_delivery contract is required")
        for field in DIALOGUE_DELIVERY_FIELDS:
            if field == "emphasis_words":
                continue
            _text(delivery, field, f"{source_id} dialogue_delivery.{field}")
        emphasis = delivery.get("emphasis_words")
        if not isinstance(emphasis, list) or not emphasis or any(not str(word).strip() for word in emphasis):
            raise ValueError(f"{source_id} dialogue_delivery.emphasis_words must be a non-empty list")
        missing = [str(word) for word in emphasis if str(word) not in spoken]
        if missing:
            raise ValueError(f"{source_id} dialogue emphasis words absent from exact text: {missing}")
    elif delivery not in (None, {}):
        raise ValueError(f"{source_id} dialogue_delivery is forbidden when dialogue is empty")

    visual = spec.get("visual_design")
    if not isinstance(visual, dict):
        raise ValueError(f"{source_id} visual_design contract is required")
    for field in VISUAL_FIELDS:
        value = visual.get(field)
        if field == "depth_layers":
            if not isinstance(value, list) or len(value) < 3 or any(not str(row).strip() for row in value):
                raise ValueError(f"{source_id} visual_design.depth_layers requires foreground/midground/background")
        elif field in {"environmental_motion", "material_detail"}:
            if not isinstance(value, list) or not value or any(not str(row).strip() for row in value):
                raise ValueError(f"{source_id} visual_design.{field} must be a non-empty list")
        else:
            _text(visual, field, f"{source_id} visual_design.{field}")
    palette = visual.get("palette")
    if not isinstance(palette, dict):
        raise ValueError(f"{source_id} visual_design.palette is required")
    for role in ("dominant", "contrast", "accent"):
        _text(palette, role, f"{source_id} visual_design.palette.{role}")

    sound = spec.get("sound_design")
    if not isinstance(sound, dict):
        raise ValueError(f"{source_id} sound_design contract is required")
    for field in SOUND_FIELDS:
        _text(sound, field, f"{source_id} sound_design.{field}")

    negatives = spec.get("negative_prompts")
    if not isinstance(negatives, list) or not negatives or any(not str(row).strip() for row in negatives):
        raise ValueError(f"{source_id} negative_prompts must be a non-empty list")
    if str(action.get("action_kind") or "").upper() == "COMBAT":
        combat = spec.get("combat_choreography")
        if not isinstance(combat, dict):
            raise ValueError(f"{source_id} combat_choreography is required for combat action")
        for field in ("attack_defense_chain", "contact_and_force", "outcome_state", "identity_coverage"):
            _text(combat, field, f"{source_id} combat_choreography.{field}")
    return spec


def compile_performance_clause(spec: dict[str, Any]) -> str:
    p = spec["performance"]
    clause = (
        f"心理={p['psychological_state']}；情绪={p['emotion']}({p['emotion_intensity']}/5)；"
        f"表情弧={p['expression_arc']}；微动作={p['continuous_micro_action']}；"
        f"事件反应={p['event_reaction']}；身体同步={p['body_sync']}"
    )
    dialogue = str(spec.get("dialogue") or "").strip()
    if dialogue:
        d = spec["dialogue_delivery"]
        clause += (
            f"；说法=语速{d['pace']}、停连{d['pause_map']}、重音{'/'.join(d['emphasis_words'])}、"
            f"音量{d['volume_arc']}、气息{d['breath_pattern']}、句内转变{d['delivery_transition']}"
        )
    actor_rows = []
    for actor, row in (p.get("actor_performance") or {}).items():
        actor_rows.append(
            f"{actor}[表情{row['expression_arc']}；微动{row['continuous_micro_action']}；"
            f"反应{row['event_reaction']}；身体{row['body_sync']}]"
        )
    if actor_rows:
        clause += "；逐人覆盖=" + "、".join(actor_rows)
    return clause


def compile_visual_sound_clause(specs: list[dict[str, Any]]) -> str:
    first_visual = specs[0]["visual_design"]
    sound_rows = []
    for spec in specs:
        sound = spec["sound_design"]
        row = f"{sound['ambience']}／{sound['foley']}／{sound['action_sound']}"
        if row not in sound_rows:
            sound_rows.append(row)
    return (
        f"空间层次={' / '.join(first_visual['depth_layers'])}；尺度锚={first_visual['scale_anchor']}；"
        f"动机光={first_visual['key_light']}；空气={first_visual['atmosphere']}；"
        f"环境微动={' / '.join(first_visual['environmental_motion'])}；"
        f"材质={' / '.join(first_visual['material_detail'])}；"
        f"色彩={first_visual['palette']['dominant']}/{first_visual['palette']['contrast']}/{first_visual['palette']['accent']}；"
        f"静帧={first_visual['still_prompt_contract']}；视频运动={first_visual['video_motion_contract']}；"
        f"现场声={'；'.join(sound_rows)}。"
    )
