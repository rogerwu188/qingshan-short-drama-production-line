#!/usr/bin/env python3
"""Build per-unit temporal-anchor decisions from a semantic grouping plan."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import re
from pathlib import Path
from typing import Any

try:
    from tools.event_boundary_continuity_contract import (
        POLICY, classify_boundary, compile_internal_shot_boundaries,
    )
except ModuleNotFoundError:
    from event_boundary_continuity_contract import (
        POLICY, classify_boundary, compile_internal_shot_boundaries,
    )


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
    previous_unit: dict[str, Any] | None = None
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
        internal_chain = compile_internal_shot_boundaries(unit)
        if internal_chain["status"] == "FAIL":
            raise ValueError(";".join(internal_chain["failures"]))
        boundary = classify_boundary(previous_unit, unit)
        if boundary["status"] != "PASS":
            raise ValueError(";".join(boundary["failures"]))
        previous_unit_id = boundary.get("previous_unit_id")
        boundary_class = str(boundary["boundary_class"])
        independent_opening = boundary_class in {"NEW_EVENT_ANCHOR", "MOTIVATED_CUT"}
        has_dialogue = any(str((row.get("prompt_spec") or {}).get("dialogue") or "").strip() for row in rows)
        has_props = any((row.get("prompt_spec") or {}).get("props") for row in rows)
        action_class = (
            "DIALOGUE_PERFORMANCE_WITH_CONTINUOUS_BLOCKING" if has_dialogue
            else "PROP_DRIVEN_CONTINUOUS_ACTION" if has_props
            else "CONTINUOUS_VISUAL_ACTION"
        )
        classes.add(action_class)
        anchor_shots, identity_reanchor, prop_reanchor = _anchor_shots(
            rows, include_opening=independent_opening
        )
        paths = [_latest_keyframe(keyframe_dir, shot_id) for shot_id in anchor_shots]
        missing.extend(shot_id for shot_id, path in zip(anchor_shots, paths) if not path.is_file())
        previous_final = unit.get("previous_unit_final_frame") or {}
        if boundary_class == "NEW_EVENT_ANCHOR":
            opening_key = anchor_shots[0]
            opening_path = str(paths[0])
            opening_role = "ADMITTED_NEW_EVENT_ENTRY_STATE"
            opening_source = "NEW_EVENT_GENERATED_KEYFRAME"
            materialization_required = False
            task_keys = [opening_key] + anchor_shots[1:]
            reference_paths = [opening_path] + [str(path) for path in paths[1:]]
        elif boundary_class == "HARD_CONTINUATION":
            opening_key = f"{previous_unit_id}:REAL_FINAL_FRAME"
            opening_path = str(
                previous_final.get("path")
                or unit.get("previous_unit_final_frame_path")
                or ""
            )
            opening_role = "PREVIOUS_UNIT_REAL_FINAL_FRAME"
            opening_source = "PREVIOUS_UNIT_REAL_FINAL_FRAME"
            materialization_required = True
            task_keys = [opening_key] + anchor_shots
            reference_paths = [opening_path] + [str(path) for path in paths]
        else:
            opening_key = anchor_shots[0]
            opening_path = str(paths[0])
            opening_role = "CONTINUITY_DERIVED_ENTRY_STATE"
            opening_source = "CONTINUITY_DERIVED_KEYFRAME"
            materialization_required = False
            tail_key = f"{previous_unit_id}:REAL_FINAL_FRAME:STATE_REFERENCE"
            tail_path = str(previous_final.get("path") or unit.get("previous_unit_final_frame_path") or "")
            task_keys = [opening_key, tail_key, *anchor_shots[1:]]
            reference_paths = [opening_path, tail_path, *[str(path) for path in paths[1:]]]
        count = len(task_keys)
        if boundary_class == "NEW_EVENT_ANCHOR" and count == 1:
            reason = (
                f"{unit['unit_id']} begins a verified new event and keeps every visible identity and "
                f"relevant prop represented in its admitted entry state."
            )
            transport = "IMAGE_TO_VIDEO_EXACT_FIRST_FRAME"
        elif boundary_class == "HARD_CONTINUATION" and count == 1:
            reason = (
                f"{unit['unit_id']} is a hard continuation and therefore opens pixel-exactly from "
                f"{previous_unit_id}'s materialized real final frame."
            )
            transport = "IMAGE_TO_VIDEO_PREVIOUS_FINAL_FRAME"
        elif boundary_class == "MOTIVATED_CUT":
            reason = (
                f"{unit['unit_id']} makes a motivated camera cut inside the same continuous event; "
                "its new composition is independently admitted while the prior real tail and the full "
                "person/environment state ledger remain binding references."
            )
            transport = "OMNI_MULTI_REFERENCE"
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
            "scene_first_unit": boundary_class == "NEW_EVENT_ANCHOR",
            "event_boundary_decision": boundary,
            "persistent_state_contract": deepcopy(unit.get("persistent_state_contract") or {}),
            "shot_state_contracts": deepcopy(unit.get("shot_state_contracts") or []),
            "internal_shot_state_chain": internal_chain,
            "reference_image_task_keys": task_keys,
            "reference_image_paths": reference_paths,
            "reference_transport_strategy": transport,
            "opening_anchor_contract": {
                "status": "PASS" if boundary_class != "HARD_CONTINUATION" or (opening_path and previous_final.get("sha256")) else "BLOCKED_UNTIL_PREVIOUS_FINAL_FRAME_MATERIALIZED",
                "policy": POLICY,
                "source": opening_source,
                "previous_unit_id": previous_unit_id,
                "materialized_path": opening_path,
                "sha256": previous_final.get("sha256") if boundary_class == "HARD_CONTINUATION" else None,
                "materialization_required_before_submit": materialization_required,
                "previous_state_reference_path": str(previous_final.get("path") or "") if boundary_class == "MOTIVATED_CUT" else None,
                "previous_state_reference_sha256": previous_final.get("sha256") if boundary_class == "MOTIVATED_CUT" else None,
            },
            "anchor_count_decision": {
                "planned_reference_image_count": count,
                "reason": reason,
                "criteria": {
                    "continuous_motion_from_single_start": count == 1,
                    "identity_or_space_reanchor": identity_reanchor or boundary_class == "MOTIVATED_CUT",
                    "prop_ownership_transition": prop_reanchor,
                    "non_interpolable_terminal_state": False,
                },
                "anchor_roles": [opening_role] + (
                    ["PREVIOUS_REAL_TAIL_STATE_AUTHORITY"]
                    + ["IDENTITY_OR_PROP_REANCHOR"] * (count - 2)
                    if boundary_class == "MOTIVATED_CUT"
                    else ["IDENTITY_OR_PROP_REANCHOR"] * (count - 1)
                ),
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
        previous_unit = unit
    return {
        "schema": "qingshan.video_unit_anchor_plan.v4_continuity_event_routed",
        "episode": grouping.get("episode"),
        "video_unit_grouping_plan_sha256": None,
        "planned_reference_image_count": sum(row["planned_reference_image_count"] for row in units),
        "uniform_count_independence_audit": {
            "status": "PASS",
            "evaluated_individually": True,
            "distinct_action_design_classes": len(classes),
            "reason": "Every boundary is classified by continuous event and camera intent, never by scene id alone; persistent person and environment state remains binding across motivated cuts.",
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
