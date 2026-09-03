#!/usr/bin/env python3
"""MiniMax-H3 renderer over the shared execution plan.

All machine-facing prose is English. Original-language dialogue is the only
text allowed inside ``<d>[Chinese]...</d>`` tags.
"""

from __future__ import annotations

from typing import Any

try:
    from tools.h3_provider_english_contract import (
        require_h3_provider_english_contract,
        validate_h3_provider_text_boundary,
    )
    from tools.prompt_budget_observability import measure_prompt
    from tools.provider_contract_boundary import validate_provider_prompt_boundary
    from tools.provider_semantic_coverage import build_semantic_coverage_receipt
    from tools.wardrobe_identity_contract import h3_adult_female_visual_block
except ModuleNotFoundError:
    from h3_provider_english_contract import (
        require_h3_provider_english_contract,
        validate_h3_provider_text_boundary,
    )
    from prompt_budget_observability import measure_prompt
    from provider_contract_boundary import validate_provider_prompt_boundary
    from provider_semantic_coverage import build_semantic_coverage_receipt
    from wardrobe_identity_contract import h3_adult_female_visual_block


SCHEMA = "qingshan.minimax_h3_provider_renderer.v2_english_machine_dialogue_tags"
ANTI_TEXT = (
    "TEXT-FREE FRAME: dialogue exists only as synchronized native speech; never render captions, "
    "subtitles, letters, numbers, punctuation, dialogue boxes, labels, signs, UI, logos, or watermarks"
)


def _camera(plan: dict[str, Any]) -> str:
    family = str(plan.get("motion_family") or "STATIC").upper()
    direction = str(plan.get("motion_direction") or "NONE").upper()
    scale = str(plan.get("shot_scale") or "MEDIUM").upper()
    mapping = {
        "STATIC": "locked camera", "LOCKED": "locked camera",
        "DOLLY": "one short dolly move", "PAN": "one short pan",
        "TRUCK": "one short lateral truck", "TRACK": "one short lateral track",
        "TRACKING": "one motivated axial follow",
        "CRANE": "one motivated vertical move", "TILT": "one motivated tilt",
        "ARC": "one motivated arc move",
    }
    optical = []
    if plan.get("lens_mm"):
        optical.append(f"estimated {int(plan['lens_mm'])}mm focal length")
    shutter = {
        "NATURAL_MOTION_CLARITY": "natural real-time motion with clear contours",
        "CRISP_ACTION_DIRECTION": "crisp action direction and readable contact without long trails",
        "DIRECTIONAL_ACTION_BLUR": "slight directional blur only on fast-moving limbs while identities remain clear",
    }.get(str(plan.get("shutter_visual_intent") or ""))
    if shutter:
        optical.append(shutter)
    dof = {
        "DEEP_SPATIAL_READABILITY": "deep enough focus to read subjects, contact path, and spatial relation",
        "BALANCED_SUBJECT_SPACE": "balanced depth of field preserving essential space",
        "CONTROLLED_SUBJECT_SEPARATION": "controlled subject separation without blurring the opponent or key prop",
    }.get(str(plan.get("depth_of_field_intent") or ""))
    if dof:
        optical.append(dof)
    if plan.get("atmosphere_intent"):
        optical.append(f"authorized atmosphere effect only: {plan['atmosphere_intent']}")
    if plan.get("effect_intent"):
        optical.append(f"authorized visual effect only: {plan['effect_intent']}")
    suffix = "; " + "; ".join(optical) if optical else ""
    return f"shot scale={scale}; {mapping.get(family, family)}; direction={direction}; execute the declared move once{suffix}"


