#!/usr/bin/env python3
"""Project episode-wide semantics into a provider-visible per-unit allowlist.

The machine contract may retain the complete episode graph. A provider prompt
may not: noun-rich video models can promote any mentioned entity into pixels or
sound. This module makes that boundary explicit and independently auditable.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


SCHEMA = "qingshan.provider_scope_projection.v1"
ACTIVE_FROM_EPISODE = 56
NEGATIVE_HEADERS = ("negative_constraints:", "NEGATIVE_PROMPT:", "【负面", "【限制")


def _positive_prompt(text: str) -> str:
    positions = [text.find(value) for value in NEGATIVE_HEADERS if text.find(value) >= 0]
    return text[: min(positions)] if positions else text


def build_provider_scope_projection(
    *,
    visible_character_ids: list[str],
    visible_prop_ids: list[str],
    episode_character_catalog: list[dict[str, Any]],
    episode_prop_catalog: list[dict[str, Any]] | None = None,
    reference_images: list[dict[str, Any]] | None = None,
    scene_domain: str,
    location_ids: list[str] | None = None,
    environment_terms: list[str] | None = None,
    sound_terms: list[str] | None = None,
) -> dict[str, Any]:
    visible = set(visible_character_ids)
    bindings = []
    for index, row in enumerate(reference_images or [], 1):
        entity_id = str(row.get("entity_id") or "")
        if not entity_id:
            continue
        bindings.append({
            "reference_index": index,
            "entity_id": entity_id,
            "provider_entity_label": str(row.get("provider_entity_label") or entity_id),
            "exclusive_identity_owner": True,
        })
    absent = []
    for row in episode_character_catalog:
        entity_id = str(row.get("character_id") or row.get("entity_id") or "")
        if not entity_id or entity_id in visible:
            continue
        terms = [
            str(row.get("canonical_name") or "").strip(),
            str(row.get("provider_entity_label") or "").strip(),
            *[str(value).strip() for value in row.get("aliases") or []],
        ]
        absent.append({
            "entity_id": entity_id,
            "forbidden_positive_terms": [value for value in dict.fromkeys(terms) if value],
        })
    return {
        "schema": SCHEMA,
        "status": "LOCKED",
        "scene_domain": scene_domain,
        "visible_character_ids": sorted(visible),
        "visible_entity_instance_counts": {entity_id: 1 for entity_id in sorted(visible)},
        "visible_prop_ids": sorted(set(visible_prop_ids)),
        "location_ids": sorted(set(location_ids or [])),
        "environment_terms": list(dict.fromkeys(environment_terms or [])),
        "sound_terms": list(dict.fromkeys(sound_terms or [])),
        "reference_identity_bindings": bindings,
        "absent_episode_entities": absent,
        "episode_prop_catalog": deepcopy(episode_prop_catalog or []),
        "provider_reads_episode_global_contract_directly": False,
    }


def validate_provider_scope_projection(
    payload: dict[str, Any], *, prompt_text: str | None = None, model: str | None = None,
) -> dict[str, Any]:
    projection = payload.get("provider_scope_projection")
    if not isinstance(projection, dict):
        identity = str(payload.get("episode") or payload.get("unit_id") or "").upper()
        match = re.search(r"(?:^|[^A-Z])E(\d+)", identity)
        required = bool(
            match
            and int(match.group(1)) >= ACTIVE_FROM_EPISODE
            and str(model or payload.get("model") or "").strip().lower()
            in {
                "minimax-h3", "h3", "seedance-2.0-pro", "gpt-image-2-pro",
                "sd2", "stable-diffusion-2", "seed", "seed-image",
                "nano-banana", "nanobanana", "nanubanner", "google-nano-banana",
            }
        )
        failures = ["PROVIDER_SCOPE_PROJECTION_MISSING"] if required else []
        return {
            "schema": "qingshan.provider_scope_projection_gate.v1",
            "status": "FAIL" if failures else "NOT_APPLICABLE",
            "required": required,
            "failures": failures,
        }
    failures: list[str] = []
    if projection.get("schema") != SCHEMA:
        failures.append("PROVIDER_SCOPE_SCHEMA_INVALID")
    if projection.get("status") != "LOCKED":
        failures.append("PROVIDER_SCOPE_NOT_LOCKED")
    if projection.get("provider_reads_episode_global_contract_directly") is not False:
        failures.append("PROVIDER_SCOPE_GLOBAL_CONTRACT_ACCESS_NOT_DISABLED")
    visible = [str(value) for value in projection.get("visible_character_ids") or []]
    if len(visible) != len(set(visible)):
        failures.append("PROVIDER_SCOPE_DUPLICATE_VISIBLE_ENTITY")
    counts = projection.get("visible_entity_instance_counts") or {}
    if set(map(str, counts)) != set(visible) or any(counts.get(entity_id) != 1 for entity_id in visible):
        failures.append("PROVIDER_SCOPE_VISIBLE_INSTANCE_CARDINALITY_INVALID")
    bindings = projection.get("reference_identity_bindings") or []
    indices = [row.get("reference_index") for row in bindings]
    entities = [str(row.get("entity_id") or "") for row in bindings]
    if len(indices) != len(set(indices)) or len(entities) != len(set(entities)):
        failures.append("PROVIDER_SCOPE_REFERENCE_BINDING_NOT_ONE_TO_ONE")
    for row in bindings:
        entity_id = str(row.get("entity_id") or "UNKNOWN")
        if row.get("exclusive_identity_owner") is not True:
            failures.append("PROVIDER_SCOPE_REFERENCE_OWNER_NOT_EXCLUSIVE:" + entity_id)
        if entity_id not in visible:
            failures.append("PROVIDER_SCOPE_REFERENCE_ENTITY_NOT_VISIBLE:" + entity_id)
    if prompt_text is not None:
        # H3 promotes concrete nouns even in a negative clause. SD2 keeps its
        # established negative-prompt semantics and is checked only positively.
        searchable = (
            prompt_text.casefold()
            if str(model or payload.get("model") or "").strip().lower() in {"minimax-h3", "h3"}
            else _positive_prompt(prompt_text).casefold()
        )
        for row in projection.get("absent_episode_entities") or []:
            for term in row.get("forbidden_positive_terms") or []:
                token = str(term).strip()
                if len(token) < 2:
                    continue
                if re.search(r"(?<![A-Za-z0-9_-])" + re.escape(token.casefold()) + r"(?![A-Za-z0-9_-])", searchable):
                    failures.append(
                        "PROVIDER_SCOPE_ABSENT_ENTITY_IN_POSITIVE_PROMPT:"
                        + str(row.get("entity_id") or "UNKNOWN") + ":" + token
                    )
        if str(model or payload.get("model") or "").strip().lower() in {"minimax-h3", "h3"}:
            for row in bindings:
                marker = f"@Image{row['reference_index']}:".casefold()
                label = str(row.get("provider_entity_label") or "").casefold()
                if marker not in searchable or not label or label not in searchable:
                    failures.append(
                        "H3_PROVIDER_SCOPE_REFERENCE_MAPPING_MISSING:"
                        + str(row.get("entity_id") or "UNKNOWN")
                    )
                cardinality = f"exactly one visible instance of {label}".casefold()
                if cardinality not in searchable:
                    failures.append(
                        "H3_PROVIDER_SCOPE_INSTANCE_CARDINALITY_MISSING:"
                        + str(row.get("entity_id") or "UNKNOWN")
                    )
    return {
        "schema": "qingshan.provider_scope_projection_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "required": True,
        "failures": failures,
    }
