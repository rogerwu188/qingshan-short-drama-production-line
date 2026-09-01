#!/usr/bin/env python3
"""Model-neutral short-drama execution-plan compiler for SD2 and H3."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

try:
    from tools.provider_contract_boundary import (
        compact_identity_prop_fact,
        compact_space_weather_fact,
        structured_contract_sha256,
        unique_text,
    )
    from tools.video_motion_density_gate import validate_execution_plan
    from tools.video_physical_continuity_contract import (
        is_combat_unit,
        requires_interaction_topology,
    )
except ModuleNotFoundError:
    from provider_contract_boundary import (
        compact_identity_prop_fact,
        compact_space_weather_fact,
        structured_contract_sha256,
        unique_text,
    )
    from video_motion_density_gate import validate_execution_plan
    from video_physical_continuity_contract import is_combat_unit, requires_interaction_topology


SCHEMA = "qingshan.video_execution_plan.v2_shared_sd2_h3_typed_state_delta"
MODEL_FAMILY_BY_NAME = {
    "seedance-2.0-pro": "SEEDANCE_2",
    "minimax-h3": "MINIMAX_H3",
    "h3": "MINIMAX_H3",
}


def _timeline(specs: list[dict[str, Any]], duration_seconds: float) -> list[tuple[float, float]]:
    spans = []
    for spec in specs:
        action = spec.get("action") or {}
        span = float(action.get("t1_seconds") or 0.0) - float(action.get("t0_seconds") or 0.0)
        spans.append(max(0.001, span))
    total = sum(spans)
    cursor = 0.0
    result: list[tuple[float, float]] = []
    for index, span in enumerate(spans):
        end = duration_seconds if index == len(spans) - 1 else cursor + duration_seconds * span / total
        result.append((round(cursor, 3), round(end, 3)))
        cursor = end
    return result


def classify_unit(unit: dict[str, Any]) -> str:
    specs = unit.get("ordered_prompt_specs") or []
    if is_combat_unit(unit):
        return "COMBAT_IMPULSE" if len(specs) == 1 else "COMBAT_EXCHANGE"
    if any(str(spec.get("dialogue") or "").strip() for spec in specs):
        return "DIALOGUE"
    if not any(spec.get("cast") for spec in specs):
        return "ATMOSPHERE"
    return "PHYSICAL_ACTION"


def _compact_transition(unit: dict[str, Any]) -> dict[str, str]:
    incoming = unit.get("incoming_transition_contract") or {}
    outgoing = unit.get("outgoing_transition_contract") or {}
    inbound = ""
    outbound = ""
    if incoming:
        target = incoming.get("target_initial_state") or {}
        inbound = str(
            incoming.get("action_bridge")
            or incoming.get("visual_bridge")
            or target.get("blocking")
            or ""
        ).strip()
    if outgoing:
        source = outgoing.get("source_terminal_state") or {}
        outbound = str(
            outgoing.get("action_bridge")
            or outgoing.get("visual_bridge")
            or source.get("blocking")
            or ""
        ).strip()
    return {"incoming": inbound, "outgoing": outbound}


def compile_video_execution_plan(unit: dict[str, Any]) -> dict[str, Any]:
    model = str(unit.get("model") or "").strip().lower()
    family = MODEL_FAMILY_BY_NAME.get(model)
    if not family:
        raise ValueError(f"{unit.get('unit_id')}:UNSUPPORTED_EXECUTION_MODEL:{model}")
    specs = unit.get("ordered_prompt_specs") or []
    if not specs:
        raise ValueError(f"{unit.get('unit_id')}:ORDERED_PROMPT_SPECS_MISSING")
    duration = float(unit.get("duration_seconds") or 0.0)
    if duration < 4 or duration > 15:
        raise ValueError(f"{unit.get('unit_id')}:VIDEO_DURATION_OUT_OF_RANGE:{duration}")
    identity_fact, identity_lineage = compact_identity_prop_fact(unit)
    space_fact, space_lineage = compact_space_weather_fact(unit)
    unit_class = classify_unit(unit)
    beats = []
    internal_transitions = unit.get("internal_transition_contracts") or []
    for index, (spec, (start, end)) in enumerate(zip(specs, _timeline(specs, duration)), 1):
        action = spec.get("action") or {}
        beat = {
            "source_index": index,
            "start_seconds": start,
            "end_seconds": end,
            "entry_state": str(action.get("start_state") or "").strip(),
            "primary_action": str(action.get("primary_action") or "").strip(),
            "contact_time_seconds": action.get("contact_time_seconds"),
            "contact_point": str(action.get("contact_point") or "").strip(),
            "force_feedback": str(
                action.get("force_feedback") or action.get("physical_causality") or ""
            ).strip(),
            "exit_state": str(action.get("completion_state") or "").strip(),
            "state_delta_dimensions": list(action.get("state_delta_dimensions") or []),
            "state_delta_evidence": deepcopy(action.get("state_delta_evidence") or {}),
            "dialogue": str(spec.get("dialogue") or "").strip(),
            "dialogue_delivery": deepcopy(spec.get("dialogue_delivery") or {}),
            "performance_cue": str(
                (spec.get("performance") or {}).get("event_reaction")
                or (spec.get("performance") or {}).get("expression_arc")
                or ""
            ).strip(),
            "microexpression_cue": str(
                action.get("microexpression_design")
                or (spec.get("performance") or {}).get("expression_arc")
                or ""
            ).strip(),
            "body_sync_cue": str(
                (spec.get("performance") or {}).get("body_sync") or ""
            ).strip(),
            "internal_transition_after": str(
                ((internal_transitions[index - 1] if index - 1 < len(internal_transitions) else {}) or {}).get("action_bridge")
                or ((internal_transitions[index - 1] if index - 1 < len(internal_transitions) else {}) or {}).get("visual_bridge")
                or ""
            ).strip(),
        }
        beats.append(beat)
    sounds = {
        key: unique_text([
            (spec.get("sound_design") or {}).get(key) for spec in specs
        ])
        for key in ("ambience", "foley", "action_sound")
    }
    negatives = unique_text([
        value for spec in specs for value in spec.get("negative_prompts") or []
    ])
    environment_motion = unique_text([
        value
        for spec in specs
        for value in (
            list((spec.get("visual_design") or {}).get("environmental_motion") or [])
            + [
                (spec.get("ambient_life") or {}).get("motion_trend"),
                (spec.get("ambient_life") or {}).get("reaction_progression"),
            ]
        )
    ])
    voice_bindings = [
        {
            "speaker": str(row.get("speaker") or row.get("character") or "").strip(),
            "audio_slot": str(row.get("audio_slot") or "").strip(),
        }
        for row in (unit.get("speaker_voice_contract") or {}).get("bindings") or []
        if str(row.get("speaker") or row.get("character") or "").strip()
    ]
    plan = {
        "schema": SCHEMA,
        "unit_id": str(unit.get("unit_id") or "UNKNOWN"),
        "model_family": family,
        "duration_seconds": duration,
        "unit_class": unit_class,
        "identity_prop_fact": identity_fact,
        "space_weather_fact": space_fact,
        "camera_plan": deepcopy(unit.get("camera_plan") or {}),
        "transition": _compact_transition(unit),
        "beats": beats,
        "sounds": sounds,
        "environment_motion": environment_motion,
        "voice_bindings": voice_bindings,
        "negative_constraints": negatives,
        "native_audio_contract": str(unit.get("native_audio_contract") or ""),
        "interaction_topology_required": requires_interaction_topology(unit),
        "combat_execution_required": unit_class in {"COMBAT_IMPULSE", "COMBAT_EXCHANGE"},
        "immutable_contract_sha256": structured_contract_sha256(unit),
        "semantic_lineage": {
            "identity_prop_fact": identity_lineage,
            "space_weather_fact": space_lineage,
            "camera_plan": ["camera_plan"],
            "beats": [f"ordered_prompt_specs[{index}]" for index in range(len(specs))],
            "sounds": [f"ordered_prompt_specs[{index}].sound_design" for index in range(len(specs))],
            "environment_motion": [
                f"ordered_prompt_specs[{index}].visual_design.environmental_motion"
                for index in range(len(specs))
            ] + ["background_ecology_contract", "weather_visibility_contract"],
            "voice_bindings": ["speaker_voice_contract.bindings"],
            "negative_constraints": [
                f"ordered_prompt_specs[{index}].negative_prompts" for index in range(len(specs))
            ],
        },
    }
    semantic_projection = {
        key: deepcopy(plan[key])
        for key in (
            "duration_seconds", "unit_class", "identity_prop_fact", "space_weather_fact",
            "camera_plan", "transition", "beats", "sounds", "environment_motion",
            "voice_bindings", "negative_constraints", "native_audio_contract",
            "interaction_topology_required", "combat_execution_required",
        )
    }
    plan["execution_semantics_sha256"] = hashlib.sha256(json.dumps(
        semantic_projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    report = validate_execution_plan(plan)
    plan["motion_density_gate"] = report
    if report["status"] != "PASS":
        raise ValueError(";".join(report["failures"]))
    return plan
