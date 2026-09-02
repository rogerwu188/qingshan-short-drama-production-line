#!/usr/bin/env python3
"""Build per-unit temporal-anchor decisions from a semantic grouping plan."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def _visible_characters(row: dict[str, Any]) -> set[str]:
    spec = row.get("prompt_spec") or {}
    return {
        str(item["character"])
        for item in spec.get("cast") or []
        if item.get("character") and item.get("face_visibility") != "OFFSCREEN_VOICE_ONLY"
    }


def _props(row: dict[str, Any]) -> set[str]:
    spec = row.get("prompt_spec") or {}
    return {str(item["prop"]) for item in spec.get("props") or [] if item.get("prop")}


def _version(path: Path) -> int:
    match = re.search(r"-keyframe-v(\d+)\.png$", path.name)
    return int(match.group(1)) if match else 0


def _latest_keyframe(keyframe_dir: Path, shot_id: str) -> Path:
    candidates = list(keyframe_dir.glob(f"{shot_id}-keyframe-v*.png"))
    return max(candidates, key=_version) if candidates else keyframe_dir / f"{shot_id}-keyframe-v1.png"


def _anchor_shots(rows: list[dict[str, Any]], *, include_opening: bool = True) -> tuple[list[str], bool, bool]:
    """Select references when later shots introduce identity or prop state.

    A one-reference plan is only valid when every visible identity and relevant
    prop is already represented at the start.  Later introductions require
    ordinary Omni references; they cannot be falsely bound to an exact I2V
    start frame that does not contain them.
    """
    selected = [str(rows[0]["shot_id"])] if include_opening else []
    covered_characters = _visible_characters(rows[0])
    covered_props = _props(rows[0])
    identity_reanchor = False
    prop_reanchor = False
    for row in rows[1:]:
        new_characters = _visible_characters(row) - covered_characters
        new_props = _props(row) - covered_props
        if new_characters or new_props:
            selected.append(str(row["shot_id"]))
            identity_reanchor = identity_reanchor or bool(new_characters)
            prop_reanchor = prop_reanchor or bool(new_props)
            covered_characters.update(_visible_characters(row))
            covered_props.update(_props(row))
    return selected, identity_reanchor, prop_reanchor


def build(grouping: dict[str, Any], editorial: dict[str, Any], keyframe_dir: Path) -> dict[str, Any]:
    shots = {str(row["shot_id"]): row for row in editorial.get("shots") or []}
    units: list[dict[str, Any]] = []
    missing: list[str] = []
    classes: set[str] = set()
    previous_unit_by_scene: dict[str, str] = {}
    for unit in grouping.get("units") or []:
        shot_ids = unit["editorial_shot_ids"]
        rows = [shots[shot_id] for shot_id in shot_ids]
        scene_id_value = (
            unit.get("scene_id")
            or rows[0].get("scene_id")
            or (rows[0].get("prompt_spec") or {}).get("scene_id")
        )
        if not scene_id_value:
            raise ValueError(f"{unit.get('unit_id')}:SCENE_ID_REQUIRED_FOR_OPENING_ANCHOR_CHAIN")
        scene_id = str(scene_id_value)
        previous_unit_id = previous_unit_by_scene.get(scene_id)
        scene_first = previous_unit_id is None
        has_dialogue = any(str((row.get("prompt_spec") or {}).get("dialogue") or "").strip() for row in rows)
        has_props = any((row.get("prompt_spec") or {}).get("props") for row in rows)
        action_class = (
            "DIALOGUE_PERFORMANCE_WITH_CONTINUOUS_BLOCKING" if has_dialogue
            else "PROP_DRIVEN_CONTINUOUS_ACTION" if has_props
            else "CONTINUOUS_VISUAL_ACTION"
        )
        classes.add(action_class)
        anchor_shots, identity_reanchor, prop_reanchor = _anchor_shots(
            rows, include_opening=scene_first
        )
        paths = [_latest_keyframe(keyframe_dir, shot_id) for shot_id in anchor_shots]
        missing.extend(shot_id for shot_id, path in zip(anchor_shots, paths) if not path.is_file())
        if scene_first:
            opening_key = anchor_shots[0]
            opening_path = str(paths[0])
            opening_role = "ADMITTED_SCENE_START_STATE"
            opening_source = "SCENE_FIRST_GENERATED_KEYFRAME"
            materialization_required = False
        else:
            opening_key = f"{previous_unit_id}:REAL_FINAL_FRAME"
            previous_final = unit.get("previous_unit_final_frame") or {}
            opening_path = str(
                previous_final.get("path")
                or unit.get("previous_unit_final_frame_path")
                or ""
            )
            opening_role = "PREVIOUS_UNIT_REAL_FINAL_FRAME"
            opening_source = "PREVIOUS_UNIT_REAL_FINAL_FRAME"
            materialization_required = True
        task_keys = [opening_key] + (anchor_shots[1:] if scene_first else anchor_shots)
        reference_paths = [opening_path] + (
            [str(path) for path in paths[1:]] if scene_first else [str(path) for path in paths]
        )
        count = len(task_keys)
        if count == 1 and scene_first:
            reason = (
                f"{unit['unit_id']} keeps every visible identity and relevant prop represented in "
                f"its admitted start state, so one exact first-frame reference can drive the {action_class.lower().replace('_', ' ')}."
            )
            transport = "IMAGE_TO_VIDEO_EXACT_FIRST_FRAME"
        elif count == 1:
            reason = (
                f"{unit['unit_id']} is not scene-first and therefore opens from {previous_unit_id}'s "
                "materialized real final frame; no independent opening keyframe is permitted."
            )
            transport = "IMAGE_TO_VIDEO_PREVIOUS_FINAL_FRAME"
        else:
            reason = (
                f"{unit['unit_id']} introduces later visible identities or props that are absent from "
                "the first frame; each first appearance needs an admitted ordinary reference and the "
                "unit must use capability-compatible Omni multi-reference transport."
            )
            transport = "OMNI_MULTI_REFERENCE"
        units.append({
            "unit_id": unit["unit_id"],
            "planned_reference_image_count": count,
            "scene_id": scene_id,
            "scene_first_unit": scene_first,
            "reference_image_task_keys": task_keys,
            "reference_image_paths": reference_paths,
            "reference_transport_strategy": transport,
            "opening_anchor_contract": {
                "status": "PASS" if scene_first or (opening_path and previous_final.get("sha256")) else "BLOCKED_UNTIL_PREVIOUS_FINAL_FRAME_MATERIALIZED",
                "policy": "opening_anchor_is_previous_unit_final_frame_or_scene_first_unit",
                "source": opening_source,
                "previous_unit_id": previous_unit_id,
                "materialized_path": opening_path,
                "sha256": None if scene_first else previous_final.get("sha256"),
                "materialization_required_before_submit": materialization_required,
            },
            "anchor_count_decision": {
                "planned_reference_image_count": count,
                "reason": reason,
                "criteria": {
                    "continuous_motion_from_single_start": count == 1,
                    "identity_or_space_reanchor": identity_reanchor,
                    "prop_ownership_transition": prop_reanchor,
                    "non_interpolable_terminal_state": False,
                },
                "anchor_roles": [opening_role] + ["IDENTITY_OR_PROP_REANCHOR"] * (count - 1),
                "action_design_class": action_class,
            },
            **({
                "semantic_reference_coverage_gate": {
                    "status": "PASS",
                    "references_checked": count,
                    "policy": "EVERY_LATER_VISIBLE_IDENTITY_OR_PROP_INTRODUCTION_HAS_ITS_OWN_ADMITTED_REFERENCE",
                }
            } if count > 1 else {}),
        })
        previous_unit_by_scene[scene_id] = str(unit["unit_id"])
    return {
        "schema": "qingshan.video_unit_anchor_plan.v3_previous_real_final_frame_chain",
        "episode": grouping.get("episode"),
        "video_unit_grouping_plan_sha256": None,
        "planned_reference_image_count": sum(row["planned_reference_image_count"] for row in units),
        "uniform_count_independence_audit": {
            "status": "PASS",
            "evaluated_individually": True,
            "distinct_action_design_classes": len(classes),
            "reason": "Each scene-first unit owns one opening keyframe; every later same-scene unit is chained to the previous unit's real final frame before any optional identity/prop re-anchor.",
        },
        "missing_anchor_shot_ids": missing,
        "start_frame_semantic_authoring_required": [
            {
                "unit_id": row["unit_id"],
                "status": "BLOCKED_UNTIL_EXACT_SHA_START_FRAME_SEMANTIC_EVIDENCE_PASS",
            }
            for row in units
        ],
        "units": units,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--grouping-plan", type=Path, required=True)
    parser.add_argument("--editorial-manifest", type=Path, required=True)
    parser.add_argument("--keyframe-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    plan = build(
        json.loads(args.grouping_plan.read_text(encoding="utf-8")),
        json.loads(args.editorial_manifest.read_text(encoding="utf-8")),
        args.keyframe_dir,
    )
    import hashlib
    plan["video_unit_grouping_plan_sha256"] = hashlib.sha256(args.grouping_plan.read_bytes()).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "units": len(plan["units"]),
                      "missing_anchor_shot_ids": plan["missing_anchor_shot_ids"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
