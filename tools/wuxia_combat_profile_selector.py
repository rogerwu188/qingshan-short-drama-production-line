#!/usr/bin/env python3
"""Deterministic reference-profile selection over immutable Action-IR.

The profile library is not a story source.  It may only add compact camera and
physical-expression cues that are compatible with facts already present in a
video unit and its compiled Action-IR.
"""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY = ROOT / "configs/WUXIA_COMBAT_PROMPT_PROFILES_V1.json"
SCHEMA = "qingshan.wuxia_combat_profile_selection.v1"


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha_bytes(raw.encode("utf-8"))


@lru_cache(maxsize=2)
def load_library(path: str = str(DEFAULT_LIBRARY)) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    failures: list[str] = []
    if payload.get("schema") != "qingshan.wuxia_combat_prompt_profiles.v1":
        failures.append("WUXIA_PROFILE_LIBRARY_SCHEMA_INVALID")
    if payload.get("status") != "ACTIVE":
        failures.append("WUXIA_PROFILE_LIBRARY_NOT_ACTIVE")
    if (payload.get("reference_lineage") or {}).get("status") != "INFERRED_RECONSTRUCTED_NOT_ORIGINAL":
        failures.append("WUXIA_PROFILE_LIBRARY_DISCLOSURE_MISSING")
    profiles = payload.get("profiles") or []
    ids: set[str] = set()
    for index, row in enumerate(profiles, 1):
        pid = str(row.get("id") or "").strip()
        if not pid or pid in ids:
            failures.append(f"WUXIA_PROFILE_ID_INVALID:{index}")
        ids.add(pid)
        for field in ("layer", "family", "cue_zh", "cue_en"):
            if not str(row.get(field) or "").strip():
                failures.append(f"WUXIA_PROFILE_FIELD_MISSING:{pid or index}:{field}")
        cue_blob = f"{row.get('cue_zh', '')} {row.get('cue_en', '')}".lower()
        if any(token in cue_blob for token in ("copyright", "导演风格：", "dialogue:", "台词：")):
            failures.append(f"WUXIA_PROFILE_UNSAFE_SOURCE_OR_DIALOGUE:{pid or index}")
    if len(profiles) != 34:
        failures.append(f"WUXIA_PROFILE_LIBRARY_COUNT:{len(profiles)}!=34")
    if failures:
        raise ValueError(";".join(failures))
    payload["path"] = str(source)
    payload["sha256"] = _sha_bytes(source.read_bytes())
    payload["by_id"] = {row["id"]: row for row in profiles}
    return payload


def _all_text(unit: dict[str, Any], action_ir: dict[str, Any]) -> str:
    rows: list[str] = []
    for spec in unit.get("ordered_prompt_specs") or []:
        action = spec.get("action") or {}
        rows.extend(str(value or "") for value in (
            action.get("start_state"), action.get("primary_action"),
            action.get("contact_point"), action.get("primary_feedback"),
            action.get("force_feedback"), action.get("completion_state"),
        ))
        rows.extend(str((prop or {}).get("prop") or (prop or {}).get("name") or "") for prop in spec.get("props") or [])
        rows.extend(str((spec.get("space") or {}).get(key) or "") for key in ("location", "subspace"))
        rows.extend(str((spec.get("scene_state") or {}).get(key) or "") for key in ("weather", "time", "palette"))
    for beat in action_ir.get("causal_chains") or []:
        rows.extend(str(beat.get(key) or "") for key in (
            "entry_state", "primary_action", "contact_point", "primary_feedback", "exit_state",
        ))
    return " ".join(rows)


def _cast_count(unit: dict[str, Any]) -> int:
    names = {
        str(row.get("character") or row.get("name") or "").strip()
        for spec in unit.get("ordered_prompt_specs") or []
        for row in spec.get("cast") or []
        if str(row.get("character") or row.get("name") or "").strip()
    }
    return len(names)


def _infer_weapon(text: str) -> str:
    pairs = (
        ("绳镖", "ROPE_DART"), ("双刀", "DUAL_SABER"), ("长枪", "SPEAR"),
        ("枪杆", "SPEAR"), ("长棍", "STAFF"), ("棍", "STAFF"),
        ("短刀", "BLADE"), ("匕首", "BLADE"), ("剑", "SWORD"), ("刀", "SABER"),
    )
    for token, value in pairs:
        if token in text:
            return value
    if any(token in text for token in ("拳", "掌", "腿", "肘", "肩靠", "擒腕", "抓腕")):
        return "UNARMED"
    return "UNKNOWN"


