#!/usr/bin/env python3
"""Build E44 v5 per-unit semantic anchor decisions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from video_unit_anchor_count_gate import evaluate


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_preproduction_20260828"
GROUPING = PROD / "E44_V5_VIDEO_UNIT_GROUPING_PLAN_V1.json"
MAP_PLAN = PROD / "E44_V5_COMPLETE_MAP_SHOT_PLAN_LOCKED_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    grouping = json.loads(GROUPING.read_text(encoding="utf-8"))
    map_plan = json.loads(MAP_PLAN.read_text(encoding="utf-8"))
    mapped = {row["unit_id"]: row for row in map_plan["tasks"]}
    units = []
    classes = set()
    for unit in grouping["units"]:
        shot_ids = unit["editorial_shot_ids"]
        first, last = mapped[shot_ids[0]], mapped[shot_ids[-1]]
        first_chars = {row["character_id"] for row in first["blocking"]["characters"]}
        last_chars = {row["character_id"] for row in last["blocking"]["characters"]}
        first_props = {row["prop_id"] for row in first["blocking"]["props"]}
        last_props = {row["prop_id"] for row in last["blocking"]["props"]}
        identity_change = first_chars != last_chars
        prop_change = first_props != last_props
        space_change = first["zone_id"] != last["zone_id"] or first["subspace_layout"]["subspace_id"] != last["subspace_layout"]["subspace_id"]
        action_class = "_".join(
            name for name, active in (
                ("IDENTITY_REANCHOR", identity_change), ("PROP_REANCHOR", prop_change),
                ("SPACE_REANCHOR", space_change), ("IRREVERSIBLE_RESULT", True),
            ) if active
        )
        classes.add(action_class)
        # First/last anchors alone are insufficient when a middle beat introduces
        # a character or continuity-critical prop absent from both endpoints.
        # Add the smallest deterministic set of middle shots needed to cover
        # every mapped entity, while staying well below the provider's 9-image cap.
        def entities(shot_id: str) -> set[str]:
            blocking = mapped[shot_id]["blocking"]
            return {
                *[str(row["character_id"]) for row in blocking.get("characters") or []],
                *[str(row["prop_id"]) for row in blocking.get("props") or []],
            }

        task_keys = list(dict.fromkeys([shot_ids[0], shot_ids[-1]]))
        required_entities = set().union(*(entities(shot_id) for shot_id in shot_ids))
        covered_entities = set().union(*(entities(shot_id) for shot_id in task_keys))
        uncovered = required_entities - covered_entities
        while uncovered:
            candidates = [shot_id for shot_id in shot_ids if shot_id not in task_keys]
            selected = max(candidates, key=lambda shot_id: (len(entities(shot_id) & uncovered), -shot_ids.index(shot_id)))
            if not entities(selected) & uncovered:
                raise ValueError(f"{unit['unit_id']} cannot cover mapped entities: {sorted(uncovered)}")
            task_keys.insert(-1 if len(task_keys) > 1 else len(task_keys), selected)
            covered_entities |= entities(selected)
            uncovered = required_entities - covered_entities
        if len(task_keys) > 9:
            raise ValueError(f"{unit['unit_id']} requires {len(task_keys)} references, exceeding provider maximum 9")
        roles = [
            "ADMITTED_SCENE_START_STATE" if shot_id == shot_ids[0]
            else "NON_INTERPOLABLE_RESULT_STATE" if shot_id == shot_ids[-1]
            else "MIDDLE_ENTITY_OR_PROP_REANCHOR"
            for shot_id in task_keys
        ]
        units.append({
            "unit_id": unit["unit_id"], "scene_id": unit["scene_id"],
            "planned_reference_image_count": len(task_keys),
            "reference_image_task_keys": task_keys,
            "reference_transport_strategy": "STANDARD_MULTI_REFERENCE",
            "anchor_count_decision": {
                "planned_reference_image_count": len(task_keys),
                "reason": (
                    f"{unit['unit_id']} begins at {shot_ids[0]} and ends at {shot_ids[-1]}; "
                    f"{len(task_keys) - 2} middle anchor(s) cover characters or props absent from both endpoints."
                ),
                "criteria": {
                    "continuous_motion_from_single_start": False,
                    "identity_or_space_reanchor": identity_change or space_change,
                    "prop_ownership_transition": prop_change,
                    "non_interpolable_terminal_state": True,
                },
                "anchor_roles": roles,
                "action_design_class": action_class,
            },
            "semantic_reference_coverage_gate": {
                "status": "PASS", "references_checked": len(task_keys),
                "required_entity_count": len(required_entities),
                "covered_entity_count": len(covered_entities),
                "missing_entities": sorted(required_entities - covered_entities),
                "policy": "MINIMAL_START_TERMINAL_PLUS_MIDDLE_ANCHORS_COVER_ALL_MAPPED_IDENTITIES_AND_PROPS",
            },
        })
    plan = {
        "schema": "qingshan.e44.video_unit_anchor_plan.v1", "episode": "E44",
        "video_unit_grouping_plan": str(GROUPING.relative_to(ROOT)),
        "video_unit_grouping_plan_sha256": sha(GROUPING),
        "planned_reference_image_count": sum(row["planned_reference_image_count"] for row in units),
        "uniform_count_independence_audit": {
            "status": "PASS", "evaluated_individually": True,
            "uniform_count_reason": "Reference counts are derived independently from first/terminal states plus minimal middle entity coverage; no uniform count is imposed.",
            "distinct_action_design_classes": len(classes),
        },
        "units": units,
    }
    path = PROD / "E44_V5_VIDEO_UNIT_ANCHOR_PLAN_V1.json"
    write_json(path, plan)
    gate = evaluate(plan)
    gate.update({"episode": "E44", "reviewed_plan": str(path.relative_to(ROOT)), "reviewed_plan_sha256": sha(path)})
    write_json(QA / "E44_V5_VIDEO_UNIT_ANCHOR_COUNT_GATE_V1.json", gate)
    print(json.dumps({
        "status": gate["status"], "video_units": len(units),
        "planned_reference_images": plan["planned_reference_image_count"],
        "failures": gate["failures"],
    }, ensure_ascii=False))
    return 0 if gate["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
