#!/usr/bin/env python3
"""Shared immutable boundary between production contracts and model prompts.

The full directing contract remains authoritative and machine-readable.  Model
serializers receive a deep copy plus compact execution facts; they must never
mutate the source object or dump internal schema/lineage identifiers into a
provider-facing prompt.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any


POLICY_VERSION = "qingshan.provider_contract_boundary.v1_immutable_no_dump"

IMMUTABLE_UNIT_FIELDS = (
    "unit_id",
    "episode",
    "scene_id",
    "editorial_shot_ids",
    "duration_seconds",
    "source_duration_seconds",
    "authorized_content_seconds",
    "authorized_tail_handle_seconds",
    "model",
    "resolution",
    "aspect_ratio",
    "ordered_prompt_specs",
    "reference_images",
    "camera_plan",
    "wardrobe_contract",
    "speaker_voice_contract",
    "background_ecology_contract",
    "weather_visibility_contract",
    "interaction_topology_contract",
    "combat_choreography_contract",
    "combat_action_library_binding",
    "incoming_transition_contract",
    "outgoing_transition_contract",
    "internal_transition_contracts",
    "native_audio_contract",
    "generation_audio_profile_id",
    "h3_provider_english_contract",
)

FORBIDDEN_PROVIDER_MACHINE_PATTERNS = (
    r"\bsha256\b",
    r"qingshan\.[a-z0-9_.-]+",
    r"GLOBAL-SPACE-",
    r"\bLOC-[A-Z0-9-]+",
    r"\bSUB-[A-Z0-9-]+",
    r"\bPF-[A-Z0-9-]+",
    r"ROLE_LOCK\[",
    r"镜头ID=",
    r"逐实体出入画状态=",
    r"immutable_contract_sha256",
    r"semantic_coverage_receipt",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def structured_contract_projection(unit: dict[str, Any]) -> dict[str, Any]:
    """Return only authoritative structured fields, without provider prose."""
    return {
        field: deepcopy(unit.get(field))
        for field in IMMUTABLE_UNIT_FIELDS
        if field in unit
    }


def structured_contract_sha256(unit: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(structured_contract_projection(unit))).hexdigest()


def begin_provider_compile(unit: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Return an isolated working copy and the immutable source digest."""
    return deepcopy(unit), structured_contract_sha256(unit)


def assert_structured_contract_unchanged(
    unit: dict[str, Any], expected_sha256: str, *, source_id: str | None = None
) -> dict[str, Any]:
    actual = structured_contract_sha256(unit)
    failures = [] if actual == expected_sha256 else [
        f"IMMUTABLE_STRUCTURED_CONTRACT_MUTATED:{source_id or unit.get('unit_id') or 'UNKNOWN'}"
    ]
    return {
        "schema": POLICY_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "source_id": source_id or str(unit.get("unit_id") or "UNKNOWN"),
        "immutable_contract_sha256": expected_sha256,
        "actual_contract_sha256": actual,
        "failures": failures,
    }


def validate_provider_prompt_boundary(
    text: str, *, source_id: str, model_family: str
) -> dict[str, Any]:
    failures: list[str] = []
    for pattern in FORBIDDEN_PROVIDER_MACHINE_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            failures.append(f"PROVIDER_PROMPT_MACHINE_CONTRACT_DUMP:{pattern}")
    return {
        "schema": POLICY_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "source_id": source_id,
        "model_family": model_family,
        "failures": failures,
    }


def unique_text(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip().rstrip("。；")
        if text and text not in result:
            result.append(text)
    return result


def compact_space_weather_fact(unit: dict[str, Any]) -> tuple[str, dict[str, list[str]]]:
    specs = unit.get("ordered_prompt_specs") or []
    locations = unique_text([
        (spec.get("space") or {}).get("location") for spec in specs
    ])
    subspaces = unique_text([
        (spec.get("space") or {}).get("subspace") for spec in specs
    ])
    times = unique_text([
        (spec.get("scene_state") or {}).get("time") for spec in specs
    ])
    weather = unique_text([
        (spec.get("scene_state") or {}).get("weather") for spec in specs
    ])
    palettes = unique_text([
        (spec.get("scene_state") or {}).get("palette") for spec in specs
    ])
    def provider_safe(values: list[str]) -> list[str]:
        return [
            value for value in values
            if not re.match(r"^(?:GLOBAL-SPACE|LOC|SUB)-", value, flags=re.IGNORECASE)
        ]

    pieces = []
    safe_locations = provider_safe(locations)
    safe_subspaces = provider_safe(subspaces)
    if safe_locations or safe_subspaces:
        pieces.append("同一" + "／".join(safe_locations + safe_subspaces) + "内")
    elif locations or subspaces:
        pieces.append("同一随任务参考素材已确认的地图子空间内")
    if times:
        pieces.append("时间=" + "／".join(times))
    if weather:
        pieces.append("天气=" + "／".join(weather))
    if palettes:
        pieces.append("综合色调=" + "／".join(palettes))
    return "；".join(pieces), {
        "location": locations,
        "subspace": subspaces,
        "time": times,
        "weather": weather,
        "palette": palettes,
    }


def compact_identity_prop_fact(unit: dict[str, Any]) -> tuple[str, dict[str, list[str]]]:
    specs = unit.get("ordered_prompt_specs") or []
    cast = unique_text([
        row.get("character")
        for spec in specs
        for row in spec.get("cast") or []
    ])
    props = unique_text([
        row.get("prop")
        for spec in specs
        for row in spec.get("props") or []
    ])
    pieces = []
    if cast:
        pieces.append("人物=" + "、".join(cast))
    if props:
        pieces.append("关键道具=" + "、".join(props))
    pieces.append("使用随任务参考素材锁定具名人物、服装、场景与道具归属")
    return "；".join(pieces), {"cast": cast, "props": props}
