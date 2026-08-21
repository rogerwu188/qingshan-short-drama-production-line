#!/usr/bin/env python3
"""Compile zero-cost E40 switch-coverage keyframe tasks.

This compiler consumes the terminal SWITCH_COVERAGE decisions and the
native-registry spatial manifest.  It never submits provider work.  Each
replacement keeps the locked episode/place/subspace topology while reducing
the visible cast and action to the materially different coverage unit.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import build_e40_spatial_keyframe_batch as spatial


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/E40_NATIVE_IDENTITY_SWITCH_COVERAGE_PLAN_V1.json"
DEFAULT_BASE = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/E40_SPATIAL_KEYFRAME_BATCH_NATIVE_REGISTRY_V1.json"
DEFAULT_PROMPTS = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/prompts/native_identity_switch_coverage_v1"
DEFAULT_OUTPUT = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/E40_NATIVE_IDENTITY_SWITCH_COVERAGE_KEYFRAME_BATCH_V1.json"


def _filter_rows(rows: list[dict[str, Any]], key: str, allowed: set[str]) -> list[dict[str, Any]]:
    return [deepcopy(row) for row in rows if str(row.get(key) or "") in allowed]


def compile_batch(plan_path: Path, base_path: Path, prompt_dir: Path, output_path: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    base = json.loads(base_path.read_text(encoding="utf-8"))
    by_unit = {str(task["unit_id"]): task for task in base.get("tasks") or []}
    tasks: list[dict[str, Any]] = []

    for coverage in plan.get("coverage_units") or []:
        unit_id = str(coverage["replaces_unit"])
        if coverage.get("terminal_decision") != "SWITCH_COVERAGE":
            raise ValueError(f"{unit_id} is not a terminal SWITCH_COVERAGE decision")
        if unit_id not in by_unit:
            raise ValueError(f"no native spatial base task for {unit_id}")

        task = deepcopy(by_unit[unit_id])
        visible = {str(value) for value in coverage.get("visible_characters") or []}
        props = {str(value) for value in coverage.get("canonical_props") or []}
        task["task_key"] = f"{coverage['coverage_id']}-KEYFRAME-V1"
        task["shot_id"] = str(coverage["coverage_id"])
        task["coverage_id"] = str(coverage["coverage_id"])
        task["replaces_unit"] = unit_id
        task["terminal_decision"] = "SWITCH_COVERAGE"
        task["material_change"] = str(coverage["material_change"])
        task["canonical_script_action"] = (
            f"Frame: {coverage['frame_design']} Motion handoff: {coverage['motion_design']}"
        )
        task["canonical_characters"] = sorted(visible)
        task["visible_characters"] = sorted(visible)
        task["canonical_props"] = sorted(props)
        task["blocking"]["characters"] = _filter_rows(
            task["blocking"].get("characters") or [], "character_id", visible
        )
        task["action_end_blocking"]["characters"] = _filter_rows(
            task["action_end_blocking"].get("characters") or [], "character_id", visible
        )
        task["blocking"]["props"] = _filter_rows(
            task["blocking"].get("props") or [], "prop_id", props
        )
        task["action_end_blocking"]["props"] = _filter_rows(
            task["action_end_blocking"].get("props") or [], "prop_id", props
        )
        task["trajectory_overlays"] = [
            deepcopy(row)
            for row in task.get("trajectory_overlays") or []
            if str(row.get("entity_id") or "") in visible | props
        ]
        compiled = spatial.compile_task(task, prompt_dir, str(base["source_script_sha256"]))
        compiled["status"] = "READY_FOR_PRECHECK_NO_PROVIDER_POST"
        compiled["provider_post_allowed"] = False
        compiled["maximum_new_submissions"] = 0
        tasks.append(compiled)

    result = {
        "schema": "qingshan.e40.switch_coverage_keyframe_batch.v1",
        "episode": "E40",
        "status": "PRECHECK_READY_NO_PROVIDER_POST",
        "source_switch_coverage_plan": spatial.portable(plan_path),
        "source_switch_coverage_plan_sha256": spatial.sha256_file(plan_path),
        "source_native_spatial_manifest": spatial.portable(base_path),
        "source_native_spatial_manifest_sha256": spatial.sha256_file(base_path),
        "episode_global_space_map_ref": base["episode_global_space_map_ref"],
        "global_space_map_gate_required": base.get("global_space_map_gate_required", True),
        "machine_gate_reports": deepcopy(base.get("machine_gate_reports") or []),
        "consumer_contract": deepcopy(base.get("consumer_contract") or {}),
        "provider_post_allowed": False,
        "credits": 0,
        "tasks": tasks,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default=str(DEFAULT_PLAN))
    parser.add_argument("--base", default=str(DEFAULT_BASE))
    parser.add_argument("--prompt-dir", default=str(DEFAULT_PROMPTS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    result = compile_batch(Path(args.plan), Path(args.base), Path(args.prompt_dir), Path(args.output))
    print(json.dumps({"status": result["status"], "task_count": len(result["tasks"]), "output": args.output}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