def _environment_tags(text: str) -> set[str]:
    mapping = {
        "RAIN": ("雨", "积水"), "BAMBOO": ("竹",), "WATER": ("水面", "浅水", "河", "湖"),
        "SNOW": ("雪",), "ALLEY": ("巷",), "ROOFTOP": ("屋脊", "屋顶", "瓦面"),
        "WALL": ("墙",), "TABLE": ("桌",), "PILLAR": ("柱",),
        "MOUNTAIN_GATE": ("山门",), "FOG": ("雾",),
    }
    return {tag for tag, tokens in mapping.items() if any(token in text for token in tokens)}


def _interaction_modes(action_ir: dict[str, Any]) -> set[str]:
    modes = {
        str(row.get("interaction_mode") or "NONE").strip().upper()
        for row in action_ir.get("causal_chains") or []
    }
    return modes or {"NONE"}


def _matches(value: str, accepted: list[str]) -> bool:
    return "ANY" in accepted or value in accepted


def _candidate_score(
    row: dict[str, Any], *, unit_class: str, weapon: str, interactions: set[str],
    cast_count: int, environment: set[str], text: str,
) -> tuple[int, list[str], list[str]]:
    reasons: list[str] = []
    rejected: list[str] = []
    if unit_class not in row.get("unit_classes", []):
        rejected.append("UNIT_CLASS_MISMATCH")
    if not (int(row.get("cast_min") or 0) <= cast_count <= int(row.get("cast_max") or 99)):
        rejected.append("CAST_COUNT_MISMATCH")
    weapons = list(row.get("weapon_types") or [])
    if weapon == "UNKNOWN" and row.get("layer") == "PRIMARY_ACTION" and "ANY" not in weapons:
        rejected.append("WEAPON_SIGNAL_UNRESOLVED")
    elif weapon != "UNKNOWN" and not _matches(weapon, weapons):
        rejected.append("WEAPON_MISMATCH")
    row_interactions = set(row.get("interaction_modes") or [])
    if "ANY" not in row_interactions and not interactions.intersection(row_interactions):
        rejected.append("INTERACTION_MISMATCH")
    required_environment = set(row.get("environment_tags") or [])
    if required_environment and not required_environment.intersection(environment):
        rejected.append("ENVIRONMENT_MISMATCH")
    if rejected:
        return -1, reasons, rejected
    score = 10
    reasons.append(f"unit_class={unit_class}")
    if weapon != "UNKNOWN" and _matches(weapon, weapons):
        score += 8
        reasons.append(f"weapon={weapon}")
    if interactions.intersection(row_interactions):
        score += 6
        reasons.append("interaction=" + "+".join(sorted(interactions.intersection(row_interactions))))
    if required_environment.intersection(environment):
        score += 5
        reasons.append("environment=" + "+".join(sorted(required_environment.intersection(environment))))
    token_hits = [token for token in row.get("action_tokens") or [] if token and token in text]
    score += min(8, len(token_hits) * 2)
    if token_hits:
        reasons.append("tokens=" + "+".join(token_hits[:4]))
    return score, reasons, rejected


