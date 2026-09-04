#!/usr/bin/env python3
"""Model-aware prompt compiler router for deployed video families."""

from __future__ import annotations

from typing import Any

try:
    from tools.h3_provider_prompt_renderer import render_h3_prompt
    from tools.h3_provider_english_contract import validate_h3_provider_text_boundary
    from tools.provider_contract_boundary import (
        assert_structured_contract_unchanged,
        begin_provider_compile,
        validate_provider_prompt_boundary,
    )
    from tools.sd2_provider_prompt_renderer import render_sd2_prompt
    from tools.video_execution_plan_compiler import compile_video_execution_plan
    from tools.role_semantic_prompt_gate import validate_role_semantics_structure
    from tools.speaker_voice_contract import validate_speaker_voice_contract
    from tools.visual_culture_contract import validate_visual_culture_contract
    from tools.character_entity_contract import validate_character_entity_contract
    from tools.provider_scope_projection import validate_provider_scope_projection
except ModuleNotFoundError:
    from h3_provider_prompt_renderer import render_h3_prompt
    from h3_provider_english_contract import validate_h3_provider_text_boundary
    from provider_contract_boundary import (
        assert_structured_contract_unchanged,
        begin_provider_compile,
        validate_provider_prompt_boundary,
    )
    from sd2_provider_prompt_renderer import render_sd2_prompt
    from video_execution_plan_compiler import compile_video_execution_plan
    from role_semantic_prompt_gate import validate_role_semantics_structure
    from speaker_voice_contract import validate_speaker_voice_contract
    from visual_culture_contract import validate_visual_culture_contract
    from character_entity_contract import validate_character_entity_contract
    from provider_scope_projection import validate_provider_scope_projection

try:
    from tools.compile_grouped_seedance_manifest import (
        prompt_text as compile_seedance_prompt,
        validate_model_prompt as validate_seedance_prompt,
        validate_transition_prompt_binding as validate_seedance_transition,
    )
    from tools.minimax_h3_prompt_compiler import (
        H3_SPEECH_ISOLATION_REPAIR_PROFILE,
        H3_MINIMAL_AUDIO_RESCUE_PROFILE,
        H3_ENGLISH_MACHINE_AUDIO_RESCUE_PROFILE,
        H3_CONCISE_COMBAT_REPAIR_PROFILE,
        compile_h3_concise_combat_repair_prompt,
        compile_h3_prompt,
        compile_h3_minimal_audio_rescue_prompt,
        compile_h3_english_machine_audio_rescue_prompt,
        compile_h3_speech_isolation_repair_prompt,
        validate_h3_prompt,
        validate_h3_minimal_audio_rescue_prompt,
        validate_h3_english_machine_audio_rescue_prompt,
        validate_h3_concise_combat_repair_prompt,
        validate_h3_speech_isolation_repair_prompt,
        validate_h3_transition_prompt_binding,
    )
    from tools.minimax_h3_ref2va_prompt_compiler import (
        H3_OFFICIAL_REF2VA_PROFILE,
        compile_h3_official_ref2va_prompt,
        validate_h3_official_ref2va_prompt,
    )
except ModuleNotFoundError:
    from compile_grouped_seedance_manifest import (
        prompt_text as compile_seedance_prompt,
        validate_model_prompt as validate_seedance_prompt,
        validate_transition_prompt_binding as validate_seedance_transition,
    )
    from minimax_h3_prompt_compiler import (
        H3_SPEECH_ISOLATION_REPAIR_PROFILE,
        H3_MINIMAL_AUDIO_RESCUE_PROFILE,
        H3_ENGLISH_MACHINE_AUDIO_RESCUE_PROFILE,
        H3_CONCISE_COMBAT_REPAIR_PROFILE,
        compile_h3_concise_combat_repair_prompt,
        compile_h3_prompt,
        compile_h3_minimal_audio_rescue_prompt,
        compile_h3_english_machine_audio_rescue_prompt,
        compile_h3_speech_isolation_repair_prompt,
        validate_h3_prompt,
        validate_h3_minimal_audio_rescue_prompt,
        validate_h3_english_machine_audio_rescue_prompt,
        validate_h3_concise_combat_repair_prompt,
        validate_h3_speech_isolation_repair_prompt,
        validate_h3_transition_prompt_binding,
    )
    from minimax_h3_ref2va_prompt_compiler import (
        H3_OFFICIAL_REF2VA_PROFILE,
        compile_h3_official_ref2va_prompt,
        validate_h3_official_ref2va_prompt,
    )


SEEDANCE_MODELS = {"seedance-2.0-pro"}
H3_MODELS = {"minimax-h3", "h3"}


def model_family(model: object) -> str:
    value = str(model or "").strip().lower()
    if value in SEEDANCE_MODELS:
        return "seedance2"
    if value in H3_MODELS:
        return "minimax-h3"
    raise ValueError(f"No prompt compiler registered for video model: {model}")


