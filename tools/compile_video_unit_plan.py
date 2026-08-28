#!/usr/bin/env python3
"""Compile scene-local contiguous script shots into video generation units."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from tools.grouped_camera_contract import validate_camera_plan, validate_camera_sequence
    from tools.grouped_transition_contract import validate_transition_sequence
except ModuleNotFoundError:  # Direct CLI execution from tools/.
    from grouped_camera_contract import validate_camera_plan, validate_camera_sequence
    from grouped_transition_contract import validate_transition_sequence


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_FORMULA_KEYS = {
    "target_video_unit_count",
    "target_unit_count",
    "estimated_video_unit_count",
    "average_unit_duration_seconds",
    "average_video_unit_duration_seconds",
    "runtime_divisor_seconds",
    "unit_count_formula",
}


def resolve(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(resolve(path).read_text(encoding="utf-8"))


def sha256(path: str | Path) -> str:
    return hashlib.sha256(resolve(path).read_bytes()).hexdigest()


def duplicate_values(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    return round(float(value), 6)


def find_forbidden_formula_keys(value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if key in FORBIDDEN_FORMULA_KEYS:
                found.append(path)
            found.extend(find_forbidden_formula_keys(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_forbidden_formula_keys(child, f"{prefix}[{index}]"))
    return found


def compile_grouping_spec(production: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Derive all unit counts and durations from explicit semantic shot groups."""
    forbidden = find_forbidden_formula_keys(spec)
    if forbidden:
        raise ValueError(f"unit-count or average-duration formula fields are forbidden: {forbidden}")

    episode = production.get("episode")
    script_sha = production.get("source", {}).get("script_sha256")
    if spec.get("episode") != episode:
        raise ValueError("grouping spec episode mismatch")
    if spec.get("source_script_sha256") != script_sha:
        raise ValueError("grouping spec script SHA mismatch")

    shots = production.get("shots") or []
    expected_shot_ids = [shot.get("shot_id") for shot in shots]
    if None in expected_shot_ids or duplicate_values(expected_shot_ids):
        raise ValueError("production manifest has invalid shot IDs")
    shot_by_id = {shot["shot_id"]: shot for shot in shots}

    duration_policy = spec.get("duration_policy_seconds") or {"minimum": 3, "maximum": 12}
    preferred_policy = spec.get("preferred_duration_seconds") or {"minimum": 5, "maximum": 8}
    minimum = _number(duration_policy.get("minimum", 3), "duration minimum")
    maximum = _number(duration_policy.get("maximum", 12), "duration maximum")
    preferred_minimum = _number(preferred_policy.get("minimum", 5), "preferred minimum")
    preferred_maximum = _number(preferred_policy.get("maximum", 8), "preferred maximum")
    if not 0 < minimum <= preferred_minimum <= preferred_maximum <= maximum:
        raise ValueError("duration policy must satisfy 0 < hard min <= preferred min <= preferred max <= hard max")

    groups = spec.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("grouping spec must contain semantic groups")

    units: list[dict[str, Any]] = []
    assigned_shots: list[str] = []
    unit_ids: list[str] = []
    for index, group in enumerate(groups, start=1):
        unit_id = group.get("unit_id")
        shot_ids = group.get("editorial_shot_ids")
        narrative_beat = group.get("narrative_beat")
        if not isinstance(unit_id, str) or not unit_id.strip():
            raise ValueError(f"group {index} is missing unit_id")
        if not isinstance(narrative_beat, str) or not narrative_beat.strip():
            raise ValueError(f"{unit_id} is missing narrative_beat")
        if not isinstance(shot_ids, list) or not shot_ids or any(not isinstance(value, str) for value in shot_ids):
            raise ValueError(f"{unit_id} must contain editorial_shot_ids")
        unknown = sorted(set(shot_ids) - set(shot_by_id))
        if unknown:
            raise ValueError(f"{unit_id} contains unknown shots: {unknown}")

        scene_ids = {shot_by_id[shot_id].get("scene_id") for shot_id in shot_ids}
        if len(scene_ids) != 1:
            raise ValueError(f"{unit_id} crosses scene boundaries")
        duration = round(sum(
            _number(shot_by_id[shot_id]["duration_seconds"], f"{shot_id} duration_seconds")
            for shot_id in shot_ids
        ), 6)
        if not minimum <= duration <= maximum:
            raise ValueError(f"{unit_id} duration {duration} is outside {minimum}-{maximum} seconds")
        exception_reason = group.get("duration_exception_reason")
        if not preferred_minimum <= duration <= preferred_maximum and not exception_reason:
            raise ValueError(f"{unit_id} needs a preferred-duration exception reason")

        camera_plan = validate_camera_plan(group.get("camera_plan"), source_id=unit_id)
        unit = {
            "unit_id": unit_id,
            "scene_id": next(iter(scene_ids)),
            "duration_seconds": duration,
            "action_unit": bool(group.get("action_unit")),
            "narrative_beat": narrative_beat.strip(),
            "editorial_shot_ids": shot_ids,
            "camera_plan": camera_plan,
            "transition_contract": group.get("transition_contract"),
            # Preserve director-authored beat-to-beat continuity. The semantic
            # compiler validates exact cast/scene/prop/sound/action bindings
            # after editorial prompt specs are attached.
            "internal_transition_contracts": group.get("internal_transition_contracts") or [],
        }
        if exception_reason:
            unit["duration_exception_reason"] = exception_reason
        units.append(unit)
        unit_ids.append(unit_id)
        assigned_shots.extend(shot_ids)

    validate_camera_sequence(units)

    if duplicate_values(unit_ids):
        raise ValueError(f"duplicate unit IDs: {duplicate_values(unit_ids)}")
    if assigned_shots != expected_shot_ids:
        missing = sorted(set(expected_shot_ids) - set(assigned_shots))
        unknown = sorted(set(assigned_shots) - set(expected_shot_ids))
        duplicates = duplicate_values(assigned_shots)
        raise ValueError(
            "groups must cover every editorial shot exactly once in source order; "
            f"missing={missing} unknown={unknown} duplicates={duplicates}"
        )

    runtime_seconds = round(sum(unit["duration_seconds"] for unit in units), 6)
    production_runtime = _number(production.get("runtime_seconds"), "production runtime_seconds")
    if abs(runtime_seconds - production_runtime) > 0.001:
        raise ValueError("compiled unit runtime does not equal production runtime")

    short_exception_count = sum(
        1 for unit in units if unit["duration_seconds"] < preferred_minimum
    )
    if len(shots) >= 12 and len(units) == len(shots):
        raise ValueError("editorial shots may not map one-to-one to video units; semantic grouping is required")
    if len(units) >= 8 and short_exception_count / len(units) > 0.25:
        raise ValueError("too many sub-preferred video units; regroup continuous editorial beats")

    validate_transition_sequence(units)

    return {
        "schema": "qingshan.video_unit_grouping_plan.v2_transition_contract",
        "episode": episode,
        "source_script_sha256": script_sha,
        "editorial_shot_count": len(shots),
        "video_unit_count": len(units),
        "runtime_seconds": runtime_seconds,
        "average_video_unit_duration_seconds": round(runtime_seconds / len(units), 3),
        "short_exception_count": short_exception_count,
        "derivation": {
            "method": "SCENE_LOCAL_CONTIGUOUS_NARRATIVE_GROUPING_FIRST",
            "unit_count_selected_in_advance": False,
            "formula_division_used": False,
            "unit_count_source": "LEN_OF_VALIDATED_SEMANTIC_GROUPS",
            "no_cross_scene_units": True,
            "no_editorial_shot_split": True,
            "unit_duration_equals_editorial_shot_sum": True,
        },
        "duration_policy_seconds": {
            "minimum": minimum,
            "maximum": maximum,
            "authority": duration_policy.get("authority", "SCRIPT_SHOT_DURATION"),
        },
        "preferred_duration_seconds": {
            "minimum": preferred_minimum,
            "maximum": preferred_maximum,
            "exceptions": preferred_policy.get("exceptions"),
        },
        "grouping_spec_sha256": spec.get("grouping_spec_sha256"),
        "units": units,
    }