def select_wuxia_combat_profiles(
    unit: dict[str, Any], *, action_ir: dict[str, Any], unit_class: str,
) -> dict[str, Any]:
    """Select compatible profiles without changing ``unit`` or ``action_ir``."""
    before = _stable_sha({"unit": unit, "action_ir": action_ir})
    library = load_library()
    combat = unit_class in {"COMBAT_IMPULSE", "COMBAT_EXCHANGE"}
    required = bool(unit.get("wuxia_combat_profile_required"))
    if not combat:
        return {
            "schema": SCHEMA, "status": "NOT_APPLICABLE", "required": required,
            "library_version": library["version"], "library_sha256": library["sha256"],
            "selected_profile_ids": [], "selection_reasons": {}, "rejected_candidates": [],
            "prompt_module_zh": "", "prompt_module_en": "", "source_unchanged": True,
        }

    signals = deepcopy(unit.get("wuxia_combat_profile_signals") or {})
    text = _all_text(unit, action_ir)
    weapon = str(signals.get("weapon_type") or _infer_weapon(text)).upper()
    cast_count = int(signals.get("cast_count") or _cast_count(unit))
    environment = {str(value).upper() for value in signals.get("environment_tags") or []} or _environment_tags(text)
    interactions = {str(value).upper() for value in signals.get("interaction_modes") or []} or _interaction_modes(action_ir)
    explicit_ids = [str(value) for value in signals.get("profile_ids") or []]
    fx_authorized = bool(signals.get("authorized_fx"))
    style_authorized = bool(signals.get("authorized_style"))
    selected: list[dict[str, Any]] = []
    reasons: dict[str, list[str]] = {}
    rejected_rows: list[dict[str, Any]] = []

    if explicit_ids:
        for pid in explicit_ids:
            row = library["by_id"].get(pid)
            if not row:
                raise ValueError(f"WUXIA_PROFILE_UNKNOWN:{unit.get('unit_id')}:{pid}")
            if row["layer"] == "AUTHORIZED_FX" and not fx_authorized:
                raise ValueError(f"WUXIA_PROFILE_FX_NOT_AUTHORIZED:{unit.get('unit_id')}:{pid}")
            if row["layer"] == "STYLE" and not style_authorized:
                raise ValueError(f"WUXIA_PROFILE_STYLE_NOT_AUTHORIZED:{unit.get('unit_id')}:{pid}")
            score, why, rejected = _candidate_score(
                row, unit_class=unit_class, weapon=weapon, interactions=interactions,
                cast_count=cast_count, environment=environment, text=text,
            )
            if rejected:
                raise ValueError(f"WUXIA_PROFILE_EXPLICIT_CONFLICT:{unit.get('unit_id')}:{pid}:{'+'.join(rejected)}")
            selected.append(row)
            reasons[pid] = ["EXPLICIT_BINDING", *why]
    else:
        primary_candidates: list[tuple[int, str, dict[str, Any], list[str]]] = []
        for row in library["profiles"]:
            layer = row["layer"]
            if layer not in {"PRIMARY_ACTION", "ENVIRONMENT"}:
                continue
            score, why, rejected = _candidate_score(
                row, unit_class=unit_class, weapon=weapon, interactions=interactions,
                cast_count=cast_count, environment=environment, text=text,
            )
            if rejected:
                rejected_rows.append({"profile_id": row["id"], "reasons": rejected})
                continue
            if layer == "PRIMARY_ACTION":
                primary_candidates.append((score, row["id"], row, why))
            elif set(row.get("environment_tags") or []).intersection(environment):
                selected.append(row)
                reasons[row["id"]] = ["DETERMINISTIC_ENVIRONMENT_MATCH", *why]
        if primary_candidates:
            score, _pid, row, why = sorted(primary_candidates, key=lambda item: (-item[0], item[1]))[0]
            selected.insert(0, row)
            reasons[row["id"]] = [f"DETERMINISTIC_SCORE={score}", *why]

    primary = [row for row in selected if row["layer"] == "PRIMARY_ACTION"]
    if not primary and required:
        raise ValueError(
            f"WUXIA_PRIMARY_PROFILE_UNRESOLVED:{unit.get('unit_id')}:"
            f"weapon={weapon}:cast={cast_count}:interactions={'+'.join(sorted(interactions))}"
        )
    if not primary:
        # An environment, style, or effect supplement cannot stand in for a
        # missing action prototype.  Dropping it avoids producing a cinematic
        # look while silently inventing the actual fight mechanics.
        selected = []
        reasons = {}
    # Keep no more than one environmental supplement.  FX/style layers require
    # explicit profile ids and authorization, so they can never appear through inference.
    compact: list[dict[str, Any]] = []
    seen_layers: set[str] = set()
    for row in selected:
        if row["layer"] in seen_layers:
            continue
        compact.append(row)
        seen_layers.add(row["layer"])
    selected = compact

    negatives_zh = list(library.get("global_negative_constraints_zh") or [])
    negatives_en = list(library.get("global_negative_constraints_en") or [])
    module_zh = "；".join(f"[{row['id']}] {row['cue_zh']}" for row in selected)
    module_en = " ".join(f"[{row['id']}] {row['cue_en']}" for row in selected)
    after = _stable_sha({"unit": unit, "action_ir": action_ir})
    if before != after:
        raise ValueError(f"WUXIA_PROFILE_SELECTOR_MUTATED_SOURCE:{unit.get('unit_id')}")
    status = "SELECTED" if primary else "UNRESOLVED_SHADOW"
    return {
        "schema": SCHEMA,
        "status": status,
        "required": required,
        "library_ref": library["path"],
        "library_version": library["version"],
        "library_sha256": library["sha256"],
        "reference_status": library["reference_lineage"]["status"],
        "signals": {
            "weapon_type": weapon, "cast_count": cast_count,
            "interaction_modes": sorted(interactions), "environment_tags": sorted(environment),
            "authorized_fx": fx_authorized, "authorized_style": style_authorized,
        },
        "selected_profile_ids": [row["id"] for row in selected],
        "selection_reasons": reasons,
        "rejected_candidates": rejected_rows,
        "prompt_module_zh": module_zh,
        "prompt_module_en": module_en,
        "negative_constraints_zh": negatives_zh,
        "negative_constraints_en": negatives_en,
        "source_unchanged": before == after,
        "post_generation_dynamic_action_qa_required": False,
    }


if __name__ == "__main__":
    data = load_library()
    print(json.dumps({
        "schema": data["schema"], "version": data["version"],
        "profile_count": len(data["profiles"]), "sha256": data["sha256"],
    }, ensure_ascii=False))
