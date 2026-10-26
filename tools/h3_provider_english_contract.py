#!/usr/bin/env python3
"""Validate H3's English-only machine-instruction projection.

MiniMax H3 receives English machine metadata.  Chinese is permitted only in
literal dialogue inside ``<d>[Chinese]...</d>`` (English-dialogue episodes tag
their literals ``<d>[English]...</d>``).  The English projection is a
translation layer over the immutable shared execution plan; it never replaces
or mutates the Chinese directing contract used by SD2.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


SCHEMA = "qingshan.h3_provider_english_contract.v1_source_sha_bound"
CJK = re.compile(r"[\u3400-\u9fff]")
DIALOGUE_TAG = re.compile(r"<d>\[(?:Chinese|English)\]\s*(.*?)</d>", re.DOTALL)
QUOTED_CJK = re.compile(r"(?:\"[^\"\n]*[\u3400-\u9fff][^\"\n]*\"|[“”「」『』][^\n]*[\u3400-\u9fff])")

#: The only Chinese allowed outside the dialogue tags: the MiniMax-H3 provider expert's constraint sentences,
#: verbatim, rendered when a CAMERA_GRAMMAR_V1 unit opts in with ``h3_constraint_language: "zh"`` (owner-approved
#: Chinese-vs-English A/B, 2026-10-26).  Everything else in an H3 prompt stays English; any other CJK still fails.
H3_CONSTRAINT_ZH = {
    "one_take": "全程一镜到底，中间不要出现切镜或拼接",
    "fixed_camera": "机位固定，不推、不拉、不摇、不移",
    "silent": "本段没有任何对白、画外音、旁白或人声，人物都不说话。",
    "only_this_line": "只说这一句台词，只说一次；台词前后没有任何其他对白、画外音、旁白或人声。",
    "only_these_lines": "只说以下这几句台词，每句只说一次，按顺序；台词前后和之间没有任何其他对白、画外音、旁白或人声。",
    "no_duplicate": ("视频全程禁止出现外形、着装、配饰完全一致的人物，禁止生成同款分身、双胞胎效果，"
                     "同一画面中仅保留单个对应人物，不出现人物重复复刻。"),
}
H3_CONSTRAINT_LANGUAGE_FIELD = "h3_constraint_language"


def h3_constraint_language(payload: dict[str, Any] | None) -> str:
    """"zh" when a unit/contract opts into Chinese constraint sentences, else "en" (the default)."""
    value = str((payload or {}).get(H3_CONSTRAINT_LANGUAGE_FIELD) or "").strip().lower()
    return "zh" if value in {"zh", "zh-cn", "chinese"} else "en"


def _outside_allowed_text(text: str) -> str:
    outside = DIALOGUE_TAG.sub("", text)
    for phrase in sorted(H3_CONSTRAINT_ZH.values(), key=len, reverse=True):
        outside = outside.replace(phrase, "")
    return outside


def validate_h3_provider_text_boundary(text: str, *, source_id: str) -> dict[str, Any]:
    failures: list[str] = []
    outside = _outside_allowed_text(text)
    if CJK.search(outside):
        failures.append(f"H3_CJK_OUTSIDE_DIALOGUE:{source_id}")
    # quoted Chinese is only forbidden OUTSIDE the dialogue tags: a line like 「好，走吧。」 or a book-title
    # quote inside <d>[Chinese]...</d> is the permitted dialogue itself (401122 《新石头记》 E13, 2026-10-16)
    if QUOTED_CJK.search(outside):
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
    if plan.get("persistent_state_contract"):
        value = str(contract.get("persistent_state_lock") or "").strip()
        if not value:
            failures.append(f"H3_ENGLISH_CONTRACT_FIELD_MISSING:{uid}:persistent_state_lock")
        elif CJK.search(value):
            failures.append(f"H3_ENGLISH_CONTRACT_CJK:{uid}:persistent_state_lock")
    source_shot_states = plan.get("shot_state_contracts") or []
    translated_shot_states = contract.get("shot_state_locks") or []
    if len(translated_shot_states) != len(source_shot_states):
        failures.append(
            f"H3_ENGLISH_CONTRACT_SHOT_STATE_COUNT:{uid}:"
            f"{len(translated_shot_states)}!={len(source_shot_states)}"
        )
    for index, value in enumerate(translated_shot_states):
        if not str(value or "").strip():
            failures.append(f"H3_ENGLISH_CONTRACT_SHOT_STATE_MISSING:{uid}:{index + 1}")
        elif CJK.search(str(value)):
            failures.append(f"H3_ENGLISH_CONTRACT_CJK:{uid}:shot_state_locks[{index}]")
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
        source_secondary = source.get("secondary_feedback") or []
        translated_secondary = row.get("secondary_feedback") or []
        if len(translated_secondary) != len(source_secondary):
            failures.append(
                f"H3_ENGLISH_CONTRACT_SECONDARY_FEEDBACK_COUNT:{uid}:{index + 1}:"
                f"{len(translated_secondary)}!={len(source_secondary)}"
            )
        for key, value in row.items():
            if isinstance(value, str) and CJK.search(value):
                failures.append(f"H3_ENGLISH_CONTRACT_CJK:{uid}:beats[{index}].{key}")
    source_spatial = [
        role for role in (plan.get("role_bindings") or []) if role.get("spatial_dialogue")
    ]
    if source_spatial:
        translated_spatial = contract.get("spatial_dialogue") or []
        if len(translated_spatial) != len(source_spatial):
            failures.append(
                f"H3_ENGLISH_CONTRACT_SPATIAL_COUNT:{uid}:"
                f"{len(translated_spatial)}!={len(source_spatial)}"
            )
        for index, row in enumerate(translated_spatial):
            if not isinstance(row, dict):
                failures.append(f"H3_ENGLISH_CONTRACT_SPATIAL_INVALID:{uid}:{index + 1}")
                continue
            for key, value in row.items():
                if isinstance(value, str) and CJK.search(value):
                    failures.append(
                        f"H3_ENGLISH_CONTRACT_CJK:{uid}:spatial_dialogue[{index}].{key}"
                    )
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