def compile_model_prompt(
    unit: dict[str, Any],
    memory_rules: list[dict[str, Any]] | None = None,
) -> str:
    # Both families consume one validated execution plan.  Only provider
    # grammar differs.  Compile on a copy and prove the authoritative contract
    # was not mutated by enrichment or serialization.
    family = model_family(unit.get("model"))
    working, source_sha = begin_provider_compile(unit)
    visual_culture = validate_visual_culture_contract(working)
    if visual_culture["status"] != "PASS":
        raise ValueError(";".join(visual_culture["failures"]))
    identity = validate_character_entity_contract(working)
    if identity["status"] != "PASS":
        raise ValueError(";".join(identity["failures"]))
    role_failures = validate_role_semantics_structure(working)
    if role_failures:
        raise ValueError(";".join(role_failures))
    if any(str(spec.get("dialogue") or "").strip() for spec in working.get("ordered_prompt_specs") or []):
        voice = validate_speaker_voice_contract(working)
        if voice["status"] != "PASS":
            raise ValueError(";".join(voice["failures"]))
    plan = compile_video_execution_plan(working)
    if family == "seedance2":
        text, receipt = render_sd2_prompt(working, plan)
    else:
        text, receipt = render_h3_prompt(working, plan)
    immutability = assert_structured_contract_unchanged(
        unit, source_sha, source_id=str(unit.get("unit_id") or "UNKNOWN")
    )
    if immutability["status"] != "PASS":
        raise ValueError(";".join(immutability["failures"]))
    unit_id = str(unit.get("unit_id") or "UNKNOWN")
    COMPILE_RECEIPTS[unit_id] = {**receipt, "immutability": immutability}
    return text


COMPILE_RECEIPTS: dict[str, dict[str, Any]] = {}


def compile_receipt(source_id: str) -> dict[str, Any] | None:
    """Return the last semantic/provider receipt without serializing it."""
    return COMPILE_RECEIPTS.get(str(source_id))


def validate_model_prompt_for_model(
    text: str,
    *,
    model: object,
    source_id: str,
    unit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    family = model_family(model)
    failures: list[str] = []
    required = (
        ("【任务】", "【锚点】", "【时间轴】", "【摄影】", "【声音】", "【限制】")
        if family == "seedance2"
        else ("subject_definitions:", "summary:", "retention_analysis:",
              "detailed_description:", "camera:", "overall_soundscape:",
              "non_diegetic_music:", "negative_constraints:", "TEXT-FREE FRAME")
    )
    failures.extend(
        f"PROVIDER_PROMPT_REQUIRED_SECTION_MISSING:{source_id}:{marker}"
        for marker in required if marker not in text
    )
    # Giggle's OmniVideo endpoint enforces an inclusive 10,000-rune limit.
    # Check the exact rendered payload so preflight cannot approve a request
    # that the provider will reject before creating a task.
    prompt_runes = len(text)
    if prompt_runes > 10_000:
        failures.append(
            f"PROVIDER_PROMPT_RUNE_LIMIT_EXCEEDED:{source_id}:{prompt_runes}>10000"
        )
    boundary = validate_provider_prompt_boundary(
        text,
        source_id=source_id,
        model_family="SEEDANCE_2" if family == "seedance2" else "MINIMAX_H3",
    )
    failures.extend(boundary["failures"])
    if unit is not None:
        visual_culture = validate_visual_culture_contract(unit, prompt_text=text)
        failures.extend(visual_culture["failures"])
        scope = validate_provider_scope_projection(unit, prompt_text=text, model=str(model or ""))
        failures.extend(scope["failures"])
    if family == "minimax-h3":
        failures.extend(
            validate_h3_provider_text_boundary(text, source_id=source_id)["failures"]
        )
    receipt = COMPILE_RECEIPTS.get(source_id)
    if unit is not None:
        receipt = receipt or COMPILE_RECEIPTS.get(str(unit.get("unit_id") or ""))
        if not receipt:
            failures.append(f"SEMANTIC_COVERAGE_RECEIPT_MISSING:{source_id}")
    if receipt:
        coverage = receipt.get("provider_semantic_coverage_receipt") or {}
        if coverage.get("status") != "PASS":
            failures.append(f"SEMANTIC_COVERAGE_RECEIPT_NOT_PASS:{source_id}")
    return {
        "schema": "qingshan.provider_prompt_validation.v2_shared_semantics_model_native_renderers",
        "status": "PASS" if not failures else "FAIL",
        "source_id": source_id,
        "model_family": family,
        "prompt_runes": prompt_runes,
        "maximum_prompt_runes": 10_000,
        "semantic_receipt": receipt,
        "failures": failures,
    }


def validate_transition_prompt_for_model(
    text: str,
    unit: dict[str, Any],
    *,
    model: object,
) -> dict[str, Any]:
    uid = str(unit.get("unit_id") or "UNKNOWN")
    transition = (COMPILE_RECEIPTS.get(uid) or {}).get("motion_density_gate")
    failures = [] if transition else [f"TRANSITION_EXECUTION_RECEIPT_MISSING:{uid}"]
    return {
        "schema": "qingshan.transition_prompt_binding.v2_structured_receipt",
        "status": "PASS" if not failures else "FAIL",
        "unit_id": uid,
        "model_family": model_family(model),
        "failures": failures,
    }
