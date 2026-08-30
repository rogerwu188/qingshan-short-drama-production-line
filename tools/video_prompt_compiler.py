#!/usr/bin/env python3
"""Model-aware prompt compiler router for deployed video families."""

from __future__ import annotations

from typing import Any

try:
    from tools.compile_grouped_seedance_manifest import (
        prompt_text as compile_seedance_prompt,
        validate_model_prompt as validate_seedance_prompt,
        validate_transition_prompt_binding as validate_seedance_transition,
    )
    from tools.minimax_h3_prompt_compiler import (
        H3_SPEECH_ISOLATION_REPAIR_PROFILE,
        H3_MINIMAL_AUDIO_RESCUE_PROFILE,
        H3_CONCISE_COMBAT_REPAIR_PROFILE,
        compile_h3_concise_combat_repair_prompt,
        compile_h3_prompt,
        compile_h3_minimal_audio_rescue_prompt,
        compile_h3_speech_isolation_repair_prompt,
        validate_h3_prompt,
        validate_h3_minimal_audio_rescue_prompt,
        validate_h3_concise_combat_repair_prompt,
        validate_h3_speech_isolation_repair_prompt,
        validate_h3_transition_prompt_binding,
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
        H3_CONCISE_COMBAT_REPAIR_PROFILE,
        compile_h3_concise_combat_repair_prompt,
        compile_h3_prompt,
        compile_h3_minimal_audio_rescue_prompt,
        compile_h3_speech_isolation_repair_prompt,
        validate_h3_prompt,
        validate_h3_minimal_audio_rescue_prompt,
        validate_h3_concise_combat_repair_prompt,
        validate_h3_speech_isolation_repair_prompt,
        validate_h3_transition_prompt_binding,
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
    family = model_family(unit.get("model"))
    if family == "seedance2":
        # Deliberately call the established compiler unchanged.
        return compile_seedance_prompt(unit, memory_rules)
    if unit.get("h3_prompt_profile") == H3_SPEECH_ISOLATION_REPAIR_PROFILE:
        return compile_h3_speech_isolation_repair_prompt(unit)
    if unit.get("h3_prompt_profile") == H3_MINIMAL_AUDIO_RESCUE_PROFILE:
        return compile_h3_minimal_audio_rescue_prompt(unit)
    if unit.get("h3_prompt_profile") == H3_CONCISE_COMBAT_REPAIR_PROFILE:
        return compile_h3_concise_combat_repair_prompt(unit)
    return compile_h3_prompt(unit)


def validate_model_prompt_for_model(
    text: str,
    *,
    model: object,
    source_id: str,
    unit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    family = model_family(model)
    if family == "seedance2":
        return validate_seedance_prompt(text, source_id=source_id)
    if unit and unit.get("h3_prompt_profile") == H3_SPEECH_ISOLATION_REPAIR_PROFILE:
        return validate_h3_speech_isolation_repair_prompt(text, source_id=source_id, unit=unit)
    if unit and unit.get("h3_prompt_profile") == H3_MINIMAL_AUDIO_RESCUE_PROFILE:
        return validate_h3_minimal_audio_rescue_prompt(text, source_id=source_id, unit=unit)
    if unit and unit.get("h3_prompt_profile") == H3_CONCISE_COMBAT_REPAIR_PROFILE:
        return validate_h3_concise_combat_repair_prompt(text, source_id=source_id, unit=unit)
    return validate_h3_prompt(text, source_id=source_id, unit=unit)


def validate_transition_prompt_for_model(
    text: str,
    unit: dict[str, Any],
    *,
    model: object,
) -> dict[str, Any]:
    family = model_family(model)
    if family == "seedance2":
        return validate_seedance_transition(text, unit)
    if unit.get("h3_prompt_profile") == H3_SPEECH_ISOLATION_REPAIR_PROFILE:
        report = validate_h3_speech_isolation_repair_prompt(
            text, source_id=str(unit.get("unit_id") or "UNKNOWN"), unit=unit
        )
        return {
            "schema": "qingshan.minimax_h3_repair_transition_prompt_binding.v1",
            "status": report["status"],
            "unit_id": str(unit.get("unit_id") or "UNKNOWN"),
            "failures": report["failures"],
        }
    if unit.get("h3_prompt_profile") == H3_MINIMAL_AUDIO_RESCUE_PROFILE:
        report = validate_h3_minimal_audio_rescue_prompt(
            text, source_id=str(unit.get("unit_id") or "UNKNOWN"), unit=unit
        )
        return {
            "schema": "qingshan.minimax_h3_minimal_rescue_transition_binding.v1",
            "status": report["status"],
            "unit_id": str(unit.get("unit_id") or "UNKNOWN"),
            "failures": report["failures"],
        }
    if unit.get("h3_prompt_profile") == H3_CONCISE_COMBAT_REPAIR_PROFILE:
        report = validate_h3_concise_combat_repair_prompt(
            text, source_id=str(unit.get("unit_id") or "UNKNOWN"), unit=unit
        )
        return {
            "schema": "qingshan.minimax_h3_concise_combat_transition_binding.v1",
            "status": report["status"],
            "unit_id": str(unit.get("unit_id") or "UNKNOWN"),
            "failures": report["failures"],
        }
    return validate_h3_transition_prompt_binding(text, unit)
