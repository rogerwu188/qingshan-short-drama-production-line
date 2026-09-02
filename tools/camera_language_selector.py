#!/usr/bin/env python3
"""Deterministic, model-neutral camera-language enrichment.

The selector never authors story state or rewrites director-owned camera
geometry.  In HYBRID mode it only fills concise optical/rendering intent.  The
provider renderers remain responsible for SD2- and H3-specific prose.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "qingshan.camera_language_selection.v1"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs" / "camera_language_profiles.v1.json"
MODES = {"AUTO", "HYBRID", "LOCKED"}
PROTECTED_FIELDS = {
    "shot_scale", "camera_height", "camera_side", "axis_relation",
    "motion_family", "motion_direction", "start_framing", "end_framing",
    "motivation", "lens_intent",
}
OPTIONAL_FIELDS = {
    "lens_mm", "shutter_visual_intent", "depth_of_field_intent",
    "atmosphere_intent", "effect_intent",
}


def _load_profiles(path: Path = CONFIG_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "qingshan.camera_language_profiles.v1":
        raise ValueError("CAMERA_LANGUAGE_PROFILE_SCHEMA_INVALID")
    return payload


def _choose_profile(unit_class: str, profiles: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    matches = [
        (profile_id, profile)
        for profile_id, profile in sorted(profiles.items())
        if unit_class in (profile.get("unit_classes") or [])
    ]
    if len(matches) != 1:
        raise ValueError(f"CAMERA_LANGUAGE_PROFILE_RESOLUTION:{unit_class}:{len(matches)}")
    return matches[0]


def select_camera_language(
    camera_plan: dict[str, Any], *, unit_class: str, unit: dict[str, Any] | None = None,
    source_id: str = "UNKNOWN", config_path: Path = CONFIG_PATH,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return enriched plan and stable receipt without changing protected fields."""
    original = deepcopy(camera_plan or {})
    plan = deepcopy(original)
    unit = unit or {}
    config = _load_profiles(config_path)
    mode = str(plan.get("selection_mode") or unit.get("camera_language_mode") or config["selection_default"]).upper()
    if mode not in MODES:
        raise ValueError(f"{source_id} CAMERA_LANGUAGE_SELECTION_MODE_INVALID:{mode}")
    profile_id, profile = _choose_profile(unit_class, config["profiles"])

    filled: list[str] = []
    if mode != "LOCKED":
        for key in ("lens_mm", "shutter_visual_intent", "depth_of_field_intent"):
            if key not in plan or plan.get(key) in (None, ""):
                plan[key] = deepcopy(profile[key])
                filled.append(key)

        authorizations = unit.get("camera_style_authorizations") or {}
        for key in ("atmosphere_intent", "effect_intent"):
            value = authorizations.get(key)
            if value and (key not in plan or plan.get(key) in (None, "")):
                plan[key] = str(value).strip().upper()
                filled.append(key)

    for key in PROTECTED_FIELDS:
        if original.get(key) != plan.get(key):
            raise ValueError(f"{source_id} CAMERA_LANGUAGE_PROTECTED_FIELD_MUTATION:{key}")
    unknown_additions = set(plan) - set(original) - OPTIONAL_FIELDS - {
        "selection_mode", "camera_profile_id", "camera_language_selector_schema",
    }
    if unknown_additions:
        raise ValueError(f"{source_id} CAMERA_LANGUAGE_UNAUTHORIZED_FIELDS:{sorted(unknown_additions)}")

    plan["selection_mode"] = mode
    plan["camera_profile_id"] = profile_id
    plan["camera_language_selector_schema"] = SCHEMA
    projection = {
        "schema": SCHEMA,
        "source_id": source_id,
        "mode": mode,
        "unit_class": unit_class,
        "profile_id": profile_id,
        "filled_fields": filled,
        "protected_fields_preserved": sorted(PROTECTED_FIELDS),
        "authorized_style_fields": sorted(
            key for key in ("atmosphere_intent", "effect_intent") if key in plan
        ),
    }
    projection["selection_sha256"] = hashlib.sha256(json.dumps(
        {"camera_plan": plan, "receipt": projection},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return plan, projection
