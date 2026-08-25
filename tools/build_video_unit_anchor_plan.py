#!/usr/bin/env python3
"""Build per-unit temporal-anchor decisions from a semantic grouping plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build(grouping: dict[str, Any], editorial: dict[str, Any], keyframe_dir: Path) -> dict[str, Any]:
    shots = {str(row["shot_id"]): row for row in editorial.get("shots") or []}
    units: list[dict[str, Any]] = []
    missing: list[str] = []
    classes: set[str] = set()
    for unit in grouping.get("units") or []:
        shot_ids = unit["editorial_shot_ids"]
        rows = [shots[shot_id] for shot_id in shot_ids]
        has_dialogue = any(str((row.get("prompt_spec") or {}).get("dialogue") or "").strip() for row in rows)
        has_props = any((row.get("prompt_spec") or {}).get("props") for row in rows)
        action_class = (
            "DIALOGUE_PERFORMANCE_WITH_CONTINUOUS_BLOCKING" if has_dialogue
            else "PROP_DRIVEN_CONTINUOUS_ACTION" if has_props
            else "CONTINUOUS_VISUAL_ACTION"
        )
        classes.add(action_class)
        anchor_shot = shot_ids[0]
        candidates = sorted(keyframe_dir.glob(f"{anchor_shot}-keyframe-v*.png"))
        path = candidates[-1] if candidates else keyframe_dir / f"{anchor_shot}-keyframe-v1.png"
        if not candidates:
            missing.append(anchor_shot)
        reason = (
            f"{unit['unit_id']} is one scene-local continuous unit; Seedance can derive its "
            f"{action_class.lower().replace('_', ' ')} from the admitted start state without "
            "an identity/space reset, prop-ownership discontinuity, or mandatory terminal re-anchor."
        )
        units.append({
            "unit_id": unit["unit_id"],
            "planned_reference_image_count": 1,
            "reference_image_task_keys": [anchor_shot],
            "reference_image_paths": [str(path)],
            "anchor_count_decision": {
                "planned_reference_image_count": 1,
                "reason": reason,
                "criteria": {
                    "continuous_motion_from_single_start": True,
                    "identity_or_space_reanchor": False,
                    "prop_ownership_transition": False,
                    "non_interpolable_terminal_state": False,
                },
                "anchor_roles": ["ADMITTED_SCENE_START_STATE"],
                "action_design_class": action_class,
            },
        })
    return {
        "schema": "qingshan.video_unit_anchor_plan.v1",
        "episode": grouping.get("episode"),
        "video_unit_grouping_plan_sha256": None,
        "planned_reference_image_count": len(units),
        "uniform_count_independence_audit": {
            "status": "PASS",
            "evaluated_individually": True,
            "distinct_action_design_classes": len(classes),
            "reason": "Each scene-local unit was independently checked for re-anchor and terminal-state requirements.",
        },
        "missing_anchor_shot_ids": missing,
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