def validate_compiled_plan(production: dict[str, Any], plan: dict[str, Any]) -> None:
    """Fail closed when a precompiled plan no longer matches its source manifest."""
    groups = []
    for unit in plan.get("units") or []:
        groups.append({
            "unit_id": unit.get("unit_id"),
            "editorial_shot_ids": unit.get("editorial_shot_ids"),
            "action_unit": unit.get("action_unit"),
            "narrative_beat": unit.get("narrative_beat") or "Legacy compiled semantic group",
            "camera_plan": unit.get("camera_plan"),
            "transition_contract": unit.get("transition_contract"),
            "internal_transition_contracts": unit.get("internal_transition_contracts") or [],
            "duration_exception_reason": unit.get("duration_exception_reason"),
        })
    spec = {
        "episode": plan.get("episode"),
        "source_script_sha256": plan.get("source_script_sha256"),
        "duration_policy_seconds": plan.get("duration_policy_seconds"),
        "preferred_duration_seconds": plan.get("preferred_duration_seconds"),
        "groups": groups,
    }
    compiled = compile_grouping_spec(production, spec)
    if plan.get("video_unit_count") != compiled["video_unit_count"]:
        raise ValueError("compiled plan video_unit_count is not the natural group count")
    if plan.get("editorial_shot_count") != compiled["editorial_shot_count"]:
        raise ValueError("compiled plan editorial_shot_count mismatch")
    if plan.get("runtime_seconds") != compiled["runtime_seconds"]:
        raise ValueError("compiled plan runtime mismatch")
    for declared, derived in zip(plan.get("units") or [], compiled["units"]):
        if declared.get("duration_seconds") != derived["duration_seconds"]:
            raise ValueError(f"{declared.get('unit_id')} duration is not the source-shot sum")
        if declared.get("scene_id") != derived["scene_id"]:
            raise ValueError(f"{declared.get('unit_id')} scene binding mismatch")
    derivation = plan.get("derivation") or {}
    if derivation.get("unit_count_selected_in_advance") is not False:
        raise ValueError("compiled plan must prove unit count was not selected in advance")
    if derivation.get("formula_division_used") is not False:
        raise ValueError("compiled plan must prove formula division was not used")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-manifest", required=True)
    parser.add_argument("--grouping-spec", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    production = load_json(args.production_manifest)
    spec = load_json(args.grouping_spec)
    spec["grouping_spec_sha256"] = sha256(args.grouping_spec)
    plan = compile_grouping_spec(production, spec)
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "editorial_shot_count": plan["editorial_shot_count"],
        "video_unit_count": plan["video_unit_count"],
        "runtime_seconds": plan["runtime_seconds"],
        "out": str(out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
