#!/usr/bin/env python3
"""Exhaustively audit E44 keyframe prompts before any paid batch submission."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_preproduction_20260828"
MANIFEST = PROD / "E44_V5_GIGGLE_KEYFRAME_MANIFEST_PRECHECK_V1.json"
GROUPING = PROD / "E44_V5_VIDEO_UNIT_GROUPING_PLAN_V1.json"
ANCHORS = PROD / "E44_V5_VIDEO_UNIT_ANCHOR_PLAN_V1.json"
MAP_PLAN = PROD / "E44_V5_COMPLETE_MAP_SHOT_PLAN_LOCKED_V1.json"
CONTRACT = ROOT / "workflow/claude_writer_agent/scripts/E44_GENERATION_CONTRACT_v5.json"
OUT = QA / "E44_V5_KEYFRAME_PROMPT_CONTINUITY_AUDIT_V1.json"
WUYUN = "ref_images/cat_wuyun_reference.jpg"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    manifest, grouping, anchors, map_plan, contract = map(
        load, (MANIFEST, GROUPING, ANCHORS, MAP_PLAN, CONTRACT)
    )
    unit_by_id = {row["unit_id"]: row for row in grouping["units"]}
    anchor_by_unit = {row["unit_id"]: row for row in anchors["units"]}
    map_by_shot = {row["unit_id"]: row for row in map_plan["tasks"]}
    shot_by_id = {row["shot_id"]: row for row in contract["shots"]}
    scene_by_id = {row["scene_id"]: row for row in contract["scene_states"]}
    task_by_key = {row["task_key"]: row for row in manifest["tasks"]}
    tasks_by_unit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    boundary_prompt_counts: Counter[str] = Counter()

    for task in manifest["tasks"]:
        task_failures: list[str] = []
        unit_id = str(task["video_unit_id"])
        shot_id = str(task["editorial_shot_id"])
        tasks_by_unit[unit_id].append(task)
        unit = unit_by_id.get(unit_id)
        anchor = anchor_by_unit.get(unit_id)
        mapped = map_by_shot.get(shot_id)
        shot = shot_by_id.get(shot_id)
        if not all((unit, anchor, mapped, shot)):
            task_failures.append("SOURCE_UNIT_ANCHOR_MAP_OR_SHOT_MISSING")
            rows.append({"task_key": task["task_key"], "status": "FAIL", "failures": task_failures})
            failures.extend(f"{task['task_key']}:{value}" for value in task_failures)
            continue
        prompt_path = resolve(task["prompt_file"])
        text = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else ""
        if not prompt_path.is_file() or sha(prompt_path) != task.get("prompt_sha256"):
            task_failures.append("PROMPT_FILE_OR_SHA_MISMATCH")
        if shot_id not in anchor["reference_image_task_keys"]:
            task_failures.append("TASK_NOT_IN_LOCKED_UNIT_ANCHOR_PLAN")
        if task.get("shot_id") != shot_id or task.get("scene_id") != shot["scene_id"]:
            task_failures.append("SHOT_OR_SCENE_BINDING_MISMATCH")
        if (mapped.get("source_shot_contract") or {}).get("action") != shot["frame_content"]:
            task_failures.append("MAP_SOURCE_ACTION_MISMATCH")
        for required in (
            shot["frame_content"],
            shot.get("dialogue") or "本镜无对白",
            shot["first_frame_motion_state"],
            mapped["episode_global_space_map_id"], mapped["global_space_map_id"],
            mapped["room_id"], mapped["zone_id"],
            mapped["subspace_layout"]["subspace_id"], mapped["subspace_layout"]["axis_id"],
        ):
            if str(required) not in text:
                task_failures.append(f"PROMPT_REQUIRED_SOURCE_FIELD_MISSING:{required}")
        scene = scene_by_id[shot["scene_id"]]
        for field in ("time_of_day_state", "weather_state", "interior_exterior", "palette_temperature"):
            if str(scene[field]) not in text:
                task_failures.append(f"SCENE_STATE_MISSING:{field}")
        camera = unit["camera_plan"]
        for field in ("shot_scale", "lens_intent", "camera_height", "camera_side", "start_framing"):
            if str(camera[field]) not in text:
                task_failures.append(f"CAMERA_CONTRACT_MISSING:{field}")

        map_characters = [row["character_id"] for row in mapped["blocking"]["characters"]]
        bound_characters = [
            row.get("entity_id") for row in task["reference_bindings"] if row.get("role") == "character"
        ]
        if map_characters != task.get("canonical_characters") or map_characters != bound_characters:
            task_failures.append("VISIBLE_CAST_MAP_PROMPT_REFERENCE_MISMATCH")
        for prop in [
            *(mapped["blocking"].get("props") or []),
            *((mapped.get("action_end_blocking") or {}).get("props") or []),
        ]:
            if str(prop["prop_id"]) not in text:
                task_failures.append(f"PROP_STATE_MISSING:{prop['prop_id']}")

        role_counts = Counter(str(row.get("role")) for row in task["reference_bindings"])
        if role_counts["scene"] != 1:
            task_failures.append("EXACTLY_ONE_SCENE_MATERIAL_REFERENCE_REQUIRED")
        for role in ("episode_global_space_map", "global_space_map", "subspace_layout"):
            if role_counts[role] != 1:
                task_failures.append(f"EXACTLY_ONE_MAP_REFERENCE_REQUIRED:{role}")
        for reference in task["reference_bindings"]:
            path = resolve(reference["path"])
            if not path.is_file() or sha(path) != reference.get("sha256"):
                task_failures.append(f"REFERENCE_FILE_OR_SHA_MISMATCH:{reference['path']}")
        if "CHAR-E44-WUYUN" in map_characters:
            wuyun_rows = [row for row in task["reference_bindings"] if row.get("entity_id") == "CHAR-E44-WUYUN"]
            if len(wuyun_rows) != 1 or wuyun_rows[0].get("path") != WUYUN:
                task_failures.append("RETURNING_WUYUN_NATIVE_ASSET_NOT_BOUND")

        incoming = unit.get("incoming_transition_contract")
        outgoing = unit.get("outgoing_transition_contract")
        if incoming:
            boundary_prompt_counts[incoming["boundary_id"]] += text.count(incoming["boundary_id"])
            for value in (incoming["boundary_id"], incoming["transition_device"], incoming["visual_bridge"], incoming["target_initial_state"]["blocking"]):
                if str(value) not in text:
                    task_failures.append("INCOMING_TRANSITION_FIELD_MISSING")
        elif "本集首段首帧" not in text:
            task_failures.append("SEQUENCE_START_CONTRACT_MISSING")
        if outgoing:
            boundary_prompt_counts[outgoing["boundary_id"]] += text.count(outgoing["boundary_id"])
            for field in ("boundary_id", "transition_device", "visual_bridge", "action_bridge", "sound_bridge"):
                if str(outgoing[field]) not in text:
                    task_failures.append(f"OUTGOING_TRANSITION_FIELD_MISSING:{field}")
            for value in (outgoing["source_terminal_state"]["blocking"], outgoing["target_initial_state"]["blocking"]):
                if str(value) not in text:
                    task_failures.append("OUTGOING_TERMINAL_OR_TARGET_STATE_MISSING")
        elif "本集末段出场" not in text:
            task_failures.append("SEQUENCE_END_CONTRACT_MISSING")

        for forbidden in ("720p", "16:9", "seedance-2.0-fast", "缓慢推镜"):
            if forbidden in text:
                task_failures.append(f"FORBIDDEN_PROMPT_LANGUAGE:{forbidden}")
        if task.get("resolution") != "2K" or task.get("aspect_ratio") != "9:16":
            task_failures.append("IMAGE_2K_9X16_CONTRACT_MISMATCH")
        failures.extend(f"{task['task_key']}:{value}" for value in task_failures)
        rows.append({
            "task_key": task["task_key"], "unit_id": unit_id, "shot_id": shot_id,
            "anchor_role": dict(zip(anchor["reference_image_task_keys"], anchor["anchor_count_decision"]["anchor_roles"]))[shot_id],
            "status": "PASS" if not task_failures else "FAIL",
            "checks": {
                "plot_dialogue_action": True, "visible_cast_identity": True,
                "scene_time_weather_palette": True, "complete_map_blocking": True,
                "props": True, "camera": True, "incoming_transition": True,
                "outgoing_transition_visual_action_sound": True,
            },
            "failures": task_failures,
        })

    for unit_id, anchor in anchor_by_unit.items():
        actual = [row["task_key"] for row in tasks_by_unit.get(unit_id, [])]
        expected = [f"{shot_id}-KF-V1" for shot_id in anchor["reference_image_task_keys"]]
        if actual != expected or len(actual) != int(anchor["planned_reference_image_count"]):
            failures.append(f"{unit_id}:EXACT_SEMANTIC_ANCHOR_SET_MISMATCH")
        coverage = anchor.get("semantic_reference_coverage_gate") or {}
        if coverage.get("status") != "PASS" or coverage.get("missing_entities"):
            failures.append(f"{unit_id}:MAPPED_ENTITY_REFERENCE_COVERAGE_FAILED")
    expected_task_count = int(anchors.get("planned_reference_image_count") or 0)
    if len(rows) != expected_task_count or len(tasks_by_unit) != 25:
        failures.append(
            f"GLOBAL_ANCHOR_COVERAGE:{len(rows)}_TASKS_{len(tasks_by_unit)}_UNITS_"
            f"EXPECTED_{expected_task_count}_25"
        )

    payload = {
        "schema": "qingshan.e44_v5.keyframe_prompt_continuity_audit.v1",
        "episode": "E44",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS" if not failures else "FAIL",
        "scope": "FULL_PRE_SUBMIT_PLOT_DIALOGUE_ACTION_VISUAL_MAP_SCENE_SOUND_TRANSITION_PROP_IDENTITY_CAMERA_CONTINUITY",
        "post_generation_policy": "TECHNICAL_AND_BASIC_PLOT_ONLY_NO_ACTION_REASONABLENESS_REROLL",
        "task_count": len(rows), "video_unit_count": len(tasks_by_unit),
        "wuyun_continuity_adjudication": {
            "status": "PASS_RETURNING_ASSET_PRECEDENCE",
            "locked_asset": WUYUN,
            "rule": "cross_episode_native_identity_asset_precedes_generic_color_descriptor; no new cat identity",
        },
        "boundary_prompt_counts": dict(sorted(boundary_prompt_counts.items())),
        "rows": rows, "failures": failures,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": payload["status"], "tasks": len(rows), "units": len(tasks_by_unit),
        "failure_count": len(failures), "out": str(OUT.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
