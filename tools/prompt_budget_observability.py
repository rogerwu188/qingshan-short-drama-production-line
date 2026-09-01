#!/usr/bin/env python3
"""Measured prompt-size telemetry; budgets are observability, not semantics."""

from __future__ import annotations

from typing import Any


SCHEMA = "qingshan.prompt_budget_observability.v1_shadow_600_900_1200"


def measure_prompt(text: str, *, source_id: str, model_family: str) -> dict[str, Any]:
    count = len(text)
    if count <= 600:
        tier = "TIER_600"
    elif count <= 900:
        tier = "TIER_900"
    elif count <= 1200:
        tier = "TIER_1200"
    else:
        tier = "ABOVE_1200_REVIEW"
    return {
        "schema": SCHEMA,
        "status": "PASS",
        "source_id": source_id,
        "model_family": model_family,
        "character_count": count,
        "shadow_tier": tier,
        "hard_length_rejection": False,
    }
