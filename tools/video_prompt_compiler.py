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
        compile_h3_prompt,
        validate_h3_prompt,
        validate_h3_transition_prompt_binding,
    )
except ModuleNotFoundError:
    from compile_grouped_seedance_manifest import (
        prompt_text as compile_seedance_prompt,
        validate_model_prompt as validate_seedance_prompt,
        validate_transition_prompt_binding as validate_seedance_transition,
    )
    from minimax_h3_prompt_compiler import (
        compile_h3_prompt,
        validate_h3_prompt,
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
    return validate_h3_transition_prompt_binding(text, unit)
