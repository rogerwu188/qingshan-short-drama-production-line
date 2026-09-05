#!/usr/bin/env python3
"""Model-neutral short-drama execution-plan compiler for SD2 and H3."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any
import re

try:
    from tools.provider_contract_boundary import (
        compact_identity_prop_fact,
        compact_space_weather_fact,
        structured_contract_sha256,
        unique_text,
    )
    from tools.video_motion_density_gate import validate_execution_plan
    from tools.camera_language_selector import select_camera_language
    from tools.wuxia_combat_profile_selector import select_wuxia_combat_profiles
    from tools.video_physical_continuity_contract import (
        is_combat_unit,
        requires_interaction_topology,
    )
    from tools.prop_state_contract import compile_prop_states
    from tools.cross_episode_event_continuity_gate import evaluate as evaluate_cross_episode_event
    from tools.event_boundary_continuity_contract import (
        compile_internal_shot_boundaries, validate_task_boundary,
    )
    from tools.h3_crossmodal_speaker_gate import require as require_h3_speaker_binding
except ModuleNotFoundError:
    from provider_contract_boundary import (
        compact_identity_prop_fact,
        compact_space_weather_fact,
        structured_contract_sha256,
        unique_text,
    )
    from video_motion_density_gate import validate_execution_plan
    from camera_language_selector import select_camera_language
    from wuxia_combat_profile_selector import select_wuxia_combat_profiles
    from video_physical_continuity_contract import is_combat_unit, requires_interaction_topology
    from prop_state_contract import compile_prop_states
    from cross_episode_event_continuity_gate import evaluate as evaluate_cross_episode_event
    from event_boundary_continuity_contract import (
        compile_internal_shot_boundaries, validate_task_boundary,
    )
    from h3_crossmodal_speaker_gate import require as require_h3_speaker_binding


SCHEMA = "qingshan.video_execution_plan.v6_entry_prop_patient_classification"
ACTION_IR_SCHEMA = "qingshan.action_ir.v1_single_causal_chain_per_beat"
MODEL_FAMILY_BY_NAME = {
    "seedance-2.0-pro": "SEEDANCE_2",
    "minimax-h3": "MINIMAX_H3",
    "h3": "MINIMAX_H3",
}


def _e51_rectification_required(unit: dict[str, Any]) -> bool:
    if unit.get("pipeline_rectification_version") == "E51_V1":
        return True
    identity = str(unit.get("episode") or unit.get("unit_id") or "").upper()
    match = re.search(r"(?:^|[^A-Z])E(\d+)", identity)
    return bool(match and int(match.group(1)) >= 51)


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
        duration = float(unit.get("duration_seconds") or 0.0)
        combat_specs = [
            spec for spec in specs
            if str((spec.get("action") or {}).get("action_kind") or "").upper() == "COMBAT"
        ]
        contacts = sum(
            1 for spec in combat_specs
            if _interaction_mode(spec.get("action") or {}) in {"CONTACT", "EVASION", "THREAT_THRESHOLD"}
        )
        if _e51_rectification_required(unit) and duration < 7.0 and contacts >= 2:
            return "COMBAT_IMPULSE"
        return "COMBAT_IMPULSE" if len(combat_specs) <= 1 else "COMBAT_EXCHANGE"
    if any(str(spec.get("dialogue") or "").strip() for spec in specs):
        return "DIALOGUE"
    if not any(spec.get("cast") for spec in specs):
        return "ATMOSPHERE"
    return "PHYSICAL_ACTION"


def _interaction_mode(action: dict[str, Any]) -> str:
    declared = str(action.get("interaction_mode") or "").strip().upper()
    if declared:
        return declared
    contact = str(action.get("contact_point") or "").strip()
    if any(token in contact for token in ("一掌距离", "尚未接触", "没有接触", "未碰到", "尚未碰到", "接触前")):
        return "THREAT_THRESHOLD"
    if contact:
        return "CONTACT"
    if str(action.get("evasion_result") or "").strip():
        return "EVASION"
    if str(action.get("threat_threshold") or "").strip():
        return "THREAT_THRESHOLD"
    return "NONE"


def _action_risk(beat: dict[str, Any]) -> dict[str, Any]:
    """Return advisory action capacity telemetry, never a post-generation gate."""
    interaction = 0 if beat["interaction_mode"] == "NONE" else 1
    secondary_count = len(beat.get("secondary_feedback") or [])
    score = (3 if beat.get("primary_action") else 0) + interaction * 2 + (
        2 if beat.get("primary_feedback") else 0
    ) + secondary_count + (
        2 if "POSITION" in beat.get("state_delta_dimensions", []) else 0
    )
    return {
        "score": score,
        "tier": "UNCALIBRATED_OBSERVE_ONLY",
        "hard_rejection": False,
        "purpose": "PER_BEAT_PRE_SUBMISSION_OBSERVABILITY_ONLY",
        "calibration_rule": "Derive thresholds from measured first-pass success data; do not block on this score.",
    }


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
        ownership = target.get("carryover_ownership") or {}
        owner = str(ownership.get("actor") or "").strip()
        patient = str(ownership.get("patient") or "").strip()
        if owner:
            ownership_clause = f"起态中的动作、肢体与道具继续属于{owner}"
            if patient:
                ownership_clause += f"，唯一承受者是{patient}"
            inbound = f"{inbound}；{ownership_clause}；不得把该起态转移给下一拍主角"
    if outgoing:
        source = outgoing.get("source_terminal_state") or {}
        outbound = str(
            outgoing.get("action_bridge")
            or outgoing.get("visual_bridge")
            or source.get("blocking")
            or ""
        ).strip()
    return {"incoming": inbound, "outgoing": outbound}


def _camera_authority(unit: dict[str, Any], *, combat: bool) -> dict[str, Any]:
    failures: list[str] = []
    if combat and unit.get("photography_prompt") and unit.get("combat_camera_language_prompt"):
        failures.append(f"CAMERA_CONTRACT_CONFLICT:{unit.get('unit_id')}:PHOTOGRAPHY_AND_COMBAT_CAMERA_BOTH_PRESENT")
    return {
        "status": "PASS" if not failures else "FAIL",
        "authority": "WRITER_CAMERA_PLAN_ONLY",
        "provider_render_rule": "RENDER_CAMERA_PLAN_ONCE; DO_NOT_APPEND_A_SECOND_PHOTOGRAPHY_OR_COMBAT_CAMERA_BLOCK",
        "writer_motion_preserved": True,
        "failures": failures,
    }


def compile_video_execution_plan(unit: dict[str, Any]) -> dict[str, Any]:
    model = str(unit.get("model") or "").strip().lower()
    family = MODEL_FAMILY_BY_NAME.get(model)
    if not family:
        raise ValueError(f"{unit.get('unit_id')}:UNSUPPORTED_EXECUTION_MODEL:{model}")
    specs = unit.get("ordered_prompt_specs") or []
    if not specs:
        raise ValueError(f"{unit.get('unit_id')}:ORDERED_PROMPT_SPECS_MISSING")
    duration = float(unit.get("duration_seconds") or 0.0)
    minimum_duration = 3.0 if family == "MINIMAX_H3" else 4.0
    if duration < minimum_duration or duration > 15:
        raise ValueError(f"{unit.get('unit_id')}:VIDEO_DURATION_OUT_OF_RANGE:{duration}")
    source_spans = [
        max(
            0.0,
            float((spec.get("action") or {}).get("t1_seconds") or 0.0)
            - float((spec.get("action") or {}).get("t0_seconds") or 0.0),
        )
        for spec in specs
    ]
    authorized_content_seconds = float(
        unit.get("authorized_content_seconds")
        or unit.get("source_duration_seconds")
        or sum(source_spans)
    )
    tail_handle_seconds = float(unit.get("authorized_tail_handle_seconds") or 0.25)
    identity_fact, identity_lineage = compact_identity_prop_fact(unit)
    space_fact, space_lineage = compact_space_weather_fact(unit)
    unit_class = classify_unit(unit)
    rectification_required = _e51_rectification_required(unit)
    event_boundary_enabled = (
        unit.get("event_boundary_decision") is not None
        or unit.get("persistent_state_contract") is not None
        or unit.get("continuity_event_contract_required") is True
        or unit.get("shot_state_contracts") is not None
    )
    event_boundary_failures = (
        validate_task_boundary(unit)
        if event_boundary_enabled
        else []
    )
    if event_boundary_failures:
        raise ValueError(";".join(event_boundary_failures))
    internal_shot_state_chain = compile_internal_shot_boundaries(unit) if event_boundary_enabled else {
        "schema": "qingshan.internal_shot_state_chain.v1",
        "status": "NOT_APPLICABLE", "boundaries": [], "failures": [],
    }
    if internal_shot_state_chain.get("status") == "FAIL":
        raise ValueError(";".join(internal_shot_state_chain.get("failures") or []))
    cross_episode_gate = {
        "schema": "qingshan.cross_episode_event_continuity_gate.v1",
        "status": "NOT_APPLICABLE",
        "failures": [],
    }
    if rectification_required and unit.get("episode_first_scene_unit") is True:
        cross_episode_gate = evaluate_cross_episode_event(
            unit.get("episode_opening_event_contract") or {}
        )
        if cross_episode_gate["status"] != "PASS":
            raise ValueError(";".join(cross_episode_gate["failures"]))
    combat_specs = [
        spec for spec in specs
        if str((spec.get("action") or {}).get("action_kind") or "").upper() == "COMBAT"
    ]
    combat_contact_count = sum(
        1 for spec in combat_specs
        if _interaction_mode(spec.get("action") or {}) in {"CONTACT", "EVASION", "THREAT_THRESHOLD"}
    ) if is_combat_unit(unit) else 0
    inferred_exchange = is_combat_unit(unit) and len(combat_specs) > 1
    class_laundering_failures: list[str] = []
    if rectification_required and inferred_exchange and duration < 7.0 and combat_contact_count >= 2:
        class_laundering_failures.append(
            f"UNIT_CLASS_LAUNDERING:{unit.get('unit_id')}:duration={duration:g}:contacts={combat_contact_count}:SPLIT_REQUIRED"
        )
    if rectification_required and unit_class == "COMBAT_EXCHANGE" and not (7.0 <= duration <= 12.0 and combat_contact_count <= 2):
        class_laundering_failures.append(
            f"UNIT_CLASS_LAUNDERING:{unit.get('unit_id')}:COMBAT_EXCHANGE_REQUIRES_7_TO_12_SECONDS_AND_AT_MOST_2_CONTACTS"
        )
    beats = []
    internal_transitions = unit.get("internal_transition_contracts") or []
    for index, (spec, (start, end)) in enumerate(zip(specs, _timeline(specs, duration)), 1):
        action = spec.get("action") or {}
        prop_states, prop_state_failures = compile_prop_states(
            spec, source_id=f"{unit.get('unit_id')}:BEAT_{index}"
        )
        if not rectification_required:
            prop_state_failures = []
        beat = {
            "source_index": index,
            "source_action_kind": str(action.get("action_kind") or "").strip().upper(),
            "e51_rectification_required": rectification_required,
            "action_patient": str(
                (spec.get("role_semantic_disambiguation") or {}).get("action_patient") or ""
            ).strip(),
            "start_seconds": start,
            "end_seconds": end,
            "entry_state": str(action.get("start_state") or "").strip(),
            "entry_state_ownership": deepcopy(action.get("entry_state_ownership") or {}),
            "primary_action": str(action.get("primary_action") or "").strip(),
            "contact_time_seconds": action.get("contact_time_seconds"),
            "contact_point": str(action.get("contact_point") or "").strip(),
            "force_feedback": str(
                action.get("force_feedback") or action.get("physical_causality") or ""
            ).strip(),
            "force_origin": str(
                action.get("force_origin")
                or action.get("power_path")
                or action.get("start_state")
                or ""
            ).strip(),
            "interaction_mode": _interaction_mode(action),
            "primary_feedback": str(
                action.get("primary_feedback")
                or action.get("force_feedback")
                or action.get("physical_causality")
                or ""
            ).strip(),
            "secondary_feedback": [
                str(value).strip()
                for value in action.get("secondary_feedback") or []
                if str(value).strip()
            ],
            "patient_state_delta_dimensions": list(action.get("patient_state_delta_dimensions") or []),
            "patient_state_delta_evidence": deepcopy(action.get("patient_state_delta_evidence") or {}),
            "prop_states": prop_states,
            "prop_state_failures": prop_state_failures,
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
        beat["action_capacity"] = _action_risk(beat)
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
    h3_crossmodal_speaker_binding = (
        require_h3_speaker_binding(unit)
        if family == "MINIMAX_H3"
        else {
            "schema": "qingshan.h3_crossmodal_speaker_gate.v1_atomic_speaker_turn",
            "status": "NOT_APPLICABLE",
            "bindings": [],
            "failures": [],
        }
    )
    role_bindings = []
    for spec in specs:
        role = spec.get("role_semantic_disambiguation") or {}
        role_bindings.append({
            "shot_id": str(role.get("shot_id") or "").strip(),
            "primary_actor": str(role.get("primary_actor") or "").strip(),
            "primary_actor_kind": str(role.get("primary_actor_kind") or "CHARACTER").strip(),
            "dialogue_speaker": str(role.get("dialogue_speaker") or "").strip(),
            "dialogue_listener": str(role.get("dialogue_listener") or "").strip(),
            "dialogue_mode": str(role.get("dialogue_mode") or "NONE").strip(),
            "action_patient": str(role.get("action_patient") or "").strip(),
        })
    selected_camera_plan, camera_language_selection = select_camera_language(
        deepcopy(unit.get("camera_plan") or {}),
        unit_class=unit_class,
        unit=unit,
        source_id=str(unit.get("unit_id") or "UNKNOWN"),
    )
    action_ir = {
        "schema": ACTION_IR_SCHEMA,
        "unit_class": unit_class,
        "e51_rectification_required": rectification_required,
        "unit_classification_gate": {
            "status": "PASS" if not class_laundering_failures else "FAIL",
            "combat_contact_count": combat_contact_count,
            "duration_seconds": duration,
            "forced_class": unit_class,
            "required": rectification_required,
            "failures": class_laundering_failures,
        },
        "causal_chains": deepcopy(beats),
        "rule": (
            "Each beat contains one primary causal chain: entry and force origin, "
            "one primary action, one contact/evasion/threat threshold, one primary "
            "feedback, optional secondary feedback, and one observable irreversible exit-state delta."
        ),
        "post_generation_dynamic_media_qa_required": False,
    }
    wuxia_profile_selection = select_wuxia_combat_profiles(
        unit,
        action_ir=action_ir,
        unit_class=unit_class,
    )
    plan = {
        "schema": SCHEMA,
        "unit_id": str(unit.get("unit_id") or "UNKNOWN"),
        "model_family": family,
        "duration_seconds": duration,
        "duration_authority": {
            "authorized_content_seconds": authorized_content_seconds,
            "authorized_tail_handle_seconds": tail_handle_seconds,
            "requested_duration_seconds": duration,
            "underfill_seconds": round(
                max(0.0, duration - authorized_content_seconds - tail_handle_seconds), 3
            ),
            "failure_code": "DURATION_EXCEEDS_AUTHORIZED_CONTENT",
            "failure_action": "REDESIGN_UNIT_BOUNDARY_OR_SHORTEN_DURATION_BEFORE_SUBMISSION",
        },
        "unit_class": unit_class,
        "e51_rectification_required": rectification_required,
        "unit_classification_gate": {
            "status": "PASS" if not class_laundering_failures else "FAIL",
            "combat_contact_count": combat_contact_count,
            "duration_seconds": duration,
            "forced_class": unit_class,
            "required": rectification_required,
            "failures": class_laundering_failures,
        },
        "identity_prop_fact": identity_fact,
        "space_weather_fact": space_fact,
        "camera_plan": selected_camera_plan,
        "camera_language_selection": camera_language_selection,
        "camera_authority_gate": _camera_authority(unit, combat=is_combat_unit(unit)),
        "cross_episode_event_continuity_gate": cross_episode_gate,
        "event_boundary_decision": deepcopy(unit.get("event_boundary_decision") or {}),
        "persistent_state_contract": deepcopy(unit.get("persistent_state_contract") or {}),
        "shot_state_contracts": deepcopy(unit.get("shot_state_contracts") or []),
        "internal_shot_state_chain": internal_shot_state_chain,
        "wuxia_combat_profile_selection": wuxia_profile_selection,
        "transition": _compact_transition(unit),
        "beats": beats,
        "action_ir": action_ir,
        "sounds": sounds,
        "environment_motion": environment_motion,
        "voice_bindings": voice_bindings,
        "h3_crossmodal_speaker_binding": h3_crossmodal_speaker_binding,
        "role_bindings": role_bindings,
        "negative_constraints": negatives,
        "native_audio_contract": str(unit.get("native_audio_contract") or ""),
        "interaction_topology_required": requires_interaction_topology(unit),
        "combat_execution_required": unit_class in {"COMBAT_IMPULSE", "COMBAT_EXCHANGE"},
        "immutable_contract_sha256": structured_contract_sha256(unit),
        "semantic_lineage": {
            "identity_prop_fact": identity_lineage,
            "space_weather_fact": space_lineage,
            "camera_plan": ["camera_plan"],
            "camera_language_selection": ["camera_plan", "camera_language_mode", "camera_style_authorizations"],
            "wuxia_combat_profile_selection": [
                "wuxia_combat_profile_required", "wuxia_combat_profile_signals",
                "ordered_prompt_specs[].action", "ordered_prompt_specs[].props",
            ],
            "event_boundary_decision": ["event_boundary_decision"],
            "persistent_state_contract": ["persistent_state_contract"],
            "shot_state_contracts": ["shot_state_contracts"],
            "internal_shot_state_chain": ["shot_state_contracts", "internal_transition_contracts"],
            "beats": [f"ordered_prompt_specs[{index}]" for index in range(len(specs))],
            "sounds": [f"ordered_prompt_specs[{index}].sound_design" for index in range(len(specs))],
            "environment_motion": [
                f"ordered_prompt_specs[{index}].visual_design.environmental_motion"
                for index in range(len(specs))
            ] + ["background_ecology_contract", "weather_visibility_contract"],
            "voice_bindings": ["speaker_voice_contract.bindings"],
            "h3_crossmodal_speaker_binding": [
                "speaker_voice_contract.bindings",
                "provider_entity_token_map",
                "provider_scope_projection.reference_identity_bindings",
                "ordered_prompt_specs[].dialogue",
            ],
            "role_bindings": [
                f"ordered_prompt_specs[{index}].role_semantic_disambiguation"
                for index in range(len(specs))
            ],
            "negative_constraints": [
                f"ordered_prompt_specs[{index}].negative_prompts" for index in range(len(specs))
            ],
        },
    }
    semantic_projection = {
        key: deepcopy(plan[key])
        for key in (
            "duration_seconds", "unit_class", "e51_rectification_required", "identity_prop_fact", "space_weather_fact",
            "duration_authority", "unit_classification_gate", "camera_plan", "camera_language_selection", "camera_authority_gate", "cross_episode_event_continuity_gate", "event_boundary_decision", "persistent_state_contract", "shot_state_contracts", "internal_shot_state_chain", "wuxia_combat_profile_selection", "transition", "beats", "sounds", "environment_motion",
            # Cross-modal H3 binding is a model-specific rendering guard and is
            # intentionally excluded from the shared SD2/H3 semantic hash.
            "action_ir", "voice_bindings", "negative_constraints", "native_audio_contract",
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