def _beat(
    source: dict[str, Any], translated: dict[str, Any], *, dialogue_slot: int | None
) -> tuple[str, dict[str, str]]:
    index = int(source["source_index"])
    prefix = f"BEAT.{index}"
    line = (
        f"[{source['start_seconds']:g}s-{source['end_seconds']:g}s] "
        f"Start from {translated['entry_state']}. Force origin: {translated.get('force_origin') or translated['entry_state']}. "
        f"{translated['primary_action']}"
    )
    interaction_mode = str(source.get("interaction_mode") or "NONE")
    interaction_label = {
        "CONTACT": "physical contact",
        "EVASION": "clear evasion",
        "THREAT_THRESHOLD": "pre-contact threat threshold",
    }.get(interaction_mode, "no person-to-person interaction")
    evidence = {
        f"{prefix}.ENTRY": translated["entry_state"],
        f"{prefix}.ACTION": translated["primary_action"],
        f"{prefix}.FORCE_ORIGIN": translated.get("force_origin") or translated["entry_state"],
        f"{prefix}.INTERACTION_MODE": interaction_label,
        f"{prefix}.EXIT": translated["exit_state"],
    }
    if source.get("contact_time_seconds") is not None:
        contact_time = f"{float(source['contact_time_seconds']):g}s"
        line += f" Interaction mode: {interaction_label}; the interaction point is reached at {contact_time}"
        evidence[f"{prefix}.CONTACT_TIME"] = contact_time
    if source.get("contact_point"):
        line += f" at {translated['contact_point']}"
        evidence[f"{prefix}.CONTACT_POINT"] = translated["contact_point"]
    if source.get("primary_feedback"):
        primary_feedback = translated.get("primary_feedback") or translated.get("force_feedback")
        line += f"; primary feedback: {primary_feedback}"
        evidence[f"{prefix}.PRIMARY_FEEDBACK"] = primary_feedback
    translated_secondary = translated.get("secondary_feedback") or []
    for secondary_index, value in enumerate(translated_secondary, 1):
        line += f"; secondary feedback: {value}"
        evidence[f"{prefix}.SECONDARY_FEEDBACK.{secondary_index}"] = value
    line += f". End at {translated['exit_state']}."
    raw = str(source.get("dialogue") or "").strip()
    if raw:
        _speaker, separator, words = raw.partition("：")
        if not separator or not words.strip() or dialogue_slot is None:
            raise ValueError(f"DIALOGUE_SPEAKER_BINDING_INVALID:{raw}")
        literal = f"<d>[Chinese] {words.strip()}</d>"
        line += (
            f" SPEAKER_{dialogue_slot} opens the mouth in sync and says exactly once {literal}; "
            "all other people keep their mouths closed."
        )
        evidence[f"{prefix}.DIALOGUE"] = literal
    if source.get("microexpression_cue"):
        line += f" Microexpression: {translated['microexpression_cue']}."
        evidence[f"{prefix}.MICROEXPRESSION"] = translated["microexpression_cue"]
    if source.get("body_sync_cue"):
        line += f" Body synchronization: {translated['body_sync_cue']}."
        evidence[f"{prefix}.BODY_SYNC"] = translated["body_sync_cue"]
    if source.get("internal_transition_after"):
        line += f" Then bridge into the next beat: {translated['internal_transition_after']}."
        evidence[f"{prefix}.INTERNAL_TRANSITION_AFTER"] = translated["internal_transition_after"]
    return line, evidence


