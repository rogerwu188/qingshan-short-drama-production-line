#!/usr/bin/env python3
"""Validate episode-map -> place-map -> shot-subspace -> blocking authority.

An EPISODE-GLOBAL-SPACE-MAP-ID names the complete spatial map used by one
episode and may be inherited unchanged by later episodes. Each concrete place
inside it has a stable GLOBAL-SPACE-MAP-ID. A generated shot must bind both
IDs, derive a locked SUBSPACE-ID, and only then resolve people and props.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GATE_ID = "SCENE-AUTHORITY-LOCK"
COMPONENT = "GLOBAL_SPACE_MAP_SUBSPACE_BLOCKING"
SHOT_STAGES = {
    "SHOT_KEYFRAME", "SHOT_START_FRAME", "SHOT_END_FRAME",
    "COMPOSITE_START_FRAME", "VIDEO_GENERATION",
}
EXEMPT_STAGES = {
    "CHARACTER_IDENTITY", "PROP_IDENTITY", "GLOBAL_SPACE_MAP",
    "SUBSPACE_LAYOUT",
}
RESOLUTION_ORDER = [
    "EPISODE_GLOBAL_SPACE_MAP", "GLOBAL_SPACE_MAP",
    "SHOT_SUBSPACE_LAYOUT", "CHARACTER_PROP_BLOCKING",
]
INHERITANCE_MODES = {"NEW", "INHERITED_EXACT", "COMPOSED"}


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def abs_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_json(value: str | Path | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        raise ValueError("episode_global_space_map_ref is missing")
    return json.loads(abs_path(value).read_text(encoding="utf-8"))


def episode_number(value: Any) -> int | None:
    match = re.match(r"E(\d+)(?:\D|$)", str(value or "").upper())
    return int(match.group(1)) if match else None


def _task_stage(task: dict[str, Any]) -> str:
    value = task.get("spatial_layout_stage") or task.get("image_purpose")
    if value:
        return str(value).upper()
    if task.get("tool_type") == "video_generation":
        return "VIDEO_GENERATION"
    return "UNDECLARED"


def requires_space_map(episode: Any, tasks: list[dict[str, Any]], explicit: Any = None) -> bool:
    number = episode_number(episode)
    # ROGER-20260827-E42-COMPLETE-MAP-MODE: E42+ shot production may
    # never opt out of the complete visual map chain.  Historical manifests
    # used ``global_space_map_gate_required=false`` as a repair escape hatch;
    # retaining that behaviour for E42+ would make the policy advisory.
    if number is not None and number >= 42:
        return any(_task_stage(task) not in EXEMPT_STAGES for task in tasks)
    if explicit is not None:
        return bool(explicit)
    if number is None or number < 40:
        return False
    return any(_task_stage(task) not in EXEMPT_STAGES for task in tasks)


def _media_failures(media: Any, *, check: str, required_kind: str) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if not isinstance(media, dict):
        return [{"check": check, "reason": "missing_or_not_object"}]
    for field in ("path", "sha256", "qa_status", "kind"):
        if not media.get(field):
            failures.append({"check": check, "reason": f"missing_{field}"})
    if media.get("qa_status") != "PASS":
        failures.append({"check": check, "reason": "qa_not_pass", "actual": media.get("qa_status")})
    if media.get("kind") != required_kind:
        failures.append({"check": check, "reason": "wrong_kind", "expected": required_kind, "actual": media.get("kind")})
    if media.get("path"):
        path = abs_path(str(media["path"]))
        if not path.is_file():
            failures.append({"check": check, "reason": "file_missing", "path": str(media["path"])})
        elif media.get("sha256") and sha256_file(path) != media.get("sha256"):
            failures.append({"check": check, "reason": "sha256_mismatch", "path": str(media["path"])})
    return failures


def _validate_exact_inheritance(authority: dict[str, Any], failures: list[dict[str, Any]]) -> None:
    inheritance = authority.get("inheritance") or {}
    mode = inheritance.get("mode")
    if mode not in INHERITANCE_MODES:
        failures.append({"check": "inheritance", "reason": "invalid_mode", "actual": mode})
        return
    if mode != "INHERITED_EXACT":
        return
    required = (
        "source_episode", "source_authority_path", "source_authority_sha256",
        "source_episode_global_space_map_id", "source_map_version",
        "source_topology_sha256", "source_map_image_sha256",
    )
    for field in required:
        if not inheritance.get(field):
            failures.append({"check": "inheritance", "field": field, "reason": "missing"})
    source_value = inheritance.get("source_authority_path")
    if not source_value:
        return
    source_path = abs_path(str(source_value))
    if not source_path.is_file():
        failures.append({"check": "inheritance", "reason": "source_authority_missing"})
        return
    if sha256_file(source_path) != inheritance.get("source_authority_sha256"):
        failures.append({"check": "inheritance", "reason": "source_authority_sha_mismatch"})
        return
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        failures.append({"check": "inheritance", "reason": f"source_authority_invalid_json:{exc}"})
        return
    comparisons = {
        "source_episode": source.get("episode"),
        "source_episode_global_space_map_id": source.get("episode_global_space_map_id"),
        "source_map_version": source.get("map_version"),
        "source_topology_sha256": source.get("topology_sha256"),
        "source_map_image_sha256": (source.get("map_image") or {}).get("sha256"),
    }
    for field, actual in comparisons.items():
        if inheritance.get(field) != actual:
            failures.append({"check": "inheritance", "field": field, "reason": "source_claim_mismatch", "expected": actual, "actual": inheritance.get(field)})
    current = {
        "episode_global_space_map_id": authority.get("episode_global_space_map_id"),
        "map_version": authority.get("map_version"),
        "topology_sha256": authority.get("topology_sha256"),
        "map_image_sha256": (authority.get("map_image") or {}).get("sha256"),
    }
    inherited = {
        "episode_global_space_map_id": inheritance.get("source_episode_global_space_map_id"),
        "map_version": inheritance.get("source_map_version"),
        "topology_sha256": inheritance.get("source_topology_sha256"),
        "map_image_sha256": inheritance.get("source_map_image_sha256"),
    }
    if current != inherited:
        failures.append({"check": "inheritance", "reason": "exact_inheritance_changed_id_version_topology_or_image", "current": current, "source": inherited})


def evaluate_authority(authority_value: str | Path | dict[str, Any] | None) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    try:
        authority = load_json(authority_value)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {
            "schema": "qingshan.episode_global_space_map_gate.v1",
            "gate_id": GATE_ID, "component": COMPONENT, "status": "FAIL",
            "failures": [{"check": "authority_load", "reason": str(exc)}],
            "recorded_at": now(),
        }
    if authority.get("schema") != "qingshan.episode_global_space_map.v1":
        failures.append({"check": "schema", "reason": "expected_qingshan.episode_global_space_map.v1"})
    for field in ("episode", "episode_global_space_map_id", "map_version", "authority_ref", "topology_sha256"):
        if authority.get(field) in (None, ""):
            failures.append({"check": "authority_required_field", "field": field, "reason": "missing"})
    if authority.get("status") != "LOCKED":
        failures.append({"check": "authority_status", "reason": "not_locked", "actual": authority.get("status")})
    _validate_exact_inheritance(authority, failures)
    failures.extend(_media_failures(authority.get("map_image"), check="episode_map_image", required_kind="EPISODE_TOP_DOWN_COMPLETE_SPACE_MAP"))

    space_maps = authority.get("space_maps")
    if not isinstance(space_maps, list) or not space_maps:
        failures.append({"check": "space_maps", "reason": "missing_or_empty"})
        space_maps = []
    expected_topology = content_sha256(space_maps)
    if authority.get("topology_sha256") != expected_topology:
        failures.append({"check": "topology_sha256", "reason": "does_not_match_space_maps", "expected": expected_topology, "actual": authority.get("topology_sha256")})

    map_ids: set[str] = set()
    room_ids: set[str] = set()
    zone_ids: set[str] = set()
    angle_ids: set[str] = set()
    axis_ids: set[str] = set()
    element_ids: set[str] = set()
    scene_to_map: dict[str, dict[str, Any]] = {}
    for map_index, space_map in enumerate(space_maps):
        map_id = space_map.get("global_space_map_id")
        if not map_id or map_id in map_ids:
            failures.append({"check": "global_space_map_id", "index": map_index, "reason": "missing_or_duplicate", "value": map_id})
        else:
            map_ids.add(map_id)
        for field in ("map_version", "name", "coordinate_system", "overall_bounds"):
            if not space_map.get(field):
                failures.append({"check": "space_map_required_field", "global_space_map_id": map_id, "field": field, "reason": "missing"})
        coordinate = space_map.get("coordinate_system") or {}
        for field in ("origin", "x_axis", "y_axis", "unit"):
            if not coordinate.get(field):
                failures.append({"check": "coordinate_system", "global_space_map_id": map_id, "field": field, "reason": "missing"})
        bounds = space_map.get("overall_bounds") or {}
        for field in ("width", "depth"):
            if not isinstance(bounds.get(field), (int, float)) or bounds.get(field, 0) <= 0:
                failures.append({"check": "overall_bounds", "global_space_map_id": map_id, "field": field, "reason": "not_positive"})
        failures.extend(_media_failures(space_map.get("layout_image"), check=f"place_map_image:{map_id}", required_kind="PLACE_TOP_DOWN_COMPLETE_SPACE_MAP"))
        rooms = space_map.get("rooms")
        if not isinstance(rooms, list) or not rooms:
            failures.append({"check": "rooms", "global_space_map_id": map_id, "reason": "missing_or_empty"})
            rooms = []
        for room in rooms:
            room_id = room.get("room_id")
            if not room_id or room_id in room_ids:
                failures.append({"check": "room_id", "global_space_map_id": map_id, "reason": "missing_or_duplicate", "value": room_id})
                continue
            room_ids.add(room_id)
            zones = room.get("zones")
            if not isinstance(zones, list) or not zones:
                failures.append({"check": "zones", "room_id": room_id, "reason": "missing_or_empty"})
                zones = []
            for zone in zones:
                zone_id = zone.get("zone_id")
                if not zone_id or zone_id in zone_ids:
                    failures.append({"check": "zone_id", "room_id": room_id, "reason": "missing_or_duplicate", "value": zone_id})
                else:
                    zone_ids.add(zone_id)
                if not isinstance(zone.get("polygon"), list) or len(zone["polygon"]) < 3:
                    failures.append({"check": "zone_polygon", "zone_id": zone_id, "reason": "needs_at_least_three_points"})
            for element in room.get("fixed_elements") or []:
                element_id = element.get("element_id")
                if not element_id or element_id in element_ids:
                    failures.append({"check": "fixed_element_id", "room_id": room_id, "reason": "missing_or_duplicate", "value": element_id})
                else:
                    element_ids.add(element_id)
                if not element.get("zone_id") or not element.get("position"):
                    failures.append({"check": "fixed_element", "element_id": element_id, "reason": "zone_or_position_missing"})
            if not room.get("entrances"):
                failures.append({"check": "entrances", "room_id": room_id, "reason": "missing_or_empty"})
            axes = room.get("axes")
            if not isinstance(axes, list) or not axes:
                failures.append({"check": "axes", "room_id": room_id, "reason": "missing_or_empty"})
                axes = []
            for axis in axes:
                axis_id = axis.get("axis_id")
                if not axis_id or axis_id in axis_ids:
                    failures.append({"check": "axis_id", "room_id": room_id, "reason": "missing_or_duplicate", "value": axis_id})
                else:
                    axis_ids.add(axis_id)
                for field in ("endpoint_a", "endpoint_b", "default_screen_direction", "crossing_policy"):
                    if not axis.get(field):
                        failures.append({"check": "axis", "axis_id": axis_id, "field": field, "reason": "missing"})
            cameras = room.get("camera_positions")
            if not isinstance(cameras, list) or not cameras:
                failures.append({"check": "camera_positions", "room_id": room_id, "reason": "missing_or_empty"})
                cameras = []
            for camera in cameras:
                angle_id = camera.get("angle_id")
                if not angle_id or angle_id in angle_ids:
                    failures.append({"check": "angle_id", "room_id": room_id, "reason": "missing_or_duplicate", "value": angle_id})
                else:
                    angle_ids.add(angle_id)
                for field in ("zone_id", "position", "facing", "axis_id", "screen_direction"):
                    if not camera.get(field):
                        failures.append({"check": "camera_position", "angle_id": angle_id, "field": field, "reason": "missing"})
        mappings = space_map.get("scene_mappings")
        if not isinstance(mappings, list) or not mappings:
            failures.append({"check": "scene_mappings", "global_space_map_id": map_id, "reason": "missing_or_empty"})
            mappings = []
        for mapping in mappings:
            scene_id = mapping.get("scene_id")
            if not scene_id or scene_id in scene_to_map:
                failures.append({"check": "scene_mapping", "reason": "scene_id_missing_or_duplicate", "value": scene_id})
            else:
                scene_to_map[scene_id] = {**mapping, "global_space_map_id": map_id}
            if mapping.get("room_id") not in room_ids:
                failures.append({"check": "scene_mapping", "scene_id": scene_id, "reason": "unknown_room_id"})
            declared_zones = mapping.get("zone_ids") or []
            if not declared_zones or any(zone not in zone_ids for zone in declared_zones):
                failures.append({"check": "scene_mapping", "scene_id": scene_id, "reason": "missing_or_unknown_zone_ids"})
    return {
        "schema": "qingshan.episode_global_space_map_gate.v1",
        "gate_id": GATE_ID, "component": COMPONENT,
        "episode": authority.get("episode"),
        "episode_global_space_map_id": authority.get("episode_global_space_map_id"),
        "status": "PASS" if not failures else "FAIL", "failures": failures,
        "authority_index": {
            "global_space_map_ids": sorted(map_ids), "room_ids": sorted(room_ids),
            "zone_ids": sorted(zone_ids), "angle_ids": sorted(angle_ids),
            "axis_ids": sorted(axis_ids), "element_ids": sorted(element_ids),
            "scene_to_map": scene_to_map,
        },
        "authority": authority, "recorded_at": now(),
    }


def evaluate_task(task: dict[str, Any], authority_report: dict[str, Any]) -> dict[str, Any]:
    key = task.get("task_key") or "UNKNOWN"
    stage = _task_stage(task)
    if stage in EXEMPT_STAGES:
        return {"task_key": key, "stage": stage, "status": "N_A", "failures": []}
    failures: list[dict[str, Any]] = []
    if stage not in SHOT_STAGES:
        failures.append({"check": "spatial_layout_stage", "reason": "missing_or_unknown", "actual": stage})
    if authority_report.get("status") != "PASS":
        failures.append({"check": "episode_global_space_map", "reason": "authority_not_locked_and_valid"})
        return {"task_key": key, "stage": stage, "status": "FAIL", "failures": failures}
    authority = authority_report["authority"]
    index = authority_report["authority_index"]
    if task.get("resolution_order") != RESOLUTION_ORDER:
        failures.append({"check": "resolution_order", "reason": "wrong_or_missing", "expected": RESOLUTION_ORDER})
    if task.get("episode_global_space_map_id") != authority.get("episode_global_space_map_id"):
        failures.append({"check": "episode_global_space_map_id", "reason": "authority_mismatch"})
    for field, values in (
        ("global_space_map_id", index["global_space_map_ids"]),
        ("room_id", index["room_ids"]), ("zone_id", index["zone_ids"]),
        ("angle_id", index["angle_ids"]),
    ):
        if task.get(field) not in values:
            failures.append({"check": field, "reason": "missing_or_not_declared", "actual": task.get(field)})
    mapping = index["scene_to_map"].get(task.get("scene_id"))
    if not mapping:
        failures.append({"check": "scene_id", "reason": "not_mapped", "actual": task.get("scene_id")})
    else:
        if mapping.get("global_space_map_id") != task.get("global_space_map_id"):
            failures.append({"check": "global_space_map_id", "reason": "does_not_match_scene_mapping"})
        if mapping.get("room_id") != task.get("room_id"):
            failures.append({"check": "room_id", "reason": "does_not_match_scene_mapping"})
        if task.get("zone_id") not in (mapping.get("zone_ids") or []):
            failures.append({"check": "zone_id", "reason": "does_not_match_scene_mapping"})

    subspace = task.get("subspace_layout")
    if not isinstance(subspace, dict):
        failures.append({"check": "subspace_layout", "reason": "missing_or_not_object"})
        subspace = {}
    required_equal = {
        "derived_from_episode_global_space_map_id": authority.get("episode_global_space_map_id"),
        "derived_from_global_space_map_id": task.get("global_space_map_id"),
        "room_id": task.get("room_id"), "angle_id": task.get("angle_id"),
    }
    for field, expected in required_equal.items():
        if subspace.get(field) != expected:
            failures.append({"check": "subspace_layout", "field": field, "reason": "authority_mismatch", "expected": expected, "actual": subspace.get(field)})
    for field in ("subspace_id", "camera_position_id", "axis_id"):
        if not subspace.get(field):
            failures.append({"check": "subspace_layout", "field": field, "reason": "missing"})
    if task.get("zone_id") not in (subspace.get("zone_ids") or []):
        failures.append({"check": "subspace_layout", "field": "zone_ids", "reason": "task_zone_not_in_subspace"})
    if subspace.get("axis_id") not in index["axis_ids"]:
        failures.append({"check": "subspace_layout", "field": "axis_id", "reason": "not_declared"})
    visible = subspace.get("visible_fixed_element_ids")
    if not isinstance(visible, list) or not visible:
        failures.append({"check": "subspace_layout", "field": "visible_fixed_element_ids", "reason": "missing_or_empty"})
    elif any(value not in index["element_ids"] for value in visible):
        failures.append({"check": "subspace_layout", "field": "visible_fixed_element_ids", "reason": "unknown_element"})
    subspace_ref = subspace.get("reference_image")
    failures.extend(_media_failures(subspace_ref, check="subspace_reference_image", required_kind="SHOT_SUBSPACE_LAYOUT"))
    place_map = next((row for row in authority.get("space_maps") or [] if row.get("global_space_map_id") == task.get("global_space_map_id")), {})
    if isinstance(subspace_ref, dict) and subspace_ref.get("derived_from_place_map_sha256") != (place_map.get("layout_image") or {}).get("sha256"):
        failures.append({"check": "subspace_reference_image", "reason": "place_map_sha_binding_mismatch"})

    blocking = task.get("blocking")
    if not isinstance(blocking, dict):
        failures.append({"check": "blocking", "reason": "missing_or_not_object"})
        blocking = {}
    if blocking.get("resolved_after_subspace_lock") is not True:
        failures.append({"check": "blocking", "reason": "not_resolved_after_subspace_lock"})
    for collection, id_field in (("characters", "character_id"), ("props", "prop_id")):
        rows = blocking.get(collection)
        if not isinstance(rows, list):
            failures.append({"check": "blocking", "field": collection, "reason": "must_be_array"})
            continue
        for row in rows:
            if not row.get(id_field) or row.get("zone_id") not in (subspace.get("zone_ids") or []) or not row.get("position") or not row.get("facing"):
                failures.append({"check": "blocking", "field": collection, "reason": "id_zone_position_or_facing_invalid", "value": row})

    bindings = task.get("reference_bindings") or []
    expected_bindings = (
        ([row for row in bindings if row.get("role") == "episode_global_space_map"], authority.get("map_image") or {}, "episode_global_space_map"),
        ([row for row in bindings if row.get("role") == "global_space_map"], place_map.get("layout_image") or {}, "global_space_map"),
        ([row for row in bindings if row.get("role") == "subspace_layout"], subspace_ref or {}, "subspace_layout"),
    )
    for rows, expected, role in expected_bindings:
        if len(rows) != 1:
            failures.append({"check": "reference_bindings", "reason": f"exactly_one_{role}_required"})
        elif rows[0].get("path") != expected.get("path") or rows[0].get("sha256") != expected.get("sha256"):
            failures.append({"check": "reference_bindings", "reason": f"{role}_binding_mismatch"})
    role_order = [row.get("role") for row in bindings]
    try:
        episode_index = role_order.index("episode_global_space_map")
        place_index = role_order.index("global_space_map")
        subspace_index = role_order.index("subspace_layout")
        blocking_indices = [position for position, role in enumerate(role_order) if role in {"character", "prop"}]
        if not episode_index < place_index < subspace_index or any(position < subspace_index for position in blocking_indices):
            failures.append({"check": "reference_bindings", "reason": "order_must_be_episode_map_place_map_subspace_then_character_prop"})
    except ValueError:
        pass
    return {
        "task_key": key, "stage": stage,
        "episode_global_space_map_id": task.get("episode_global_space_map_id"),
        "global_space_map_id": task.get("global_space_map_id"),
        "subspace_id": subspace.get("subspace_id"),
        "status": "PASS" if not failures else "FAIL", "failures": failures,
    }


def evaluate_batch(
    authority_value: str | Path | dict[str, Any] | None,
    tasks: list[dict[str, Any]], *, episode: Any = None, required: Any = None,
) -> dict[str, Any]:
    if not requires_space_map(episode, tasks, required):
        return {
            "schema": "qingshan.global_space_layout_batch_gate.v1",
            "gate_id": GATE_ID, "component": COMPONENT, "episode": episode,
            "status": "N_A", "results": [], "failures": [], "recorded_at": now(),
        }
    authority_report = evaluate_authority(authority_value)
    results = [evaluate_task(task, authority_report) for task in tasks]
    failures = list(authority_report.get("failures") or [])
    failures.extend(
        {"task_key": result.get("task_key"), **failure}
        for result in results for failure in result.get("failures") or []
    )
    return {
        "schema": "qingshan.global_space_layout_batch_gate.v1",
        "gate_id": GATE_ID, "component": COMPONENT,
        "episode": episode or authority_report.get("episode"),
        "episode_global_space_map_id": authority_report.get("episode_global_space_map_id"),
        "status": "PASS" if not failures else "FAIL",
        "authority_status": authority_report.get("status"),
        "results": results, "failures": failures,
        "rollback": "Lock the complete episode map and place map, derive and QA each shot subspace, then resolve character/prop blocking before shot keyframe or video submission.",
        "recorded_at": now(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authority", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    config = load_json(args.config)
    report = evaluate_batch(
        args.authority, config.get("tasks") or [], episode=config.get("episode"),
        required=config.get("global_space_map_gate_required"),
    )
    destination = abs_path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] in {"PASS", "N_A"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
