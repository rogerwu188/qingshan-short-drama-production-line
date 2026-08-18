#!/usr/bin/env python3
"""Fail closed on overloaded, discontinuous, or repetitive action-shot designs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


ACTION_REQUIRED_FIELDS = (
    "pre_state",
    "actor",
    "action",
    "contact_point",
    "force_direction",
    "force_feedback",
    "result_state",
)
SPATIAL_ACTION_REQUIRED_FIELDS = (
    "episode_global_space_map_id",
    "global_space_map_id",
    "subspace_id",
    "room_id",
    "angle_id",
    "axis_id",
    "script_action",
    "script_action_sha256",
    "canonical_script_path",
    "canonical_script_sha256",
    "start_state_token",
    "end_state_token",
)


def contract_payload(shot: dict[str, Any]) -> dict[str, Any]:
    """Return the exact design fields that must reach the provider prompt."""
    return {
        "shot_id": shot.get("shot_id"),
        "action_unit": shot.get("action_unit"),
        "visual_tier": shot.get("visual_tier"),
        "information_beats": shot.get("information_beats"),
        "camera": shot.get("camera"),
        "primary_contacts": shot.get("primary_contacts"),
        "result_read_seconds": shot.get("result_read_seconds"),
        "reset_or_replay_allowed": shot.get("reset_or_replay_allowed"),
        "continuity_group": shot.get("continuity_group"),
        "entry_state_token": shot.get("entry_state_token"),
        "exit_state_token": shot.get("exit_state_token"),
        "spatial_action_contract": shot.get("spatial_action_contract"),
    }


def contract_sha256(shot: dict[str, Any]) -> str:
    encoded = json.dumps(
        contract_payload(shot), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def prompt_marker(shot: dict[str, Any]) -> str:
    return f"[ACTION_SHOT_CONTRACT_V1:{contract_sha256(shot)}]"


def prompt_spatial_block(shot: dict[str, Any]) -> str:
    """Compile the spatial contract into provider-readable prompt text."""
    spatial = shot.get("spatial_action_contract") or {}
    trajectories = []
    for row in spatial.get("trajectories") or []:
        points = [row.get("start"), *(row.get("waypoints") or []), row.get("end")]
        trajectories.append(
            f"{row.get('entity_id')}:{json.dumps(points, ensure_ascii=False, separators=(',', ':'))}"
            f"=>{row.get('end_state')}"
        )
    return "\n".join([
        "[SPATIAL_ACTION_CONTRACT_V1]",
        f"整集空间地图ID={spatial.get('episode_global_space_map_id')}",
        f"地点空间地图ID={spatial.get('global_space_map_id')}",
        f"镜头子空间ID={spatial.get('subspace_id')}",
        f"房间/机位/轴={spatial.get('room_id')}/{spatial.get('angle_id')}/{spatial.get('axis_id')}",
        f"剧本原动作={spatial.get('script_action')}",
        f"动作轨迹={'；'.join(trajectories)}",
        f"遮挡约束={'；'.join(str(value) for value in spatial.get('occlusion_constraints') or [])}",
        f"退路与反制={'；'.join(str(value) for value in spatial.get('escape_and_counter_paths') or [])}",
        "[/SPATIAL_ACTION_CONTRACT_V1]",
    ])


def validate_task_bindings(
    plan: dict[str, Any], tasks: list[dict[str, Any]], root: Path
) -> list[str]:
    """Prove that the structured design was compiled into each provider prompt."""
    failures: list[str] = []
    shots = {str(row.get("shot_id")): row for row in plan.get("shots") or [] if row.get("shot_id")}
    required_action_shots = {
        shot_id for shot_id, row in shots.items() if row.get("action_unit") is True
    }
    bound_action_shots: list[str] = []
    for task in tasks:
        if task.get("tool_type", "video_generation") != "video_generation":
            continue
        task_id = str(task.get("task_key") or task.get("source_id") or "UNKNOWN")
        shot_id = str(task.get("action_design_shot_id") or "")
        if not shot_id or shot_id not in shots:
            failures.append(f"{task_id}:action_design_shot_binding_missing")
            continue
        if shots[shot_id].get("action_unit") is True:
            bound_action_shots.append(shot_id)
        expected = contract_sha256(shots[shot_id])
        if task.get("action_design_contract_sha256") != expected:
            failures.append(f"{task_id}:action_design_contract_sha256_mismatch")
        spatial = shots[shot_id].get("spatial_action_contract") or {}
        task_subspace = task.get("subspace_layout") or {}
        for field, task_value in (
            ("episode_global_space_map_id", task.get("episode_global_space_map_id")),
            ("global_space_map_id", task.get("global_space_map_id")),
            ("subspace_id", task_subspace.get("subspace_id")),
            ("room_id", task.get("room_id")),
            ("angle_id", task.get("angle_id")),
            ("axis_id", task_subspace.get("axis_id")),
        ):
            if spatial and spatial.get(field) != task_value:
                failures.append(f"{task_id}:spatial_action_{field}_mismatch")
        if spatial:
            source_action = str((task.get("prompt_contract") or {}).get("source_action") or "")
            if source_action != spatial.get("script_action"):
                failures.append(f"{task_id}:spatial_action_source_action_mismatch")
            start_rows = {
                str(row.get("character_id") or row.get("prop_id")): row
                for row in [
                    *((task.get("blocking") or {}).get("characters") or []),
                    *((task.get("blocking") or {}).get("props") or []),
                ]
            }
            end_rows = {
                str(row.get("character_id") or row.get("prop_id")): row
                for row in [
                    *((task.get("action_end_blocking") or {}).get("characters") or []),
                    *((task.get("action_end_blocking") or {}).get("props") or []),
                ]
            }
            for trajectory in spatial.get("trajectories") or []:
                entity_id = str(trajectory.get("entity_id") or "")
                if (start_rows.get(entity_id) or {}).get("position") != trajectory.get("start"):
                    failures.append(f"{task_id}:spatial_action_{entity_id}_start_not_bound_to_task_blocking")
                if (end_rows.get(entity_id) or {}).get("position") != trajectory.get("end"):
                    failures.append(f"{task_id}:spatial_action_{entity_id}_end_not_bound_to_task_end_blocking")
        prompt_value = task.get("prompt_path") or task.get("prompt_file")
        if not prompt_value:
            failures.append(f"{task_id}:compiled_prompt_path_missing")
            continue
        prompt_path = Path(prompt_value)
        if not prompt_path.is_absolute():
            prompt_path = root / prompt_path
        if not prompt_path.is_file():
            failures.append(f"{task_id}:compiled_prompt_not_found:{prompt_path}")
            continue
        if prompt_marker(shots[shot_id]) not in prompt_path.read_text(encoding="utf-8"):
            failures.append(f"{task_id}:action_design_contract_not_compiled_into_prompt")
        elif spatial and prompt_spatial_block(shots[shot_id]) not in prompt_path.read_text(encoding="utf-8"):
            failures.append(f"{task_id}:spatial_action_contract_not_readable_in_prompt")
    for shot_id in sorted(required_action_shots - set(bound_action_shots)):
        failures.append(f"{shot_id}:action_design_shot_unbound")
    for shot_id, count in Counter(bound_action_shots).items():
        if count > 1:
            failures.append(f"{shot_id}:action_design_shot_bound_multiple_times:{count}")
    return failures


def validate_tail_chained_submission(
    tasks: list[dict[str, Any]], root: Path
) -> list[str]:
    """Allow one ready task per action chain and require its exact predecessor tail."""
    failures: list[str] = []
    by_chain: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        if task.get("generation_schedule_mode") != "TAIL_CHAINED_SERIAL":
            continue
        sequence = task.get("action_sequence_contract") or {}
        chain_id = str(sequence.get("chain_id") or "").strip()
        task_id = str(task.get("task_key") or task.get("source_id") or "UNKNOWN")
        if not chain_id:
            failures.append(f"{task_id}:tail_chain_id_missing")
            continue
        by_chain.setdefault(chain_id, []).append(task)

    for chain_id, chain_tasks in by_chain.items():
        if len(chain_tasks) > 1:
            failures.append(f"{chain_id}:tail_chain_parallel_submission_forbidden:{len(chain_tasks)}>1")
        for task in chain_tasks:
            task_id = str(task.get("task_key") or task.get("source_id") or "UNKNOWN")
            sequence = task.get("action_sequence_contract") or {}
            try:
                sequence_index = int(sequence.get("sequence_index"))
            except (TypeError, ValueError):
                failures.append(f"{task_id}:tail_chain_sequence_index_invalid")
                continue
            if sequence_index <= 1:
                continue
            predecessor = str(sequence.get("predecessor_tail_frame_ref") or "").strip()
            if not predecessor:
                failures.append(f"{task_id}:exact_predecessor_tail_ref_missing")
                continue
            predecessor_path = Path(predecessor)
            if not predecessor_path.is_absolute():
                predecessor_path = root / predecessor_path
            if not predecessor_path.is_file():
                failures.append(f"{task_id}:exact_predecessor_tail_not_materialized:{predecessor}")
            references = task.get("reference_image_sequence") or []
            first = references[0] if references else {}
            if first.get("path") != predecessor:
                failures.append(f"{task_id}:first_reference_is_not_exact_predecessor_tail")
            if first.get("role") != "EXACT_PREDECESSOR_ACCEPTED_TAIL_AND_START_FRAME":
                failures.append(f"{task_id}:predecessor_tail_role_not_fail_closed")
            if not str(task.get("depends_on_task") or "").strip():
                failures.append(f"{task_id}:predecessor_task_dependency_missing")
    return failures


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _episode_number(value: Any) -> int:
    text = str(value or "").upper()
    match = re.match(r"E(\d+)(?:\D|$)", text)
    return int(match.group(1)) if match else 0


def _point(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) in {2, 3}
        and all(isinstance(item, (int, float)) for item in value)
    )


def _point_in_polygon(point: list[float], polygon: list[list[float]]) -> bool:
    """Boundary-inclusive 2D ray casting; z, when present, is ignored."""
    x, y = point[:2]
    inside = False
    for index, first in enumerate(polygon):
        second = polygon[(index + 1) % len(polygon)]
        x1, y1 = first[:2]
        x2, y2 = second[:2]
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) < 1e-9 and min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2):
            return True
        if (y1 > y) != (y2 > y):
            crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing_x:
                inside = not inside
    return inside


def _orientation(a: list[float], b: list[float], c: list[float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(a: list[float], b: list[float], c: list[float], d: list[float]) -> bool:
    first = _orientation(a, b, c)
    second = _orientation(a, b, d)
    third = _orientation(c, d, a)
    fourth = _orientation(c, d, b)
    return (
        ((first > 0 > second) or (first < 0 < second))
        and ((third > 0 > fourth) or (third < 0 < fourth))
    )


def _polyline_crosses_polygon(points: list[list[float]], polygon: list[list[float]]) -> bool:
    if any(_point_in_polygon(point, polygon) for point in points):
        return True
    edges = list(zip(polygon, polygon[1:] + polygon[:1]))
    return any(
        _segments_intersect(start, end, edge_start, edge_end)
        for start, end in zip(points, points[1:])
        for edge_start, edge_end in edges
    )


def _validate_spatial_action(shot: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    contract = shot.get("spatial_action_contract")
    if not isinstance(contract, dict):
        return ["spatial_action_contract_missing"]
    for field in SPATIAL_ACTION_REQUIRED_FIELDS:
        if not _text(contract.get(field)):
            failures.append(f"spatial_action_{field}_missing")
    script_action = str(contract.get("script_action") or "")
    actual_script_sha = hashlib.sha256(script_action.encode("utf-8")).hexdigest()
    if contract.get("script_action_sha256") != actual_script_sha:
        failures.append("spatial_action_script_sha256_mismatch")
    canonical_path_value = str(contract.get("canonical_script_path") or "")
    canonical_path = Path(canonical_path_value)
    if canonical_path_value and not canonical_path.is_absolute():
        canonical_path = Path(__file__).resolve().parents[1] / canonical_path
    if canonical_path_value:
        if not canonical_path.is_file():
            failures.append("spatial_action_canonical_script_missing")
        else:
            canonical_bytes = canonical_path.read_bytes()
            if contract.get("canonical_script_sha256") != hashlib.sha256(canonical_bytes).hexdigest():
                failures.append("spatial_action_canonical_script_sha256_mismatch")
            elif script_action not in canonical_bytes.decode("utf-8"):
                failures.append("spatial_action_script_action_not_verbatim_in_canonical")
    if contract.get("start_state_token") != shot.get("entry_state_token"):
        failures.append("spatial_action_start_state_token_mismatch")
    if contract.get("end_state_token") != shot.get("exit_state_token"):
        failures.append("spatial_action_end_state_token_mismatch")
    polygon = contract.get("subspace_polygon")
    if not isinstance(polygon, list) or len(polygon) < 3 or not all(_point(point) for point in polygon):
        failures.append("spatial_action_subspace_polygon_invalid")
        polygon = []
    obstacles = contract.get("non_traversable_obstacles")
    if not isinstance(obstacles, list):
        failures.append("spatial_action_obstacles_not_declared")
        obstacles = []
    else:
        for obstacle in obstacles:
            if not _text(obstacle.get("element_id")) or not isinstance(obstacle.get("polygon"), list) or len(obstacle["polygon"]) < 3:
                failures.append("spatial_action_obstacle_invalid")
    trajectories = contract.get("trajectories")
    if not isinstance(trajectories, list) or not trajectories:
        failures.append("spatial_action_trajectories_missing")
        trajectories = []
    for trajectory_index, trajectory in enumerate(trajectories, 1):
        prefix = f"spatial_action_trajectory_{trajectory_index}"
        for field in ("entity_id", "trajectory_type", "start", "waypoints", "end", "end_state"):
            if trajectory.get(field) in (None, ""):
                failures.append(f"{prefix}_{field}_missing")
        points = [trajectory.get("start"), *(trajectory.get("waypoints") or []), trajectory.get("end")]
        if not all(_point(point) for point in points):
            failures.append(f"{prefix}_points_invalid")
            continue
        if polygon and any(not _point_in_polygon(point, polygon) for point in points):
            failures.append(f"{prefix}_leaves_locked_subspace")
        allowed_contacts = set(trajectory.get("allowed_obstacle_contact_ids") or [])
        for obstacle in obstacles:
            obstacle_polygon = obstacle.get("polygon") or []
            if len(obstacle_polygon) < 3:
                continue
            if obstacle.get("element_id") in allowed_contacts:
                continue
            if _polyline_crosses_polygon(points, obstacle_polygon):
                failures.append(f"{prefix}_crosses_non_traversable:{obstacle.get('element_id')}")
        if trajectory.get("start") != trajectory.get("blocking_start_position"):
            failures.append(f"{prefix}_start_not_equal_locked_blocking")
        if trajectory.get("end") != trajectory.get("declared_end_position"):
            failures.append(f"{prefix}_end_not_equal_declared_end_state")
        if trajectory.get("zone_transition") is True and not trajectory.get("portal_ids"):
            failures.append(f"{prefix}_zone_transition_without_portal")
    if contract.get("camera_readability") not in {"PASS", True}:
        failures.append("spatial_action_camera_readability_not_locked")
    if not isinstance(contract.get("occlusion_constraints"), list) or not contract.get("occlusion_constraints"):
        failures.append("spatial_action_occlusion_constraints_not_declared")
    if not isinstance(contract.get("escape_and_counter_paths"), list) or not contract.get("escape_and_counter_paths"):
        failures.append("spatial_action_escape_and_counter_paths_not_declared")
    declared_portals = set(contract.get("declared_portal_ids") or [])
    used_portals = {
        portal
        for trajectory in trajectories
        for portal in trajectory.get("portal_ids") or []
    }
    if not used_portals.issubset(declared_portals):
        failures.append("spatial_action_uses_undeclared_portal")
    return failures


def evaluate(plan: dict[str, Any]) -> dict[str, Any]:
    shots = plan.get("shots")
    failures: list[str] = []
    decisions: list[dict[str, Any]] = []
    if not isinstance(shots, list) or not shots:
        shots = []
        failures.append("shots_missing")

    previous_by_group: dict[str, dict[str, Any]] = {}
    camera_families: list[str] = []
    maximum_information_beats = int(plan.get("maximum_information_beats_per_shot", 2))
    maximum_camera_family_share = float(plan.get("maximum_camera_family_share", 0.35))
    maximum_consecutive_camera_family = int(plan.get("maximum_consecutive_camera_family", 2))
    spatial_action_required = (
        plan.get("spatial_action_layout_required") is True
        or _episode_number(plan.get("episode")) >= 40
    )

    for index, shot in enumerate(shots, 1):
        shot_id = str(shot.get("shot_id") or f"SHOT_{index}")
        shot_failures: list[str] = []
        action_unit = shot.get("action_unit")
        if not isinstance(action_unit, bool):
            shot_failures.append("action_unit_not_explicit")
        information_beats = shot.get("information_beats")
        if not isinstance(information_beats, list) or not information_beats:
            shot_failures.append("information_beats_missing")
        elif len(information_beats) > maximum_information_beats:
            shot_failures.append(
                f"information_load_exceeded:{len(information_beats)}>{maximum_information_beats}"
            )

        camera = shot.get("camera")
        if not isinstance(camera, dict):
            camera = {}
            shot_failures.append("camera_contract_missing")
        family = str(camera.get("family") or "").strip()
        if not family:
            shot_failures.append("camera_family_missing")
        else:
            camera_families.append(family)
        moves = camera.get("moves")
        if not isinstance(moves, list):
            shot_failures.append("camera_moves_not_explicit")
        elif len(moves) > 1:
            shot_failures.append(f"camera_move_budget_exceeded:{len(moves)}>1")

        if spatial_action_required:
            shot_failures.extend(_validate_spatial_action(shot))

        if action_unit is True:
            if str(shot.get("visual_tier") or "").upper() != "CORE":
                shot_failures.append("action_shot_must_be_core_80")
            for key in ("axis", "screen_direction"):
                if not _text(camera.get(key)):
                    shot_failures.append(f"camera_{key}_missing")
            if camera.get("contact_readable") is not True:
                shot_failures.append("camera_contact_readability_not_locked")

            contracts = shot.get("primary_contacts")
            if not isinstance(contracts, list) or not contracts:
                contracts = []
                shot_failures.append("primary_contact_missing")
            elif len(contracts) > 1:
                shot_failures.append(f"primary_contact_count_exceeded:{len(contracts)}>1")
            for contact_index, contract in enumerate(contracts, 1):
                missing = [key for key in ACTION_REQUIRED_FIELDS if not _text(contract.get(key))]
                if missing:
                    shot_failures.append(
                        f"primary_contact_{contact_index}_fields_missing:{','.join(missing)}"
                    )
            try:
                result_read_seconds = float(shot.get("result_read_seconds"))
            except (TypeError, ValueError):
                shot_failures.append("action_result_read_seconds_missing_or_invalid")
            else:
                if result_read_seconds > 0.8:
                    shot_failures.append("action_result_read_exceeds_0.8s")
                if result_read_seconds <= 0:
                    shot_failures.append("action_result_read_must_be_positive")
            if shot.get("reset_or_replay_allowed") is not False:
                shot_failures.append("reset_or_replay_must_be_explicitly_forbidden")

        group = str(shot.get("continuity_group") or "").strip()
        if group:
            entry = str(shot.get("entry_state_token") or "").strip()
            exit_state = str(shot.get("exit_state_token") or "").strip()
            if not entry or not exit_state:
                shot_failures.append("continuity_state_tokens_missing")
            previous = previous_by_group.get(group)
            if previous and entry != previous["exit_state_token"]:
                shot_failures.append(
                    f"continuity_handoff_mismatch:{previous['shot_id']}:"
                    f"{previous['exit_state_token']}!={entry}"
                )
            previous_by_group[group] = {"shot_id": shot_id, "exit_state_token": exit_state}

        failures.extend(f"{shot_id}:{failure}" for failure in shot_failures)
        decisions.append({
            "shot_id": shot_id,
            "status": "PASS" if not shot_failures else "FAIL",
            "failures": shot_failures,
        })

    if camera_families:
        run_family = camera_families[0]
        run_length = 1
        for family in camera_families[1:]:
            if family == run_family:
                run_length += 1
                if run_length > maximum_consecutive_camera_family:
                    failures.append(
                        f"camera_family_consecutive_exceeded:{family}:"
                        f"{run_length}>{maximum_consecutive_camera_family}"
                    )
            else:
                run_family = family
                run_length = 1
        if len(camera_families) >= 6:
            maximum_count = max(1, math.floor(len(camera_families) * maximum_camera_family_share))
            for family, count in Counter(camera_families).items():
                if count > maximum_count:
                    failures.append(
                        f"camera_family_episode_share_exceeded:{family}:"
                        f"{count}/{len(camera_families)}"
                    )

    return {
        "schema": "backlotos.action_shot_design_gate.v1",
        "episode": plan.get("episode"),
        "status": "PASS" if not failures else "FAIL",
        "fail_closed": True,
        "policy": {
            "one_primary_contact_per_action_shot": True,
            "action_shot_visual_tier": "CORE_80",
            "maximum_information_beats_per_shot": maximum_information_beats,
            "maximum_camera_moves_per_shot": 1,
            "maximum_camera_family_share": maximum_camera_family_share,
            "maximum_consecutive_camera_family": maximum_consecutive_camera_family,
            "maximum_action_result_read_seconds": 0.8,
            "cross_shot_state_token_match_required": True,
            "spatial_action_layout_required": spatial_action_required,
            "trajectory_must_stay_inside_locked_subspace": spatial_action_required,
            "blocking_start_and_declared_end_must_match_trajectory": spatial_action_required,
        },
        "shot_count": len(shots),
        "decisions": decisions,
        "camera_family_counts": dict(Counter(camera_families)),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.plan.read_text(encoding="utf-8")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "failures": len(result["failures"]),
        "out": str(args.out),
    }, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