def render_h3_prompt(unit: dict[str, Any], plan: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    uid = str(plan["unit_id"])
    refs = unit.get("reference_images") or []
    if not refs or len(refs) > 9:
        raise ValueError(f"{uid}:H3_REFERENCE_COUNT_OUT_OF_RANGE:{len(refs)}")
    contract = require_h3_provider_english_contract(unit, plan)
    reference_lines = [
        f"@Image{index}: lock only its assigned identity, wardrobe, prop, location, or result state; do not copy a static pose."
        for index, _ in enumerate(refs, 1)
    ]
    translated_transition = contract.get("transition") or {}
    source_transition = plan.get("transition") or {}
    description: list[str] = []
    clause_evidence = {
        "ANCHOR.IDENTITY_PROP": contract["identity_prop_fact"],
        "ANCHOR.SPACE_WEATHER": contract["space_weather_fact"],
    }
    persistent_state_lock = str(contract.get("persistent_state_lock") or "").strip()
    if persistent_state_lock:
        clause_evidence["CONTINUITY.PERSISTENT_STATE"] = persistent_state_lock
    shot_state_locks = [str(value).strip() for value in contract.get("shot_state_locks") or []]
    for index, value in enumerate(shot_state_locks, 1):
        clause_evidence[f"CONTINUITY.SHOT_STATE.{index}"] = value
    if source_transition.get("incoming"):
        incoming = str(translated_transition.get("incoming") or "").strip()
        if not incoming:
            raise ValueError(f"H3_ENGLISH_CONTRACT_FIELD_MISSING:{uid}:transition.incoming")
        description.append(f"Open directly from the inherited state: {incoming}. Do not reset or replay it.")
        clause_evidence["TRANSITION.INCOMING"] = incoming
    action_beats = (plan.get("action_ir") or {}).get("causal_chains") or plan["beats"]
    dialogue_slot = 0
    for source, translated in zip(action_beats, contract["beats"]):
        slot = None
        if source.get("dialogue"):
            dialogue_slot += 1
            slot = dialogue_slot
        line, evidence = _beat(source, translated, dialogue_slot=slot)
        description.append(line)
        clause_evidence.update(evidence)
    if source_transition.get("outgoing"):
        outgoing = str(translated_transition.get("outgoing") or "").strip()
        if not outgoing:
            raise ValueError(f"H3_ENGLISH_CONTRACT_FIELD_MISSING:{uid}:transition.outgoing")
        description.append(f"End by completing this handoff: {outgoing}. Keep natural micro-motion and the sound tail.")
        clause_evidence["TRANSITION.OUTGOING"] = outgoing

    translated_sounds = contract.get("sounds") or {}
    sound_rows: list[str] = []
    for key in ("ambience", "foley", "action_sound"):
        source_rows = (plan.get("sounds") or {}).get(key) or []
        provider_rows = translated_sounds.get(key) or []
        if len(provider_rows) != len(source_rows):
            raise ValueError(f"H3_ENGLISH_CONTRACT_SOUND_COUNT:{uid}:{key}:{len(provider_rows)}!={len(source_rows)}")
        for index, value in enumerate(provider_rows, 1):
            value = str(value).strip()
            sound_rows.append(value)
            clause_evidence[f"SOUND.{key.upper()}.{index}"] = value

    source_environment = plan.get("environment_motion") or []
    translated_environment = contract.get("environment_motion") or []
    if len(translated_environment) != len(source_environment):
        raise ValueError(
            f"H3_ENGLISH_CONTRACT_ENVIRONMENT_COUNT:{uid}:"
            f"{len(translated_environment)}!={len(source_environment)}"
        )
    environment_rows = [str(value).strip() for value in translated_environment]
    for index, value in enumerate(environment_rows, 1):
        clause_evidence[f"ENVIRONMENT_MOTION.{index}"] = value

    voice_rows = []
    for index, _row in enumerate(plan.get("voice_bindings") or [], 1):
        line = f"SPEAKER_{index} uses @Audio{index} as the registered fixed voice reference"
        voice_rows.append(line)
        clause_evidence[f"VOICE_BINDING.{index}"] = line
    if not any(beat.get("dialogue") for beat in action_beats):
        vocal_rule = "No human speech event; every visible person keeps the mouth closed for the entire clip."
    else:
        vocal_rule = "Only literals inside d-tags may become speech; never vocalize machine metadata."

    camera = _camera(plan.get("camera_plan") or {})
    clause_evidence["CAMERA.PLAN"] = camera
    physical_rules = []
    if plan.get("interaction_topology_required"):
        topology = (
            "Every visible hand has one named owner and remains anatomically connected through shoulder, "
            "upper arm, elbow, forearm, wrist, palm, and fingers; no isolated limb, extra limb, severed limb, "
            "reversed joint, fixed-surface penetration, or owner swap"
        )
        physical_rules.append(topology)
        clause_evidence["PHYSICAL.INTERACTION_TOPOLOGY"] = topology
    if plan.get("combat_execution_required"):
        combat = (
            "Execute each combat beat in real time as setup and displacement, one contact or clear evasion, "
            "force feedback, and a new position; no posing, push-hands contact, or still-frame interpolation"
        )
        physical_rules.append(combat)
        clause_evidence["COMBAT.EXECUTION_RULE"] = combat
    wuxia_profile = plan.get("wuxia_combat_profile_selection") or {}
    if wuxia_profile.get("status") == "SELECTED":
        profile_clause = (
            "Wuxia action-camera profile [INFERRED_RECONSTRUCTED_NOT_ORIGINAL]: "
            + str(wuxia_profile.get("prompt_module_en") or "")
            + " This profile only expresses the existing Action-IR and must not add moves, hits, injuries, "
            "effects, winners, losers, dialogue, or story outcomes"
        )
        physical_rules.append(profile_clause)
        clause_evidence["COMBAT.WUXIA_PROFILE_MODULE"] = profile_clause
    # Run the established explicit-content validator.  The returned Chinese
    # prose is intentionally not serialized; H3 receives an equivalent English
    # model-specific styling clause only for explicitly confirmed adults.
    adult_style_source = h3_adult_female_visual_block(unit)
    adult_style = (
        "For every explicitly confirmed adult woman, use a mature, naturally fuller silhouette with "
        "role-appropriate fitted tailoring, a clear waistline, complete period clothing, and tasteful non-explicit styling"
        if adult_style_source else ""
    )
    negatives = list(contract.get("negative_constraints") or [])
    negatives.extend([
        ANTI_TEXT,
        "No identity, wardrobe, prop ownership, map, weather, lighting-direction, or voice drift",
        "No freeze, loop, pose interpolation, unmotivated orbit, or discontinuous spatial jump",
    ])
    if wuxia_profile.get("status") == "SELECTED":
        negatives.extend(wuxia_profile.get("negative_constraints_en") or [])
    profile = str(unit.get("h3_prompt_profile") or "").strip()
    profile_constraints = {
        "H3_CONCISE_QUOTED_DIALOGUE_REPAIR_V1": "Only the bound named speaker may speak; never add, translate, repeat, or visualize dialogue",
        "H3_MINIMAL_AUDIO_RESCUE_V1": "Repair only the declared native sound; do not rewrite identity, map, action, framing, or timing",
        "H3_ENGLISH_MACHINE_AUDIO_RESCUE_V1": "Never vocalize machine metadata; only tagged source-language dialogue may become speech",
        "H3_CONCISE_COMBAT_REPAIR_V1": "Execute one physical force chain; no push-hands contact, posing, or reference-frame interpolation",
        "H3_OFFICIAL_REF2VA_V1": "References bind only their declared identity, location, prop, and state roles",
    }
    if profile in profile_constraints:
        negatives.append(profile_constraints[profile])
    text = "\n".join([
        "subject_definitions:", *reference_lines,
        f"summary: [reference generation + keyframe completion] {plan['duration_seconds']:g}s vertical 9:16 live-action short drama; {contract['identity_prop_fact']}; {contract['space_weather_fact']}.",
        *( ["persistent_state_lock: " + persistent_state_lock + "."] if persistent_state_lock else [] ),
        *( ["shot_state_chain:", *[f"SHOT_{index}: {value}." for index, value in enumerate(shot_state_locks, 1)]] if shot_state_locks else [] ),
        "retention_analysis: @Image1 locks the opening identity and space; later references bind only their declared identity, prop, or result state.",
        "detailed_description:", *description,
        "camera: " + camera + ".",
        "physical_continuity: " + ("; ".join(physical_rules) or "Preserve continuous body ownership and real physical causality") + ".",
        *( ["adult_woman_style: " + adult_style + "."] if adult_style else [] ),
        "environment_motion: " + ("; ".join(environment_rows) or "Background life moves naturally only when motivated by the story; never freeze into a still image") + ".",
        "overall_soundscape: " + ("; ".join(sound_rows) or "Native location ambience, cloth, foley, action contact, and declared dialogue only") + ".",
        "voice_binding: " + ("; ".join(voice_rows) or "No dialogue voice reference is required") + ".",
        "vocal_rule: " + vocal_rule,
        "non_diegetic_music: none unless the structured audio profile explicitly binds a cue.",
        "negative_constraints: " + "; ".join(dict.fromkeys(value.strip().rstrip(".; ") for value in negatives if value.strip())) + ".",
    ]) + "\n"
    boundary = validate_provider_prompt_boundary(text, source_id=uid, model_family="MINIMAX_H3")
    h3_boundary = validate_h3_provider_text_boundary(text, source_id=uid)
    failures = [*boundary["failures"], *h3_boundary["failures"]]
    if failures:
        raise ValueError(";".join(failures))
    coverage = build_semantic_coverage_receipt(
        plan=plan,
        prompt_text=text,
        model_family="MINIMAX_H3",
        clause_evidence=clause_evidence,
    )
    if coverage["status"] != "PASS":
        raise ValueError(";".join(coverage["failures"]))
    return text, {
        "schema": SCHEMA,
        "status": "PASS",
        "unit_id": uid,
        "model_family": "MINIMAX_H3",
        "h3_prompt_profile": profile or "STANDARD",
        "immutable_contract_sha256": plan["immutable_contract_sha256"],
        "execution_semantics_sha256": plan["execution_semantics_sha256"],
        "camera_language_selection": plan["camera_language_selection"],
        "wuxia_combat_profile_selection": wuxia_profile,
        "motion_density_gate": plan["motion_density_gate"],
        "provider_semantic_coverage_receipt": coverage,
        "provider_boundary": boundary,
        "h3_english_boundary": h3_boundary,
        "prompt_budget": measure_prompt(text, source_id=uid, model_family="MINIMAX_H3"),
    }
