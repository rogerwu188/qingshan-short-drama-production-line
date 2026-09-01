#!/usr/bin/env python3
"""Validate H3's English-only machine-instruction projection.

MiniMax H3 receives English machine metadata.  Chinese is permitted only in
literal dialogue inside ``<d>[Chinese]...</d>``.  The English projection is a
translation layer over the immutable shared execution plan; it never replaces
or mutates the Chinese directing contract used by SD2.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


SCHEMA = "qingshan.h3_provider_english_contract.v1_source_sha_bound"
CJK = re.compile(r"[\u3400-\u9fff]")
DIALOGUE_TAG = re.compile(r"<d>\[Chinese\]\s*(.*?)</d>", re.DOTALL)
QUOTED_CJK = re.compile(r"(?:\"[^\"\n]*[\u3400-\u9fff][^\"\n]*\"|[“”「」『』][^\n]*[\u3400-\u9fff])")


def validate_h3_provider_text_boundary(text: str, *, source_id: str) -> dict[str, Any]:
    failures: list[str] = []
    outside = DIALOGUE_TAG.sub("", text)
    if CJK.search(outside):
        failures.append(f"H3_CJK_OUTSIDE_DIALOGUE:{source_id}")
    if QUOTED_CJK.search(text):
        failures.append(f"H3_QUOTED_CJK_FORBIDDEN:{source_id}")
    return {
        "schema": SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "source_id": source_id,
        "cjk_outside_dialogue_count": len(CJK.findall(outside)),
        "failures": failures,
    }


def require_h3_provider_english_contract(
    unit: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    uid = str(plan.get("unit_id") or "UNKNOWN")
    contract = deepcopy(unit.get("h3_provider_english_contract") or {})
    failures: list[str] = []
    if contract.get("schema") != SCHEMA:
        failures.append(f"H3_ENGLISH_CONTRACT_SCHEMA:{uid}")
    if contract.get("source_execution_semantics_sha256") != plan.get("execution_semantics_sha256"):
        failures.append(f"H3_ENGLISH_CONTRACT_SOURCE_SHA_MISMATCH:{uid}")
    for key in ("identity_prop_fact", "space_weather_fact"):
        value = str(contract.get(key) or "").strip()
        if not value:
            failures.append(f"H3_ENGLISH_CONTRACT_FIELD_MISSING:{uid}:{key}")
        elif CJK.search(value):
            failures.append(f"H3_ENGLISH_CONTRACT_CJK:{uid}:{key}")
    source_beats = plan.get("beats") or []
    translated_beats = contract.get("beats") or []
    if len(translated_beats) != len(source_beats):
        failures.append(
            f"H3_ENGLISH_CONTRACT_BEAT_COUNT:{uid}:{len(translated_beats)}!={len(source_beats)}"
        )
    required = ("entry_state", "primary_action", "exit_state")
    optional_if_source = (
        "contact_point", "force_feedback", "microexpression_cue", "body_sync_cue",
        "internal_transition_after",
    )
    for index, source in enumerate(source_beats):
        row = translated_beats[index] if index < len(translated_beats) else {}
        for key in required:
            if not str(row.get(key) or "").strip():
                failures.append(f"H3_ENGLISH_CONTRACT_BEAT_FIELD_MISSING:{uid}:{index + 1}:{key}")
        for key in optional_if_source:
            if source.get(key) and not str(row.get(key) or "").strip():
                failures.append(f"H3_ENGLISH_CONTRACT_BEAT_FIELD_MISSING:{uid}:{index + 1}:{key}")
        for key, value in row.items():
            if isinstance(value, str) and CJK.search(value):
                failures.append(f"H3_ENGLISH_CONTRACT_CJK:{uid}:beats[{index}].{key}")
    for section in ("sounds", "environment_motion", "negative_constraints", "transition"):
        value = contract.get(section)
        if value is None:
            continue
        strings: list[str] = []
        if isinstance(value, dict):
            for child in value.values():
                strings.extend(child if isinstance(child, list) else [child])
        elif isinstance(value, list):
            strings.extend(value)
        else:
            strings.append(value)
        if any(CJK.search(str(row or "")) for row in strings):
            failures.append(f"H3_ENGLISH_CONTRACT_CJK:{uid}:{section}")
    if failures:
        raise ValueError(";".join(failures))
    return contract


def bind_h3_provider_english_contract(
    unit: dict[str, Any], translated_fields: dict[str, Any]
) -> dict[str, Any]:
    """Bind an authored English translation to the current shared semantics.

    This helper is intended for the writer/director build stage.  It computes
    the source SHA locally; provider submission still revalidates that binding.
    """
    try:
        from tools.video_execution_plan_compiler import compile_video_execution_plan
    except ModuleNotFoundError:
        from video_execution_plan_compiler import compile_video_execution_plan
    probe = deepcopy(unit)
    probe.pop("h3_provider_english_contract", None)
    plan = compile_video_execution_plan(probe)
    contract = deepcopy(translated_fields)
    contract["schema"] = SCHEMA
    contract["source_execution_semantics_sha256"] = plan["execution_semantics_sha256"]
    unit["h3_provider_english_contract"] = contract
    return unit
