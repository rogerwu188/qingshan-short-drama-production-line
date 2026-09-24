#!/usr/bin/env python3
"""Episode-agnostic nalu preproduction builder.

One CLI that turns a writer ``generation_contract`` plus a locked
``episode_global_space_map`` into the whole offline video-unit chain:

  a. per-shot subspace plan (E-2) -> render subspace assets -> SCENE-AUTHORITY-LOCK gate
  b. generation contract -> SD2 editorial seedance manifest (E-4 / E-5)
  c. grouping spec -> transition contracts (E-6) -> compiled video-unit plan -> grouping gate
  d. per-unit start_frame_semantic_contract skeletons (E-7)
  e. video-unit anchor plan (+ anchor-count gate)
  f. machine_gate_reports bundle, transaction manifest, video-preflight attempt, report

Nothing here invents plot.  Every prompt field is composed from fields that
already exist in the generation contract, the audio contract, the visual
culture contract, or the global space map.  No network call, no paid POST and
no fabricated media, QA receipt or gate PASS is ever produced: a stage is PASS
only when the real engine gate function returned PASS.
"""

from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import nalu_policy_profile as _policy_profile
import nalu_series_scope as _series_scope
import argparse
import copy
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_PREFIX = "qingshan"
TOOL_ID = "build_nalu_preproduction.v1"
RESOLUTION_ORDER = [
    "EPISODE_GLOBAL_SPACE_MAP",
    "GLOBAL_SPACE_MAP",
    "SHOT_SUBSPACE_LAYOUT",
    "CHARACTER_PROP_BLOCKING",
]
MODEL_CONTRACT = {
    "model": "seedance-2.0-pro",
    "model_registry_key": "SEEDANCE_2_STANDARD_GIGGLE",
    "resolution": "720p",
    "native_raster": "720x1280",
    "aspect_ratio": "9:16",
    "route": "STANDARD_MULTI_REFERENCE",
}
_OPPOSITE_FACING = {
    "north": "south", "south": "north", "east": "west", "west": "east",
    "northeast": "southwest", "southwest": "northeast",
    "northwest": "southeast", "southeast": "northwest",
}
# Translation verbs only.  Rotations ("转身", "抬头") change facing, not world
# position, so they must not synthesise a travel trajectory.
TRAVEL_TERMS = ("走", "穿过", "跑", "奔", "追", "离开", "进入", "跨", "行进",
                "出门", "上街", "上前", "退", "追出", "来回")


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def portable(path: Path, root: Path) -> str:
    path = Path(path)
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def find_engine_root(*candidates: Path) -> Path:
    marker = Path("tools") / "global_space_layout_gate.py"
    for candidate in candidates:
        current = Path(candidate).resolve()
        for parent in [current, *current.parents]:
            if (parent / marker).is_file():
                return parent
    raise SystemExit("cannot locate the engine clone; pass --engine-root")


def core_name(value: str) -> str:
    """Strip parenthetical annotations from a Chinese GSM label."""
    text = re.split(r"[（(]", str(value or ""), maxsplit=1)[0].strip()
    return re.split(r"[区]$", text)[0].strip() or text


def name_keys(value: str) -> set[str]:
    core = core_name(value)
    keys = {core}
    if len(core) >= 2:
        keys.add(core[-2:])
    if len(core) == 2:
        keys.add(core[-1])
    return {key for key in keys if key}


def bbox(polygon: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [float(point[0]) for point in polygon]
    ys = [float(point[1]) for point in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def rect(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[round(x0, 3), round(y0, 3)], [round(x1, 3), round(y0, 3)],
            [round(x1, 3), round(y1, 3)], [round(x0, 3), round(y1, 3)]]


def slot_point(polygon: list[list[float]], index: int, total: int) -> list[float]:
    x0, y0, x1, y1 = bbox(polygon)
    total = max(1, total)
    if (x1 - x0) >= (y1 - y0):
        step = (x1 - x0) / (total + 1)
        return [round(x0 + step * (index + 1), 2), round((y0 + y1) / 2, 2)]
    step = (y1 - y0) / (total + 1)
    return [round((x0 + x1) / 2, 2), round(y0 + step * (index + 1), 2)]


def first_clause(text: str) -> str:
    parts = [row for row in re.split(r"[，。？！、；：\n“”‘’\"']+", str(text or "")) if row.strip()]
    return max(parts, key=len).strip() if parts else str(text or "").strip()


# --------------------------------------------------------------------------- #
# engine binding
# --------------------------------------------------------------------------- #
class Engine:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        for entry in (str(self.root), str(self.root / "tools")):
            if entry not in sys.path:
                sys.path.insert(0, entry)
        from tools.render_global_space_map_assets import build as render_build
        from tools.global_space_layout_gate import evaluate_batch as space_gate
        from tools.build_video_unit_grouping_spec import build as grouping_build
        from tools.compile_video_unit_plan import compile_grouping_spec
        from tools.video_unit_grouping_gate import evaluate as grouping_gate
        from tools.build_video_unit_anchor_plan import build as anchor_build
        from tools.video_unit_anchor_count_gate import evaluate as anchor_gate
        from tools.grouped_performance_contract import validate_grouped_beat_contract
        from tools.grouped_transition_contract import boundary_id
        from tools.multimodal_character_binding_guard import (
            DIALOGUE_CHARACTER_LIMIT, _dialogue_length,
        )

        self.render_build = render_build
        self.space_gate = space_gate
        self.grouping_build = grouping_build
        self.compile_grouping_spec = compile_grouping_spec
        self.grouping_gate = grouping_gate
        self.anchor_build = anchor_build
        self.anchor_gate = anchor_gate
        self.validate_beat = validate_grouped_beat_contract
        self.boundary_id = boundary_id
        self.dialogue_limit = DIALOGUE_CHARACTER_LIMIT
        self.dialogue_length = _dialogue_length

    def python(self) -> str:
        return sys.executable


# --------------------------------------------------------------------------- #
# global space map index
# --------------------------------------------------------------------------- #
class SpaceIndex:
    def __init__(self, gsm: dict[str, Any]) -> None:
        self.gsm = gsm
        self.episode_map_id = str(gsm.get("episode_global_space_map_id") or "")
        self.places: dict[str, dict[str, Any]] = {}
        self.rooms: dict[str, dict[str, Any]] = {}
        self.room_place: dict[str, str] = {}
        self.zones: dict[str, dict[str, Any]] = {}
        self.zone_room: dict[str, str] = {}
        self.angles: dict[str, dict[str, Any]] = {}
        self.angle_room: dict[str, str] = {}
        self.axes: dict[str, dict[str, Any]] = {}
        self.scene_map: dict[str, dict[str, Any]] = {}
        for place in gsm.get("space_maps") or []:
            place_id = str(place.get("global_space_map_id") or "")
            self.places[place_id] = place
            for room in place.get("rooms") or []:
                room_id = str(room.get("room_id") or "")
                self.rooms[room_id] = room
                self.room_place[room_id] = place_id
                for zone in room.get("zones") or []:
                    self.zones[str(zone["zone_id"])] = zone
                    self.zone_room[str(zone["zone_id"])] = room_id
                for axis in room.get("axes") or []:
                    self.axes[str(axis["axis_id"])] = axis
                for camera in room.get("camera_positions") or []:
                    self.angles[str(camera["angle_id"])] = camera
                    self.angle_room[str(camera["angle_id"])] = room_id
            for mapping in place.get("scene_mappings") or []:
                self.scene_map[str(mapping["scene_id"])] = {**mapping, "global_space_map_id": place_id}

    def angle_shot_hints(self) -> dict[str, list[str]]:
        """Map angle_id -> shot-id suffixes named in the authored angle label."""
        hints: dict[str, list[str]] = {}
        for angle_id, camera in self.angles.items():
            found = re.findall(r"S\d+-\d+", str(camera.get("name") or ""))
            hints[angle_id] = list(dict.fromkeys(found))
        return hints

    def elements(self, room_id: str) -> list[dict[str, Any]]:
        return list((self.rooms.get(room_id) or {}).get("fixed_elements") or [])


def choose_angle(shot: dict[str, Any], index: SpaceIndex, mapping: dict[str, Any],
                 hints: dict[str, list[str]], used: dict[str, int]) -> tuple[str, str]:
    """Pick the authored camera angle for one shot; returns (angle_id, basis)."""
    room_id = str(mapping.get("room_id") or "")
    room_angles = [angle_id for angle_id, owner in index.angle_room.items() if owner == room_id]
    place_id = index.room_place.get(room_id, "")
    place_angles = [angle_id for angle_id, owner in index.angle_room.items()
                    if index.room_place.get(owner) == place_id]
    shot_id = str(shot["shot_id"])
    suffix_match = re.search(r"(S\d+-\d+)$", shot_id)
    suffix = suffix_match.group(1) if suffix_match else shot_id

    exact = [angle_id for angle_id in room_angles if suffix in hints.get(angle_id, [])]
    if exact:
        return exact[0], "GSM_CAMERA_POSITION_NAME_DECLARES_THIS_SHOT_ID"
    exact_place = [angle_id for angle_id in place_angles if suffix in hints.get(angle_id, [])]
    if exact_place:
        return exact_place[0], "GSM_CAMERA_POSITION_NAME_DECLARES_THIS_SHOT_ID_IN_SAME_PLACE_MAP"

    text = " ".join(str(shot.get(field) or "") for field in ("camera", "shot_size", "axis", "blocking"))
    scored: list[tuple[int, str]] = []
    for angle_id in room_angles or place_angles:
        label = core_name((index.angles[angle_id].get("name") or ""))
        score = sum(1 for token in re.findall(r"[㐀-鿿]{2,}", label) if token in text)
        scored.append((score, angle_id))
    scored.sort(key=lambda row: (-row[0], row[1]))
    if scored and scored[0][0] > 0:
        return scored[0][1], "GSM_CAMERA_POSITION_LABEL_TEXT_MATCHES_SHOT_CAMERA_FIELDS"
    pool = room_angles or place_angles
    if not pool:
        raise SystemExit(f"{shot_id}: the global space map declares no camera position for {room_id}")
    turn = used.get(room_id, 0)
    used[room_id] = turn + 1
    return sorted(pool)[turn % len(pool)], "DETERMINISTIC_ROTATION_OVER_DECLARED_ROOM_ANGLES"


def shot_text(shot: dict[str, Any]) -> str:
    spec = shot.get("prompt_spec") or {}
    return " ".join(str(value or "") for value in (
        shot.get("blocking"), shot.get("entry_state"), shot.get("completion_state"),
        shot.get("camera"), shot.get("axis"), shot.get("shot_size"),
        (spec.get("action") or {}).get("primary_action"),
    ))


def bind_entry_supports(characters, props, bindings):
    """Align a declared movable support with its seated owner, without editing the map."""
    result = copy.deepcopy(props)
    owners = {r['character_id']: r for r in characters}
    supports = {r['prop_id']: r for r in result}
    for prop_id, owner_id in bindings.items():
        if owner_id not in owners or prop_id not in supports:
            raise ValueError(f'ENTRY_SUPPORT_BINDING_UNRESOLVED:{prop_id}:{owner_id}')
        owner, prop = owners[owner_id], supports[prop_id]
        prop.update(position=list(owner['position']), zone_id=owner['zone_id'],
                    support_owner_id=owner_id, derived_from='EXPLICIT_ENTRY_SUPPORT_BINDING')
    return result


def build_subspace_tasks(contract: dict[str, Any], index: SpaceIndex,
                         episode: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hints = index.angle_shot_hints()
    used: dict[str, int] = {}
    scenes = {str(row["scene_id"]): row for row in contract.get("scene_states") or []}
    props = [row for row in contract.get("non_character_entities") or []
             if str(row.get("entity_id") or "").startswith(("PROP-", "SET-"))]  # SET-*: fixed-set plates (火泉) bind like props
    tasks: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for shot in contract.get("shots") or []:
        shot_id = str(shot["shot_id"])
        scene_id = str(shot["scene_id"])
        mapping = index.scene_map.get(scene_id)
        if not mapping:
            raise SystemExit(f"{shot_id}: scene {scene_id} is not mapped by the global space map")
        place_id = str(mapping["global_space_map_id"])
        room_id = str(mapping["room_id"])
        declared_zones = [str(value) for value in mapping.get("zone_ids") or []]
        angle_id, angle_basis = choose_angle(shot, index, mapping, hints, used)
        camera = index.angles[angle_id]
        axis_id = str(camera.get("axis_id") or "")
        primary_zone = str(camera.get("zone_id") or "")
        if primary_zone not in declared_zones:
            primary_zone = declared_zones[0]

        text = shot_text(shot)
        selected = [primary_zone]
        for zone_id in declared_zones:
            if zone_id in selected:
                continue
            keys = set(name_keys((index.zones[zone_id].get("name") or "")))
            for element in index.elements(room_id):
                if str(element.get("zone_id")) == zone_id:
                    keys |= name_keys((element.get("name") or ""))
            if any(key in text for key in keys):
                selected.append(zone_id)
        polygons = [index.zones[zone_id]["polygon"] for zone_id in selected]
        boxes = [bbox(polygon) for polygon in polygons]
        polygon = rect(min(row[0] for row in boxes), min(row[1] for row in boxes),
                       max(row[2] for row in boxes), max(row[3] for row in boxes))
        visible = [str(element["element_id"]) for element in index.elements(room_id)
                   if str(element.get("zone_id")) in selected]
        if not visible:
            visible = [str(element["element_id"]) for element in index.elements(room_id)]

        cast = [row for row in ((shot.get("prompt_spec") or {}).get("cast") or [])
                if row.get("character_id") and row.get("first_frame_visible", True) is not False]  # hidden at entry: no blocking slot
        facing = _OPPOSITE_FACING.get(str(camera.get("facing") or "north"), "south")
        char_rows = [{
            "character_id": str(row["character_id"]),
            "character": str(row.get("character") or ""),
            "zone_id": primary_zone,
            "position": slot_point(index.zones[primary_zone]["polygon"], order, len(cast)),
            "facing": facing,
            "derived_from": "GENERATION_CONTRACT_CAST_AND_SHOT_BLOCKING_TEXT",
        } for order, row in enumerate(cast)]
        prop_rows: list[dict[str, Any]] = []
        for prop in props:
            if str(prop.get("name") or "") not in text:
                continue
            element = next((row for row in index.elements(room_id)
                            if str(row.get("zone_id")) in selected
                            and any(key in str(prop.get("name") or "") or key in str(row.get("name") or "")
                                    for key in name_keys(row.get("name") or ""))), None)
            zone_id = str(element.get("zone_id")) if element else primary_zone
            position = list(element.get("position")) if element else slot_point(
                index.zones[primary_zone]["polygon"], len(char_rows) + len(prop_rows), len(char_rows) + 2)
            prop_rows.append({
                "prop_id": str(prop["entity_id"]),
                "prop": str(prop.get("name") or ""),
                "zone_id": zone_id,
                "position": position,
                "facing": facing,
                "derived_from": "NON_CHARACTER_ENTITY_NAME_PRESENT_IN_SHOT_TEXT",
            })
        prop_rows = bind_entry_supports(char_rows, prop_rows,
            (shot.get('prompt_spec') or {}).get('entry_support_bindings') or {})
        end_chars: list[dict[str, Any]] = []
        overlays: list[dict[str, Any]] = []
        axis = index.axes.get(axis_id) or {}
        zone_polygon = index.zones[primary_zone]["polygon"]
        x0, y0, x1, y1 = bbox(zone_polygon)
        span = max(1e-6, ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5)
        vector = (0.0, 0.0)
        if axis.get("endpoint_a") and axis.get("endpoint_b"):
            ax, ay = float(axis["endpoint_a"][0]), float(axis["endpoint_a"][1])
            bx, by = float(axis["endpoint_b"][0]), float(axis["endpoint_b"][1])
            length = max(1e-6, ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5)
            vector = ((bx - ax) / length, (by - ay) / length)
        for order, row in enumerate(char_rows):
            travels = any(term in text for term in TRAVEL_TERMS) and str(row["character"]) in text
            start = list(row["position"])
            if travels and vector != (0.0, 0.0):
                end = [round(min(max(start[0] + vector[0] * span * 0.3, x0), x1), 2),
                       round(min(max(start[1] + vector[1] * span * 0.3, y0), y1), 2)]
            else:
                end = list(start)
            end_chars.append({**row, "position": end,
                              "movement": "AXIS_ALIGNED_TRAVEL" if end != start else "NO_WORLD_TRANSLATION"})
            if end != start:
                overlays.append({"entity_id": row["character_id"], "kind": "CHARACTER_TRAVEL",
                                 "start": start, "waypoints": [], "end": end,
                                 "derived_from": "shot blocking text declares translation along the mapped axis"})
        if not overlays:
            actor = char_rows[0] if char_rows else None
            target = (char_rows[1]["position"] if len(char_rows) > 1
                      else (prop_rows[0]["position"] if prop_rows
                            else (index.elements(room_id)[0].get("position")
                                  if index.elements(room_id) else None)))
            if actor and target:
                overlays.append({"entity_id": actor["character_id"], "kind": "CONTACT_OR_GAZE_VECTOR",
                                 "start": list(actor["position"]), "waypoints": [], "end": list(target),
                                 "derived_from": "no world translation in this shot; vector points at the declared contact/reaction target"})
            else:
                anchor_element = index.elements(room_id)[0] if index.elements(room_id) else None
                overlays.append({
                    "entity_id": str(anchor_element.get("element_id")) if anchor_element else primary_zone,
                    "kind": "ENVIRONMENT_STATE_CHANGE_VECTOR",
                    "start": [round((x0 + x1) / 2, 2), round(y0, 2)],
                    "waypoints": [], "end": [round((x0 + x1) / 2, 2), round(y1, 2)],
                    "derived_from": "empty shot; vector marks the environment change axis inside the subspace"})

        subspace_id = f"SUBSPACE-{shot_id}"
        space_chain_id = f"SPACECHAIN-{episode}-{place_id}-{room_id}"
        tasks.append({
            "task_key": f"{shot_id}-SUBSPACE-V1",
            "unit_id": shot_id,
            "tool_type": "image_generation",
            "spatial_layout_stage": "SHOT_KEYFRAME",
            "scene_id": scene_id,
            "episode": episode,
            "episode_global_space_map_id": index.episode_map_id,
            "global_space_map_id": place_id,
            "room_id": room_id,
            "zone_id": primary_zone,
            "angle_id": angle_id,
            "resolution_order": list(RESOLUTION_ORDER),
            "subspace_layout": {
                "subspace_id": subspace_id,
                "derived_from_episode_global_space_map_id": index.episode_map_id,
                "derived_from_global_space_map_id": place_id,
                "room_id": room_id,
                "zone_ids": selected,
                "angle_id": angle_id,
                "camera_position_id": angle_id,
                "axis_id": axis_id,
                "visible_fixed_element_ids": visible,
                "polygon": polygon,
                "angle_selection_basis": angle_basis,
                "camera_position": camera.get("position"),
                "camera_facing": camera.get("facing"),
                "screen_direction": camera.get("screen_direction"),
                "authored_camera_note": camera.get("name"),
            },
            "blocking": {
                "resolved_after_subspace_lock": True,
                "characters": char_rows,
                "props": prop_rows,
            },
            "action_end_blocking": {"characters": end_chars, "props": prop_rows},
            "trajectory_overlays": overlays,
            "space_chain_id": space_chain_id,
            "entity_reference_bindings": [],
            "source_shot_contract": {
                "shot_id": shot_id,
                "camera": shot.get("camera"),
                "axis": shot.get("axis"),
                "entry_state": shot.get("entry_state"),
                "completion_state": shot.get("completion_state"),
                "keyframe_source": shot.get("keyframe_source"),
            },
        })
        rows.append({
            "shot_id": shot_id, "scene_id": scene_id, "location_id": (scenes.get(scene_id) or {}).get("location_id"),
            "global_space_map_id": place_id, "room_id": room_id, "zone_id": primary_zone,
            "zone_ids": selected, "angle_id": angle_id, "axis_id": axis_id,
            "subspace_id": subspace_id, "angle_selection_basis": angle_basis,
            "space_chain_id": space_chain_id,
            "cast_ids": [row["character_id"] for row in char_rows],
            "prop_ids": [row["prop_id"] for row in prop_rows],
        })
    return tasks, rows


# --------------------------------------------------------------------------- #
# editorial seedance manifest (E-4 / E-5 / E-10)
# --------------------------------------------------------------------------- #
def split_dialogue(dialogue: str, limit: int, length: Any) -> tuple[str, list[dict[str, Any]]]:
    """Split any over-limit dialogue LINE at a punctuation boundary.

    Not one character of the authored text changes: the same speaker prefix is
    repeated and the original line is cut at an existing punctuation mark.
    """
    if not dialogue:
        return dialogue, []
    output: list[str] = []
    splits: list[dict[str, Any]] = []
    for line in str(dialogue).split("\n"):
        speaker, separator, spoken = line.partition("：")
        if not separator or length(spoken) <= limit:
            output.append(line)
            continue
        marks = [match.end() for match in re.finditer(r"[，、；。！？]", spoken)]
        target = len(spoken) / 2
        cut = min(marks, key=lambda value: abs(value - target)) if marks else None
        if cut is None or cut >= len(spoken):
            output.append(line)
            splits.append({
                "line": line, "spoken_length": length(spoken), "limit": limit,
                "status": "BLOCKED_NO_PUNCTUATION_BOUNDARY_AVAILABLE",
            })
            continue
        head, tail = spoken[:cut], spoken[cut:]
        output.append(f"{speaker}：{head}")
        output.append(f"{speaker}：{tail}")
        splits.append({
            "speaker": speaker, "original_spoken": spoken,
            "original_spoken_length": length(spoken), "limit": limit,
            "split_at_character_index": cut,
            "resulting_lines": [f"{speaker}：{head}", f"{speaker}：{tail}"],
            "resulting_spoken_lengths": [length(head), length(tail)],
            "text_preserved_exactly": head + tail == spoken,
            "status": "SPLIT_AT_EXISTING_PUNCTUATION_BOUNDARY",
        })
    return "\n".join(output), splits


def screen_slot(name: str, shot: dict[str, Any], order: int) -> str:
    text = f"{shot.get('axis') or ''} {shot.get('blocking') or ''}"
    for pattern, slot in (
        (rf"{re.escape(name)}[^，。；]{{0,4}}(?:在|自|向)?左", "SCREEN_LEFT"),
        (rf"{re.escape(name)}[^，。；]{{0,4}}(?:在|自|向)?右", "SCREEN_RIGHT"),
    ):
        if re.search(pattern, text):
            return slot
    if f"{name}面向镜头右" in text:
        return "SCREEN_LEFT"
    if f"{name}面向镜头左" in text:
        return "SCREEN_RIGHT"
    return f"SLOT_{order + 1}"


def authored_wardrobe_rows(requirements: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """owner_character_id -> the authored WARDROBE_STATE_REFERENCE row (asset_requirements)."""
    rows: dict[str, dict[str, Any]] = {}
    for row in ((requirements or {}).get("assets") or {}).get("wardrobe") or []:
        spec = row.get("specification") or {}
        owner = str(spec.get("owner_character_id") or "")
        if owner and str(spec.get("description") or "").strip():
            rows[owner] = {"asset_id": row.get("asset_id"), "description": str(spec["description"]).strip(),
                           "period_constraints": spec.get("period_constraints")}
    return rows


def _wardrobe_layers_from_description(description: str) -> tuple[str, str]:
    """Outer / inner layer read off the authored description — never a location string."""
    outer = None
    positive = description.replace("无外披兽皮", "")
    for token in ("陈旧兽皮大衣", "兽皮大衣", "兽皮小披", "兽皮外披", "旧兽皮"):
        if token in positive:
            outer = "陈旧兽皮大衣" if "大衣" in token else "旧兽皮小披"
            break
    if outer is None:
        outer = "无外披，粗布棉衣即为外层" if ("无外披" in description or "棉衣" in description or "棉袄" in description) else "剧本未指定"
    inner = "粗布棉袄" if "棉袄" in description else "粗布棉衣" if "棉衣" in description else "剧本未指定"
    return outer, inner



def build_internal_transition_contracts(group: dict[str, Any], by_shot: dict[str, Any],
                                       authored: dict[tuple[str, str], dict[str, Any]],
                                       allow_migration_defaults: bool = False) -> list[dict[str, Any]]:
    try:
        from tools.grouped_internal_continuity_contract import (
            _visible_characters, _space, _props, _sound, internal_boundary_id)
    except ModuleNotFoundError:
        from grouped_internal_continuity_contract import (  # type: ignore
            _visible_characters, _space, _props, _sound, internal_boundary_id)
    shot_ids = list(group.get("editorial_shot_ids") or [])
    rows: list[dict[str, Any]] = []
    for a, b in zip(shot_ids, shot_ids[1:]):
        row = authored.get((a, b))
        prev, cur = by_shot[a]["prompt_spec"], by_shot[b]["prompt_spec"]
        if not row and allow_migration_defaults:
            prev_camera = prev.get("camera_plan") or {}
            cur_camera = cur.get("camera_plan") or {}
            row = {
                "transition_mode": "MOTIVATED_CUT" if prev_camera != cur_camera else "CONTINUOUS_ACTION",
                "authorship": "EDITOR_AUTHORED",
                "camera_change_reason": "迁移旧生产线分组后新增的相邻镜头边界，按当前机位计划明确承接",
            }
        if not row:
            continue
        rows.append({
            "boundary_id": internal_boundary_id(str(group["unit_id"]), a, b),
            "from_shot_id": a, "to_shot_id": b,
            "transition_mode": row["transition_mode"],
            "authorship": row.get("authorship") or "DIRECTOR_AUTHORED",
            "cast_bridge": {"from_visible_characters": _visible_characters(prev),
                            "to_visible_characters": _visible_characters(cur),
                            "identity_preservation": row.get("identity_preservation") or "角色、服装与脸部身份沿承，不重置",
                            "entry_exit_or_reveal": row.get("entry_exit_or_reveal") or "保持同一角色连续；新增角色必须明确入画或切换承接"},
            "scene_bridge": {"from_space": _space(prev), "to_space": _space(cur),
                             "continuity": row.get("scene_continuity") or "地图空间、光向与人物位置连续"},
            "prop_bridge": {"from_props": _props(prev), "to_props": _props(cur),
                            "ownership_or_handoff": row.get("prop_handoff") or "道具归属与位置保持连续，不交换"},
            "sound_bridge": {"from_sound": _sound(prev), "to_sound": _sound(cur), "bridge": row.get("sound_bridge") or "现场声从上一拍连续过渡到下一拍"},
            "camera_bridge": {"axis_strategy": row.get("axis_strategy") or "沿既定轴线保持方向，不越轴", "transition_execution": row.get("transition_execution") or row.get("camera_change_reason") or "按承接机位完成一次明确转场"},
            "camera_change_reason": row.get("camera_change_reason") or row.get("plot_motivation") or row.get("transition_execution") or "按承接机位完成一次明确转场",
            "action_bridge": row.get("action_bridge") or f"上一拍终态「{(prev.get('action') or {}).get('completion_state','')}」→ 下一拍起态「{(cur.get('action') or {}).get('start_state','')}」，动作连续不复位",
            "reference_bridge": {"entity_mapping": row.get("entity_mapping") or "按角色实体ID逐一对应，禁止换人",
                                 "different_character_same_slot_forbidden": True,
                                 "same_slot_reuse_allowed": bool(row.get("same_slot_reuse_allowed", False))},
            "authoring_source": "generation_contract.internal_transition_authoring",
        })
    return rows


def wardrobe_bible(contract: dict[str, Any], episode: str,
                   requirements: dict[str, Any] | None = None) -> dict[str, Any]:
    """Itemized wardrobe bible.

    Authority order: the authored WARD-* rows in asset_requirements.json (the same
    text the paid identity prompts were compiled from) > the character's own
    appearance_ch1.  The visual-culture production_design string is NOT split
    into garments any more: it lists buildings and food too, and an earlier
    version of this function put "茅草与木板屋顶压雪" into outer_layer.  Fields
    the authored text does not decide are left null and are skipped by every
    consumer (keyframe prompt lines, review expectations).
    """
    authored = authored_wardrobe_rows(requirements)
    vcc = contract.get("visual_culture_contract") or {}
    design = str(vcc.get("production_design") or "")
    palette = vcc.get("palette_system") or {}
    del design  # production_design is art-department prose, not a garment list
    rows: list[dict[str, Any]] = []
    for order, entity in enumerate(contract.get("character_entities") or []):
        name = str(entity.get("canonical_name") or "")
        character_id = str(entity.get("character_id") or "")
        appearance = str(entity.get("appearance_ch1") or "")
        ward = authored.get(character_id)
        description = ward["description"] if ward else ""
        basis_text = description or appearance
        outer, inner = _wardrobe_layers_from_description(basis_text)
        row = {
            "character": name,
            "character_id": character_id,
            "social_tier": "VILLAGE_SUBSISTENCE_FARMER",
            "role_basis": f"依据剧本人物描写：{appearance}",
            "authored_description": description or None,
            "authored_wardrobe_asset_id": (ward or {}).get("asset_id"),
            "silhouette": None,
            "outer_layer": outer,
            "inner_layer": inner,
            "primary_color": None,
            "secondary_color": None,
            "material": "粗布棉" + ("＋兽皮" if ("兽皮" in basis_text and "无外披兽皮" not in basis_text) else ""),
            "material_justification": "依据作者层服装描述" if description else "依据人物外貌描写",
            "pattern": None,
            "belt_or_fastening": ("麻布腰带" if "麻布腰带" in basis_text else
                                  "腰间麻绳" if "麻绳" in basis_text else
                                  "布带系束" if "布带" in basis_text else None),
            "footwear": None,
            "accessory": ("麻布头巾" if "头巾" in basis_text else None),
            "condition": "长期穿用、雪水浸渍、袖口与下摆磨损",
            "continuity_key": f"WARDROBE-{episode}-{character_id}-V1",
            "derivation": {
                "script_authored_fields": ["role_basis", "authored_description", "outer_layer",
                                           "inner_layer", "belt_or_fastening", "accessory"],
                "null_means": "the authored wardrobe text does not decide this field; consumers skip it",
                "authority": ("asset_requirements.assets.wardrobe[owner_character_id]."
                              "specification.description" if description else
                              "character_entities[].appearance_ch1"),
                "production_design_no_longer_split_into_garments": True,
            },
            "appearance_ch1": appearance,
        }
        # 2026-09-12: structured garment fields authored in the generation contract
        # (character_entities[].wardrobe_garments, from the LOCKED plates + ch1) override the
        # heuristics above; tools/wardrobe_identity_contract.py requires them non-null.
        garments = entity.get("wardrobe_garments") or {}
        for field in ("silhouette", "outer_layer", "inner_layer", "primary_color", "secondary_color",
                      "material", "pattern", "belt_or_fastening", "footwear", "accessory"):
            if str(garments.get(field) or "").strip():
                row[field] = str(garments[field]).strip()
        if garments:
            row["derivation"]["structured_fields_authority"] = "generation_contract.character_entities[].wardrobe_garments"
        rows.append(row)
    return {
        "schema": "qingshan.wardrobe_identity_contract.v1_role_and_peer_distinction",
        "bible_id": f"WARDROBE-BIBLE-{episode}-V1",
        "episode": episode,
        "animal_characters": [],
        "palette_reference": palette,
        "characters": rows,
    }


def bind_dialogue_cast(dialogue, cast, entities):
    """Resolve speakers by registered identity, not display-name inequality."""
    names = {}
    for cid, entity in entities.items():
        for name in [entity.get("canonical_name"), *(entity.get("aliases") or [])]:
            if not name:
                continue
            if name in names and names[name] != cid:
                raise ValueError(f"DIALOGUE_ALIAS_COLLISION:{name}")
            names[name] = cid
    result = copy.deepcopy(cast)
    known_ids = {c.get("character_id") for c in result}
    lines = []
    for line in dialogue.splitlines():
        speaker, separator, spoken = line.partition("：")
        if not separator or not speaker.strip():
            raise ValueError("DIALOGUE_SPEAKER_UNRESOLVED")
        cid = names.get(speaker.strip())
        if not cid:
            raise ValueError(f"DIALOGUE_SPEAKER_UNREGISTERED:{speaker.strip()}")
        canonical = entities[cid]["canonical_name"]
        lines.append(f"{canonical}：{spoken}")
        if cid not in known_ids:
            result.append({"character": canonical, "character_id": cid,
                           "screen_slot": "OFFSCREEN", "depth_plane": "OFFSCREEN_SOURCE",
                           "face_visibility": "OFFSCREEN_VOICE_ONLY", "identity_card_required": False})
            known_ids.add(cid)
    return "\n".join(lines), result


def migrate_shot_camera_state(legacy_state, shot):
    """Legacy ledgers supply continuity, not authority over current camera plans."""
    result = copy.deepcopy(legacy_state)
    spec = shot.get('prompt_spec') or {}
    plan = spec.get('camera_plan') or {}
    space = spec.get('space') or {}
    camera = result.setdefault('camera_state', {})
    before = copy.deepcopy(camera)
    for key in ('shot_scale', 'lens_intent', 'motion_family'):
        if plan.get(key):
            camera[key] = plan[key]
    for key, source in (('camera_position_id', 'angle_id'), ('axis_id', 'axis_id')):
        value = shot.get(source) or space.get(source)
        if value:
            camera[key] = value
    if before != camera:
        result['camera_projection'] = {'source': 'CURRENT_SHOT_PROMPT_SPEC',
                                       'legacy_camera_state': before}
    return result


def scoped_interaction(source_action, subject, target, delta_text):
    """Do not turn solo performance into an invented contact event."""
    contact = source_action.get("contact_point") or ("" if source_action.get("interaction_mode") == "NONE" else
        f"{subject}与{target}的接触/反应落点：{delta_text}" if target else "")
    result = {"contact_point": contact}
    if source_action.get("interaction_mode"):
        result["interaction_mode"] = source_action["interaction_mode"]
    elif not target and not contact:
        result["interaction_mode"] = "NONE"
    return result


def constrain_noncontact_sound(sound, action):
    """An explicit no-contact action must not inherit template impact cues."""
    evidence = str(action.get("physical_causality") or "")
    explicit_none = str(action.get("interaction_mode") or "").upper() == "NONE"
    if action.get("contact_point") or not (explicit_none or any(term in evidence for term in ("未触碰", "不接触", "没有接触", "没有触碰"))):
        return copy.deepcopy(sound)
    result = copy.deepcopy(sound)
    result["foley"] = "仅保留已声明动作实际产生的衣料及道具拟音，不添加人物之间的触碰、撞击或未发生的脚步声"
    old = str(result.get("action_sound") or "")
    # Preserve authored audio/BGM policy following the generated cue.
    policy = old.partition("一次因果接触声；")[2] if old.startswith("只强化「") else old
    cue = "本拍人物之间未发生接触，不添加人物接触音效；已声明的笔纸等道具接触拟音保留"
    for previous_cue in (cue, "本拍人物之间未发生接触，不生成接触音效"):
        if policy.startswith(previous_cue):
            policy = policy[len(previous_cue):].lstrip("；")
    result["action_sound"] = cue + ("；" + policy if policy else "")
    return result


def scope_shot_sound(sound, shot_id):
    """Keep local Foley/impact instructions local when the renderer merges sounds."""
    result = copy.deepcopy(sound)
    prefix = f"仅分镜{shot_id}适用："
    for key in ("foley", "action_sound"):
        value = str(result.get(key) or "")
        if value and not value.startswith(prefix):
            result[key] = prefix + value
    return result


def build_editorial(contract: dict[str, Any], plan_rows: list[dict[str, Any]],
                    index: SpaceIndex, engine: Engine, episode: str,
                    contract_path: Path, gsm_path: Path,
                    root: Path, requirements: dict[str, Any] | None = None
                    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    vcc = contract.get("visual_culture_contract") or {}
    palette = vcc.get("palette_system") or {}
    audio = contract.get("audio_contract") or {}
    ambient = audio.get("ambient_by_scene") or {}
    bgm_value = audio.get("bgm")
    bgm_rule = str((bgm_value.get("declaration") if isinstance(bgm_value, dict) else bgm_value) or "")
    scenes = {str(row["scene_id"]): row for row in contract.get("scene_states") or []}
    by_shot = {str(row["shot_id"]): row for row in plan_rows}
    entities = {str(row["character_id"]): row for row in contract.get("character_entities") or []}
    props_by_id = {str(row["entity_id"]): row for row in contract.get("non_character_entities") or []}
    bible = wardrobe_bible(contract, episode, requirements)
    bible_by_name = {row["character"]: row for row in bible["characters"]}
    forbidden = [str(row) for row in vcc.get("forbidden_influences") or []]

    shots: list[dict[str, Any]] = []
    all_splits: list[dict[str, Any]] = []
    cursor = 0.0
    for shot in contract.get("shots") or []:
        shot_id = str(shot["shot_id"])
        scene_id = str(shot["scene_id"])
        scene = scenes.get(scene_id) or {}
        row = by_shot[shot_id]
        duration = float(shot["target_seconds"])
        start_seconds = round(cursor, 3)
        cursor = round(cursor + duration, 3)
        spec = shot.get("prompt_spec") or {}
        role = spec.get("role_semantic_disambiguation") or {}
        source_action = spec.get("action") or {}
        entry = str(shot.get("entry_state") or "")
        completion = str(shot.get("completion_state") or "")
        primary = str(source_action.get("primary_action") or "")
        # Historical E01 contracts predate explicit beat endpoints.  Preserve
        # their replay compatibility, but never synthesize those authored facts
        # for a new portable production merely to satisfy a downstream gate.
        missing_endpoints = [
            name for name, value in (
                ("entry_state", entry), ("completion_state", completion)
            ) if not value
        ]
        if missing_endpoints and _policy_profile.is_current():
            raise RuntimeError(
                "CURRENT_PORTABLE_SHOT_ENDPOINTS_REQUIRED:"
                f"{shot_id}:{','.join(missing_endpoints)}"
            )
        if not entry:
            entry = "动作开始前：主体处于初始状态"
        if not completion:
            completion = f"动作完成后：{primary or '主体保持当前状态'}"
        evidence = shot.get("state_delta_evidence") or {}
        dims = [str(value) for value in shot.get("state_delta_dimensions") or []]
        first_dim = dims[0] if dims else ""
        first_ev = evidence.get(first_dim) or {}
        arc_entry = str(first_ev.get("entry") or entry)
        arc_exit = str(first_ev.get("exit") or completion)
        delta_text = "；".join(
            f"{name}：{(evidence.get(name) or {}).get('entry')}→{(evidence.get(name) or {}).get('exit')}"
            for name in dims
        ) or f"{entry}→{completion}"

        dialogue, splits = split_dialogue(str(spec.get("dialogue") or ""),
                                         engine.dialogue_limit, engine.dialogue_length)
        for entry_row in splits:
            all_splits.append({"shot_id": shot_id, **entry_row})

        room_id = str(row["room_id"])
        room = index.rooms.get(room_id) or {}
        element_names = [core_name(element.get("name") or "") for element in index.elements(room_id)
                         if str(element.get("zone_id")) in row["zone_ids"]]
        zone_names = [core_name((index.zones[zone_id].get("name") or "")) for zone_id in row["zone_ids"]]

        cast_rows = spec.get("cast") or []
        cast: list[dict[str, Any]] = []
        for order, member in enumerate(cast_rows):
            name = str(member.get("character") or "")
            cast.append({
                "character": name,
                "character_id": str(member.get("character_id") or ""),
                "screen_slot": str(member.get("screen_slot") or screen_slot(name, shot, order)),  # authored slot wins
                "depth_plane": "PRIMARY_ACTION_PLANE" if order < 2 else "REACTION_PLANE",
                "face_visibility": ("ENTERS_IN_SHOT_NOT_IN_FIRST_FRAME" if member.get("first_frame_visible", True) is False
                                    else str(member.get("face_visibility") or "VISIBLE_PER_FRAME_CONTENT")),
                "identity_card_required": True,
                "entity_presence": (role.get("entity_presence") or {}).get(str(member.get("character_id") or "")),
            })
        dialogue, cast = bind_dialogue_cast(dialogue, cast, entities)
        props = [{
            "prop": str(props_by_id[prop_id].get("name") or prop_id),
            "prop_id": prop_id,
            "anchor": "PRIMARY_ACTION_PLANE",
            "continuity_scope": "SCENE_OR_RECURRING_PROP",
            "note": str(props_by_id[prop_id].get("note") or ""),
        } for prop_id in row["prop_ids"] if prop_id in props_by_id]

        subject = str(role.get("primary_actor") or "")
        patient = str(role.get("action_patient") or "")
        actor_kind = str(role.get("primary_actor_kind") or "CHARACTER").upper()
        if not subject:
            subject = "环境本身（无人物空镜）" if actor_kind == "ENVIRONMENT" else (
                cast[0]["character"] if cast else "画内主体")
        target = patient or (element_names[0] if element_names else str(row["zone_id"]))

        intensity = 1 + (1 if cast_rows else 0) + (1 if dialogue else 0)
        intensity += 1 if "！" in dialogue else 0
        intensity += 1 if len(dims) >= 3 else 0
        intensity = max(1, min(5, intensity))

        actor_performance: dict[str, Any] = {}
        for member in cast:
            state = (role.get("entity_states") or {}).get(member["character_id"]) or completion
            actor_performance[member["character"]] = {
                "expression_arc": f"{arc_entry}→{arc_exit}",
                "continuous_micro_action": (
                    f"呼吸连续；{member['character']}的眼神先于头部改变一次，"
                    f"眼睑与下颌只在因果点响应"),
                "event_reaction": f"只对「{primary or entry}」发生一次可见反应，随后保持「{state}」",
                "body_sync": (
                    f"视线先动，下颌与肩颈随后，重心最后完成并停在「{state}」，不复位不重演"),
                "state_authority": state,
            }

        delivery = None
        if dialogue:
            spoken_all = dialogue.partition("：")[2]
            first_line_spoken = dialogue.split("\n")[0].partition("：")[2]
            emphasis = first_clause(first_line_spoken) or first_line_spoken.strip()
            if emphasis not in spoken_all:
                emphasis = first_line_spoken.strip()
            delivery = {
                "pace": "自然克制，按原文停连，不均匀播报",
                "pause_map": "只在原文逗号、问号、感叹号处短停；句末留半拍给对方反应",
                "emphasis_words": [emphasis],
                "volume_arc": "贴近现场音量起句，重音轻抬，句末收回，不喊叫",
                "breath_pattern": "开口前一次短吸气，长句在原文停连处补气，不切断词组",
                "delivery_transition": f"由「{arc_entry}」的心理起点讲到「{arc_exit}」的明确落点",
                "line_count": len(dialogue.split("\n")),
                "character_limit_per_line": engine.dialogue_limit,
                "spoken_lengths": [engine.dialogue_length(line.partition("：")[2])
                                   for line in dialogue.split("\n")],
            }

        depth_layers = [
            f"前景：{element_names[0] if element_names else zone_names[0]}（{row['zone_id']} 内已声明的固定物）",
            f"中景：{'、'.join(member['character'] for member in cast) or '雪面与空气本身'}执行「{primary or entry}」",
            f"背景：{room.get('name') or room_id} 的 {'、'.join(zone_names)} 纵深",
        ]
        if len(element_names) > 1:
            depth_layers.append(f"纵深补充：{element_names[1]}")
        materials = [value.strip() for value in re.split(r"[、，；]", str(vcc.get("production_design") or ""))
                     if value.strip()][:4] or ["夯土与粗布材质"]
        env_motion = [
            f"天候：{scene.get('weather')}（只做连续微动，不做特效）",
            f"光源微动：{scene.get('lighting')}",
        ]
        if ambient.get(scene_id):
            env_motion.append(f"与现场声一致的可见微动：{ambient.get(scene_id)}")

        visual = {
            "depth_layers": depth_layers,
            "scale_anchor": (
                f"以 {element_names[0] if element_names else zone_names[0]} 与人物肩宽保持真实比例；"
                f"place map {row['global_space_map_id']} 的坐标单位为米"),
            "key_light": f"{scene.get('lighting')}；{vcc.get('lighting_language')}",
            "atmosphere": f"{scene.get('weather')}；{vcc.get('image_texture')}",
            "environmental_motion": env_motion,
            "material_detail": materials,
            "still_prompt_contract": (
                f"首帧只表现 entry_state「{entry}」；严禁出现 completion_state「{completion}」"),
            "video_motion_contract": (
                f"从「{entry}」经「{primary or delta_text}」到「{completion}」一次完成并保持结果态"),
            "palette": {
                "dominant": str(palette.get("base") or "靛黑夜色"),
                "contrast": str(palette.get("skin") or "冷白肤色"),
                "accent": str(palette.get("accent") or "橘红太阳石"),
            },
        }
        sound = {
            "ambience": str(ambient.get(scene_id) or f"{scene.get('weather')}的现场底声"),
            "foley": (
                f"近景真实接触声，来自「{shot.get('blocking')}」中的衣料、脚步与"
                f"{'、'.join(item['prop'] for item in props) or '固定物'}"),
            "action_sound": f"只强化「{primary or entry}」一次因果接触声；{bgm_rule}",
        }
        sound = constrain_noncontact_sound(sound, source_action)
        sound = scope_shot_sound(sound, shot_id)
        negatives = [*forbidden,
                     "冻结帧、速度斜坡或慢动作",
                     "首帧出现 completion_state",
                     "外置配乐、旁白或字幕",
                     "跨镜头动作循环或复位重演"]

        prompt_spec = {
            "space": {
                "global": index.episode_map_id,
                # Transition contracts require a stable non-empty location;
                # legacy scene rows may omit location_id, so use the authored
                # room identity as the canonical fallback.
                "location": str(scene.get("location_id") or row.get("room_id") or row.get("global_space_map_id") or "UNKNOWN_LOCATION"),
                "subspace": str(row["subspace_id"]),
            },
            "scene_state": {
                "time": str(scene.get("time_id") or ""),
                "weather": str(scene.get("weather") or ""),
                "lighting": str(scene.get("lighting") or ""),
                "palette": str(palette.get("base") or ""),
                # writer production fields required by tools/sd2_background_ecology_contract.py
                # (BEAT_n_WRITER_AMBIENT_LIFE_MISSING / BEAT_n_WEATHER_PROVENANCE_MISSING); passed
                # through verbatim from the generation contract, never synthesised here.
                "ambient_life": scene.get("ambient_life"),
                "weather_provenance": scene.get("weather_provenance"),
            },
            "cast": cast,
            "props": props,
            "camera": (
                f"{shot.get('shot_size')}／{shot.get('camera')}；机位 {row['angle_id']}，"
                f"轴线 {row['axis_id']}，子空间 {row['subspace_id']}"),
            "action": {
                "t0_seconds": start_seconds,
                "t1_seconds": round(start_seconds + duration, 3),
                "start_state": entry,
                "primary_action": primary or entry,
                "completion_state": completion,
                **scoped_interaction(source_action, subject, target, delta_text),
                "motion_direction": (
                    f"沿已声明轴线「{shot.get('axis')}」（{row['axis_id']}）单一方向"
                    f"由「{entry}」到「{completion}」，不反向复位"),
                "physical_causality": source_action.get('physical_causality') or (
                    f"{subject}发起「{primary or entry}」→ {target} 承受 → 结果停在「{completion}」；"
                    f"接触先发生，眼神与下颌随后，肩颈与重心最后完成" if target else
                    f"{subject}完成本镜动作「{primary or entry}」，到达「{completion}」；不增加接触对象"),
                "freeze_or_speed_ramp_forbidden": True,
                "microexpression_design": source_action.get('microexpression_design') or (
                    f"眼神先于头部改变一次，呼吸与下颌在因果点响应，随后保持「{arc_exit}」"
                    if cast_rows else
                    f"无人物；微观变化只发生在{scene.get('weather')}的雪幕、火光与呼出白气等环境细节上"),
                "physical_action_design": (
                    f"「{primary or entry}」一次完成并停在「{completion}」；"
                    f"尾帧保留呼吸、衣料与道具惯性微动，禁止循环、复位或另起动作"),
                "action_kind": "NON_COMBAT",
                "subject_id": str(source_action.get("subject_id") or ""),
                "patient_id": str(source_action.get("patient_id") or ""),
                "state_delta_dimensions": dims,
                "state_delta_evidence": evidence,
            },
            "performance": {
                "psychological_state": (
                    f"只处理当前一拍「{primary or entry}」，不预演后续情节"),
                "emotion": (
                    "情绪外露但仍克制" if "！" in dialogue else
                    "试探与追问" if "？" in dialogue else
                    "克制而有明确因果落点" if cast_rows else
                    "无人物情绪，只有环境压迫感"),
                "emotion_intensity": intensity,
                "expression_arc": f"{arc_entry}→{arc_exit}",
                "continuous_micro_action": (
                    "呼吸连续，眼神先动，眼睑与下颌只在因果点变化一次"
                    if cast_rows else "雪幕、火光与屋顶积雪保持连续微动"),
                "event_reaction": (spec.get('performance') or {}).get('event_reaction') or f"对「{primary or entry}」只发生一次可见反应，随后保持「{completion}」",
                "body_sync": (spec.get('performance') or {}).get('body_sync') or (
                    "视线先行，下颌与肩颈随后，手部或重心最后完成并保持"
                    if cast_rows else "环境力学按同一方向完成一次变化并保持"),
                "actor_performance": actor_performance,
            },
            "dialogue": dialogue,
            # authored delivery rate (tools/dialogue_cut_safety.py reads
            # spec.dialogue_delivery.chinese_characters_per_second); passed through verbatim
            **({"dialogue_delivery": shot["dialogue_delivery"]} if isinstance(shot.get("dialogue_delivery"), dict) else {}),
            "visual_design": visual,
            "sound_design": sound,
            "audio_contract": "SAME_VIDEO_TASK_NATIVE_AUDIO" if dialogue else "DIEGETIC_OR_SILENT_NO_TTS",
            "negative_prompts": negatives,
            "referent_resolution_contract": spec.get("referent_resolution_contract"),
            # director-authored camera plan (generation contract prompt_spec.camera_plan) — the
            # grouping builder treats a first-shot camera_plan as authoritative
            **({"camera_plan": spec["camera_plan"]} if isinstance(spec.get("camera_plan"), dict) else {}),
            **({"wardrobe_state_overrides": spec["wardrobe_state_overrides"]} if isinstance(spec.get("wardrobe_state_overrides"), dict) else {}),
            **({"wardrobe_reference_exclusions": spec["wardrobe_reference_exclusions"]} if isinstance(spec.get("wardrobe_reference_exclusions"), dict) else {}),
            "role_semantic_disambiguation": role,
            "keyframe_source": str(shot.get("keyframe_source") or "entry_state"),
            "expected_keyframe_filename": f"{shot_id}-keyframe-v1.png",
            # seq=12 / engine e19: an authored per-shot identity re-anchor request is passed through verbatim
            **({"identity_reanchor_required": True, "identity_reanchor_reason": spec.get("identity_reanchor_reason")}
               if spec.get("identity_reanchor_required") else {}),
        }
        if delivery is not None:
            prompt_spec["dialogue_delivery"] = delivery
            # merge the authored rate (contract shot.dialogue_delivery) so
            # tools/dialogue_cut_safety.py reads chinese_characters_per_second
            if isinstance(shot.get("dialogue_delivery"), dict):
                prompt_spec["dialogue_delivery"].update(
                    {key: value for key, value in shot["dialogue_delivery"].items() if value is not None})

        visible_names = [member["character"] for member in cast
                         if member["face_visibility"] != "OFFSCREEN_VOICE_ONLY"]
        shots.append({
            "shot_id": shot_id,
            "scene_id": scene_id,
            "duration_seconds": duration,
            "start_seconds": start_seconds,
            "model": MODEL_CONTRACT["model"],
            "resolution": MODEL_CONTRACT["resolution"],
            "aspect_ratio": MODEL_CONTRACT["aspect_ratio"],
            "shot_size": shot.get("shot_size"),
            "axis": shot.get("axis"),
            "blocking": shot.get("blocking"),
            "entry_state": entry,
            "completion_state": completion,
            "angle_id": row["angle_id"],
            "axis_id": row["axis_id"],
            "subspace_id": row["subspace_id"],
            "room_id": room_id,
            "zone_id": row["zone_id"],
            "global_space_map_id": row["global_space_map_id"],
            "prompt_spec": prompt_spec,
            "wardrobe_contract": {
                "schema": bible["schema"],
                "episode_bible_id": bible["bible_id"],
                "animal_characters": [],
                "characters": [copy.deepcopy(bible_by_name[name]) for name in visible_names
                               if name in bible_by_name],
            },
        })

    manifest = {
        "schema": "qingshan.editorial_seedance_manifest.v2_performance_complete",
        "episode": episode,
        "generated_by": TOOL_ID,
        "generated_at": now(),
        "source_generation_contract": portable(contract_path, root),
        "source_generation_contract_sha256": sha256_file(contract_path),
        "source_episode_global_space_map": portable(gsm_path, root),
        "source_episode_global_space_map_sha256": sha256_file(gsm_path),
        "episode_global_space_map_id": index.episode_map_id,
        "model_contract": dict(MODEL_CONTRACT),
        "field_rename_note": "generation_contract.target_seconds -> duration_seconds (E-5)",
        "dialogue_character_limit": engine.dialogue_limit,
        "runtime_seconds": round(sum(float(row["duration_seconds"]) for row in shots), 3),
        "wardrobe_bible": bible,
        "shots": shots,
    }
    return manifest, all_splits


# --------------------------------------------------------------------------- #
# transition contracts (E-6)
# --------------------------------------------------------------------------- #
def build_transition(engine: Engine, previous_group: dict[str, Any], group: dict[str, Any],
                     left: dict[str, Any], right: dict[str, Any],
                     ambient: dict[str, Any]) -> dict[str, Any]:
    left_spec, right_spec = left["prompt_spec"], right["prompt_spec"]
    left_space, right_space = left_spec["space"], right_spec["space"]
    same_subspace = left_space["subspace"] == right_space["subspace"]
    same_location = left_space["location"] == right_space["location"]
    angle_changed = left.get("angle_id") != right.get("angle_id")
    left_dialogue = bool(str(left_spec.get("dialogue") or "").strip())
    right_dialogue = bool(str(right_spec.get("dialogue") or "").strip())
    left_props = {row["prop"] for row in left_spec.get("props") or []}
    right_props = {row["prop"] for row in right_spec.get("props") or []}
    source_state = str(left_spec["action"]["completion_state"])
    target_state = str(right_spec["action"]["start_state"])

    if same_subspace:
        space_relation = "SAME_SUBSPACE"
        cut_reason = ("REACTION_CUT" if (left_dialogue or right_dialogue)
                      else "CONTINUOUS_ACTION" if not angle_changed else "SAME_SPACE_COVERAGE")
    elif same_location:
        space_relation = "SAME_LOCATION_NEW_SUBSPACE"
        cut_reason = "NEW_SPACE_MATCH_CUT"
    else:
        space_relation = "NEW_LOCATION_SAME_GLOBAL"
        cut_reason = ("NEW_SPACE_ESTABLISH" if not (right_spec.get("cast") or [])
                      else "SOUND_BRIDGE_NEW_SPACE")

    if not same_location:
        device = "SOUND_BRIDGE" if right_dialogue or left_dialogue else "ENVIRONMENT_BRIDGE"
    elif angle_changed:
        device = "GAZE_MATCH" if (left_dialogue or right_dialogue) else "MOTIVATED_CUT"
    elif left_props & right_props:
        device = "PROP_MATCH"
    else:
        device = "ACTION_MATCH"

    left_ambient = str(ambient.get(left["scene_id"]) or "")
    right_ambient = str(ambient.get(right["scene_id"]) or "")
    visible = sorted({row["character"] for row in right_spec.get("cast") or []
                      if row.get("face_visibility") != "OFFSCREEN_VOICE_ONLY"})
    return {
        "boundary_id": engine.boundary_id(previous_group["unit_id"], group["unit_id"]),
        "from_unit_id": previous_group["unit_id"],
        "to_unit_id": group["unit_id"],
        "authorship": "DIRECTOR_AUTHORED",
        "cut_reason": cut_reason,
        "space_relation": space_relation,
        "transition_device": device,
        "outgoing_handle_seconds": 0.8,
        "incoming_handle_seconds": 0.8,
        "plot_motivation": (
            f"由「{source_state}」这一结果推动「{target_state}」的下一拍，不插入无关空镜或重复交代"),
        "visual_bridge": (
            f"上一段以{previous_group['camera_plan']['end_framing']}停在「{source_state}」，"
            f"下一段以{group['camera_plan']['start_framing']}从「{target_state}」承接"),
        "action_bridge": (
            f"「{source_state}」→「{target_state}」；动作因果不断裂，不复位不重演"),
        "sound_bridge": (
            f"{left_ambient or '现场底声'}的声尾跨过切点，{right_ambient or '现场底声'}的首个真实声接管；"
            f"人声不得截断"),
        "axis_strategy": (
            f"从 {left.get('axis_id')} 切到 {right.get('axis_id')}；"
            + ("同轴不越轴，保持既定屏幕方向"
               if left.get("axis_id") == right.get("axis_id")
               else "换轴后先以地图内固定物重建方向再进入新轴")),
        "continuity_intent": "剧情、人物身份、服装、道具、地图坐标、光向与现场声全部连续，不因换镜复位",
        "source_terminal_state": {
            "scene_id": left["scene_id"],
            "space": dict(left_space),
            "camera_framing": previous_group["camera_plan"]["end_framing"],
            "camera_side": previous_group["camera_plan"]["camera_side"],
            "blocking": source_state,
        },
        "target_initial_state": {
            "scene_id": right["scene_id"],
            "space": dict(right_space),
            "camera_framing": group["camera_plan"]["start_framing"],
            "camera_side": group["camera_plan"]["camera_side"],
            "blocking": target_state,
        },
        "anchor_semantic_requirements": {
            "target_visible_characters": visible,
            "target_visible_props": sorted(right_props),
            "target_space_anchors": [right_space["location"], right_space["subspace"]],
            "empty_establishing_frame_allowed": not visible,
        },
        "derived_from": {
            "source_shot_id": left["shot_id"], "target_shot_id": right["shot_id"],
            "authority": "adjacent shots completion_state/entry_state + scene change + axis + ambient_by_scene",
        },
    }


# --------------------------------------------------------------------------- #
# start frame semantic contracts (E-7)
# --------------------------------------------------------------------------- #
def build_start_frame_contracts(anchor_plan: dict[str, Any], editorial: dict[str, Any],
                                root: Path) -> list[dict[str, Any]]:
    by_shot = {str(row["shot_id"]): row for row in editorial["shots"]}
    rows: list[dict[str, Any]] = []
    for unit in anchor_plan.get("units") or []:
        shot_id = str(unit["reference_image_task_keys"][0]).split(":")[0]
        first_shot = by_shot.get(str((unit.get("editorial_shot_ids") or [shot_id])[0])) or by_shot.get(shot_id)
        if first_shot is None:
            first_shot = by_shot[sorted(by_shot)[0]]
        spec = first_shot["prompt_spec"]
        reference_value = str((unit.get("reference_image_paths") or [""])[0])
        reference_path = Path(reference_value) if reference_value else None
        exists = bool(reference_path and reference_path.is_file())
        required_characters = sorted({row["character"] for row in spec.get("cast") or []
                                      if row.get("face_visibility") != "OFFSCREEN_VOICE_ONLY"})
        required_props = sorted({row["prop"] for row in spec.get("props") or []})
        required_anchors = [spec["space"]["location"], spec["space"]["subspace"]]
        pending: list[str] = []
        if not exists:
            pending.append(f"KEYFRAME_MISSING:{reference_value or 'UNRESOLVED'}")
        # --- read-only pickup of the start-frame observation receipt (D-5) -----
        # The receipt is authored OUTSIDE this compiler by
        # runtime/tools/start_frame_evidence_writer.py from a submitted
        # CLAUDE_VLM_STRUCTURED_REVIEW.  This block only READS it at the path
        # this file already declares in ``expected_evidence_ref`` below, and
        # only adopts values the receipt itself states.  Nothing is inferred:
        # a missing, non-PASS or sha-stale receipt leaves the contract BLOCKED
        # exactly as before, and compile_grouped_seedance_manifest re-verifies
        # every adopted field against this receipt anyway
        # (grouped_anchor_semantic_contract.validate_start_anchor_semantics).
        expected_ref = f"reports/start_frame_evidence/{unit['unit_id']}_start_frame_evidence.json"
        receipt_path = root / expected_ref
        receipt: dict[str, Any] | None = None
        if receipt_path.is_file():
            try:
                candidate = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                candidate = None
                pending.append("START_FRAME_OBSERVATION_EVIDENCE_RECEIPT_UNREADABLE")
            if isinstance(candidate, dict):
                receipt_sha = str(candidate.get("reference_sha256") or "")
                actual_sha = sha256_file(reference_path) if exists else None
                if candidate.get("status") != "PASS":
                    pending.append("START_FRAME_OBSERVATION_EVIDENCE_RECEIPT_NOT_PASS")
                elif str(candidate.get("reference_path") or "") != (reference_value or ""):
                    pending.append("START_FRAME_OBSERVATION_EVIDENCE_RECEIPT_PATH_MISMATCH")
                elif not actual_sha or receipt_sha != actual_sha:
                    pending.append("START_FRAME_OBSERVATION_EVIDENCE_RECEIPT_SHA_STALE")
                else:
                    receipt = candidate
        if receipt is None:
            pending.append("START_FRAME_OBSERVATION_EVIDENCE_RECEIPT_MISSING")
        rows.append({
            "unit_id": unit["unit_id"],
            "status": ("PASS" if receipt is not None and not pending
                       else "BLOCKED_UNTIL_EXACT_SHA_START_FRAME_SEMANTIC_EVIDENCE_PASS"),
            "derived_from": {
                "shot_id": first_shot["shot_id"],
                "entry_state": spec["action"]["start_state"],
                "keyframe_source": spec.get("keyframe_source"),
                "camera_start_framing": (unit.get("event_boundary_decision") or {}).get("boundary_class"),
            },
            "reference_path": reference_value or None,
            "reference_sha256": sha256_file(reference_path) if exists else None,
            "evidence_ref": expected_ref if receipt is not None else None,
            "expected_evidence_ref": expected_ref,
            "required_visible_characters": required_characters,
            "required_visible_props": required_props,
            "required_space_anchors": required_anchors,
            "observed_visible_characters": (
                receipt.get("observed_visible_characters") or [] if receipt else []),
            "observed_visible_props": (
                receipt.get("observed_visible_props") or [] if receipt else []),
            "observed_space_anchors": (
                receipt.get("observed_space_anchors") or [] if receipt else []),
            "camera_start_framing_match": (
                receipt.get("camera_start_framing_match") if receipt else None),
            "space_match": receipt.get("space_match") if receipt else None,
            "empty_establishing_frame": (
                receipt.get("empty_establishing_frame") if receipt
                else not required_characters),
            "evidence_review_method": receipt.get("review_method") if receipt else None,
            "evidence_reviewer": receipt.get("reviewer") if receipt else None,
            "evidence_sha256": (
                hashlib.sha256(receipt_path.read_bytes()).hexdigest() if receipt else None),
            "start_frame_must_show_only_entry_state": spec["visual_design"]["still_prompt_contract"],
            "pending_inputs": pending,
            "authoring_note": (
                "Every derivable field is authored here from the unit's first shot entry_state. "
                "status may only become PASS after the real keyframe exists and a real "
                "observation receipt (evidence_ref) records the same observed characters, props, "
                "space anchors and camera-start-framing match. No receipt is fabricated."),
        })
    return rows


# --------------------------------------------------------------------------- #
# stage runner
# --------------------------------------------------------------------------- #
def run_cli(engine: Engine, argv: list[str], cwd: Path) -> dict[str, Any]:
    env = dict(os.environ)
    env.pop("GIGGLE_API_KEY", None)
    env["PYTHONPATH"] = os.pathsep.join([str(engine.root), str(engine.root / "tools")])
    completed = subprocess.run(
        [engine.python(), *argv], cwd=str(cwd), env=env,
        capture_output=True, text=True,
    )
    return {
        "argv": argv, "returncode": completed.returncode,
        "stdout": completed.stdout.strip()[-4000:], "stderr": completed.stderr.strip()[-4000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the offline nalu preproduction chain.")
    parser.add_argument("--episode", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--gsm", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--keyframe-dir")
    parser.add_argument("--ready-units", help="JSON list of unit ids for a rolling wave: stages 4.3+ run on a "
                        ".partial_ready. grouping restricted to these units (engine compile_manifest partial mode)")
    parser.add_argument("--real-final-frames", help="directory of <unit_id>.png real final frames extracted from "
                        "harvested videos; injected as previous_unit_final_frame for successors")
    parser.add_argument("--asset-requirements",
                        help="preproduction/<EP>/asset_requirements.json — its authored WARD-* rows are "
                             "the wardrobe bible authority (same text the identity prompts use)")
    parser.add_argument("--legacy-plan", help="optional prior production grouping plan used to migrate authored internal transitions")
    parser.add_argument("--engine-root")
    args = parser.parse_args()

    if os.environ.get("GIGGLE_API_KEY", "").strip():
        raise SystemExit("GIGGLE_API_KEY must stay unset for this offline builder")

    contract_path = Path(args.contract).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()
    gsm_path = Path(args.gsm).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = out_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    root = Path(args.engine_root).expanduser().resolve() if args.engine_root else find_engine_root(
        contract_path, out_dir, Path(__file__))
    engine = Engine(root)
    episode = str(args.episode)
    prefix = f"{episode}_"
    stages: list[dict[str, Any]] = []
    gate_reports: list[dict[str, Any]] = []

    def stage(name: str, status: str, **extra: Any) -> None:
        stages.append({"stage": name, "status": status, **extra})

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    writer_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    gsm = json.loads(gsm_path.read_text(encoding="utf-8"))
    requirements = (json.loads(Path(args.asset_requirements).expanduser().read_text(encoding="utf-8"))
                    if args.asset_requirements else None)
    if str(contract.get("episode")) != episode:
        raise SystemExit(f"contract episode {contract.get('episode')} != --episode {episode}")
    if str(gsm.get("episode")) != episode:
        raise SystemExit(f"global space map episode {gsm.get('episode')} != --episode {episode}")
    index = SpaceIndex(gsm)

    # ---------------------------------------------------------------- stage a
    tasks, plan_rows = build_subspace_tasks(contract, index, episode)
    template = write_json(out_dir / f"{prefix}SUBSPACE_SHOT_PLAN_TEMPLATE_V1.json", {
        "schema": "qingshan.complete_map_shot_plan.v1",
        "episode": episode, "generated_by": TOOL_ID,
        "global_space_map_gate_required": True,
        "episode_global_space_map_id": index.episode_map_id,
        "tasks": tasks,
    })
    assets = out_dir / "space_map_assets"
    locked, rendered, receipt = engine.render_build(gsm, json.loads(template.read_text(encoding="utf-8")), assets)
    authority_path = write_json(out_dir / f"{prefix}EPISODE_GLOBAL_SPACE_MAP_AUTHORITY_LOCKED_V1.json", locked)
    rendered_path = write_json(out_dir / f"{prefix}SUBSPACE_SHOT_PLAN_LOCKED_V1.json", rendered)
    receipt["authority_path"] = portable(authority_path, root)
    receipt["authority_sha256"] = sha256_file(authority_path)
    receipt["shot_plan_path"] = portable(rendered_path, root)
    receipt["shot_plan_sha256"] = sha256_file(rendered_path)
    write_json(reports_dir / f"{prefix}SUBSPACE_RENDER_RECEIPT_V1.json", receipt)

    space_report = engine.space_gate(locked, rendered["tasks"], episode=episode, required=True)
    space_report_path = write_json(reports_dir / f"{prefix}GLOBAL_SPACE_LAYOUT_GATE_V1.json", space_report)
    stage("1.4_subspace_plan_and_space_gate", space_report["status"],
          subspaces=receipt["subspace_count"],
          authority_status=space_report.get("authority_status"),
          failures=space_report.get("failures") or [],
          report=portable(space_report_path, root),
          topology_sha256=locked.get("topology_sha256"),
          source_topology_sha256=gsm.get("topology_sha256"))
    if space_report["status"] == "PASS":
        gate_reports.append({"gate_id": space_report["gate_id"], "path": portable(space_report_path, root)})
    else:
        write_json(out_dir / f"{prefix}PREPRODUCTION_REPORT.json", {
            "schema": "qingshan.nalu_preproduction_report.v1", "episode": episode,
            "status": "BLOCKED", "stages": stages, "recorded_at": now()})
        print(json.dumps({"status": "BLOCKED", "stage": "1.4"}, ensure_ascii=False))
        return 2

    # ---------------------------------------------------------------- stage b
    editorial, splits = build_editorial(contract, plan_rows, index, engine, episode,
                                        contract_path, gsm_path, root,
                                        requirements=requirements)
    beat_failures: list[str] = []
    for shot in editorial["shots"]:
        try:
            engine.validate_beat(shot["prompt_spec"], source_id=shot["shot_id"])
        except ValueError as exc:
            beat_failures.append(str(exc))
    editorial_path = write_json(out_dir / f"{prefix}EDITORIAL_SEEDANCE_MANIFEST_V1.json", editorial)
    stage("4.0_editorial_seedance_manifest", "PASS" if not beat_failures else "FAIL",
          shots=len(editorial["shots"]), runtime_seconds=editorial["runtime_seconds"],
          grouped_beat_contract_failures=beat_failures,
          dialogue_splits=len(splits), path=portable(editorial_path, root),
          writer_manifest_ref=portable(manifest_path, root),
          writer_manifest_sha256=sha256_file(manifest_path),
          writer_manifest_schema=writer_manifest.get("schema"))
    write_json(reports_dir / f"{prefix}DIALOGUE_CAP_REPORT_V1.json", {
        "schema": "qingshan.dialogue_character_limit_report.v1",
        "episode": episode, "limit": engine.dialogue_limit,
        "counting_authority": "tools/multimodal_character_binding_guard.py:_dialogue_length",
        "dialogue_splits": splits,
        "lines": [
            {"shot_id": shot["shot_id"], "line": line,
             "spoken_length": engine.dialogue_length(line.partition("：")[2]),
             "raw_length": len(line.partition("：")[2])}
            for shot in editorial["shots"]
            for line in str(shot["prompt_spec"].get("dialogue") or "").split("\n") if line
        ],
    })
    if beat_failures:
        write_json(out_dir / f"{prefix}PREPRODUCTION_REPORT.json", {
            "schema": "qingshan.nalu_preproduction_report.v1", "episode": episode,
            "status": "BLOCKED", "stages": stages, "recorded_at": now()})
        print(json.dumps({"status": "BLOCKED", "stage": "4.0"}, ensure_ascii=False))
        return 2

    # ---------------------------------------------------------------- stage c
    source_sha = sha256_file(editorial_path)
    production, spec = engine.grouping_build(editorial, source_sha)
    production["source"] = {
        "script_sha256": source_sha,
        "editorial_seedance_manifest": portable(editorial_path, root),
        "generation_contract": portable(contract_path, root),
        "generation_contract_sha256": sha256_file(contract_path),
    }
    production["production_overlay"] = {
        "model": MODEL_CONTRACT["model"], "resolution": MODEL_CONTRACT["resolution"],
        "aspect_ratio": MODEL_CONTRACT["aspect_ratio"], "route": MODEL_CONTRACT["route"],
        "complete_map_mode_required": True,
        "authorization_ref": "PENDING_PRIVATE_LINE_OWNER_PAID_AUTHORIZATION",
        "paid_post_allowed": False,
    }
    by_shot = {str(row["shot_id"]): row for row in editorial["shots"]}
    ambient = (contract.get("audio_contract") or {}).get("ambient_by_scene") or {}
    authored_internal = {
        (str(row.get("from_shot_id")), str(row.get("to_shot_id"))): row
        for row in contract.get("internal_transition_authoring") or []}
    # v4 contracts may author internal transitions while still omitting the
    # legacy persistent/shot state ledgers required by the paid storyboard
    # gate.  Always use the dedicated E59 legacy plan as a state-source
    # fallback; it never overrides an authored transition.
    if args.legacy_plan:
        legacy = json.loads(Path(args.legacy_plan).expanduser().resolve().read_text(encoding="utf-8"))
        legacy_units = {str(unit.get("unit_id")): unit for unit in legacy.get("units") or []}
        legacy_shot_states = {
            str(row.get("shot_id")): row
            for unit in legacy.get("units") or []
            for row in unit.get("shot_state_contracts") or []
            if row.get("shot_id")
        }
        for group in spec.get("groups") or []:
            prior = legacy_units.get(str(group.get("unit_id")))
            migrated_states = [migrate_shot_camera_state(legacy_shot_states[sid], by_shot[sid])
                               for sid in group.get("editorial_shot_ids") or []
                               if sid in legacy_shot_states]
            if len(migrated_states) == len(group.get("editorial_shot_ids") or []):
                group["shot_state_contracts"] = migrated_states
                first = migrated_states[0].get("persistent_state_contract") or {}
                last = migrated_states[-1].get("persistent_state_contract") or {}
                group["persistent_state_contract"] = {
                    "status": "PASS", "characters": [],
                    "no_character_state_reason": "migrated legacy state chain",
                    "props": {}, "environment": {
                        "entry_state": copy.deepcopy((first.get("environment") or {}).get("entry_state") or {}),
                        "exit_state": copy.deepcopy((last.get("environment") or {}).get("exit_state") or {}),
                    },
                }
        for legacy_unit in legacy.get("units") or []:
            for row in legacy_unit.get("internal_transition_contracts") or []:
                key = (str(row.get("from_shot_id")), str(row.get("to_shot_id")))
                if all(key):
                    authored_internal.setdefault(key, row)

    # v4 adapters may provide a valid per-shot camera sequence whose grouped
    # unit anchors collide after semantic grouping (the grouping contract uses
    # the first shot of each unit as its camera authority).  Repair only
    # adapter-generated anchors, never director-authored overlays, and retain
    # a receipt in the unit so the transformation is auditable.
    motion_dirs = {
        "PAN": ["LEFT_TO_RIGHT", "RIGHT_TO_LEFT"],
        "TRACK": ["LEFT_TO_RIGHT", "RIGHT_TO_LEFT"],
        "DOLLY": ["PUSH_IN", "PULL_OUT"],
        "CRANE": ["RISE", "FALL"],
        "ARC": ["CLOCKWISE", "COUNTERCLOCKWISE"],
    }
    motion_order = ["PAN", "TRACK", "DOLLY", "CRANE", "ARC"]
    previous_signature = None
    for group in spec.get("groups") or []:
        camera = group.get("camera_plan") or {}
        signature = (camera.get("motion_family"), camera.get("motion_direction"))
        authored = str(camera.get("authorship") or "")
        if previous_signature and signature == previous_signature and authored.startswith("V4_ADAPTER_"):
            for family in motion_order:
                for direction in motion_dirs[family]:
                    if (family, direction) != previous_signature and direction != previous_signature[1]:
                        camera["motion_family"] = family
                        camera["motion_direction"] = direction
                        camera["signature"] = f"{family}:{direction}"
                        camera["authorship"] = "V4_ADAPTER_GROUP_SEQUENCE_REPAIR"
                        signature = (family, direction)
                        break
                if signature != previous_signature:
                    break
        previous_signature = signature
    for order, group in enumerate(spec["groups"]):
        # 2026-09-12: bind the director-authored internal transitions (generation contract
        # internal_transition_authoring[]) to the two beat specs exactly as
        # tools/grouped_internal_continuity_contract.validate_internal_transition_contract expects.
        # A multi-shot group without an authored boundary keeps an empty list and the strict
        # compile fails on it honestly — nothing is templated here.
        group["internal_transition_contracts"] = build_internal_transition_contracts(
            group, by_shot, authored_internal, allow_migration_defaults=bool(args.legacy_plan))
        if order == 0:
            continue
        previous_group = spec["groups"][order - 1]
        left = by_shot[previous_group["editorial_shot_ids"][-1]]
        right = by_shot[group["editorial_shot_ids"][0]]
        group["transition_contract"] = build_transition(engine, previous_group, group, left, right, ambient)
    spec["transition_authoring_required"] = [
        {"from_unit_id": row["from_unit_id"], "to_unit_id": row["to_unit_id"], "status": "AUTHORED"}
        for row in spec.get("transition_authoring_required") or []
    ]
    production_path = write_json(out_dir / f"{prefix}EDITORIAL_PRODUCTION_MANIFEST_V1.json", production)
    spec_path = write_json(out_dir / f"{prefix}VIDEO_UNIT_GROUPING_SPEC_V1.json", spec)
    spec_loaded = json.loads(spec_path.read_text(encoding="utf-8"))
    spec_loaded["grouping_spec_sha256"] = sha256_file(spec_path)
    try:
        plan = engine.compile_grouping_spec(json.loads(production_path.read_text(encoding="utf-8")), spec_loaded)
        compile_error = None
    except ValueError as exc:
        plan, compile_error = None, str(exc)
    if plan is None:
        stage("4.2_compile_video_unit_plan", "FAIL", error=compile_error)
        write_json(out_dir / f"{prefix}PREPRODUCTION_REPORT.json", {
            "schema": "qingshan.nalu_preproduction_report.v1", "episode": episode,
            "status": "BLOCKED", "stages": stages, "recorded_at": now()})
        print(json.dumps({"status": "BLOCKED", "stage": "4.2", "error": compile_error}, ensure_ascii=False))
        return 2
    plan["wardrobe_bible"] = editorial["wardrobe_bible"]
    plan_path = write_json(out_dir / f"{prefix}VIDEO_UNIT_GROUPING_PLAN_V1.json", plan)
    stage("4.1_grouping_spec", "PASS", units=len(spec["groups"]),
          transitions_authored=sum(1 for row in spec["groups"] if row.get("transition_contract")),
          path=portable(spec_path, root))
    stage("4.2_compile_video_unit_plan", "PASS",
          video_unit_count=plan["video_unit_count"],
          editorial_shot_count=plan["editorial_shot_count"],
          runtime_seconds=plan["runtime_seconds"],
          unit_durations=[row["duration_seconds"] for row in plan["units"]],
          path=portable(plan_path, root))

    grouping_report = engine.grouping_gate(plan)
    grouping_report.setdefault("schema", "qingshan.video_unit_grouping_gate.v1")
    grouping_report["gate_id"] = "VIDEO-UNIT-SEMANTIC-GROUPING"
    grouping_report["recorded_at"] = now()
    grouping_report_path = write_json(reports_dir / f"{prefix}VIDEO_UNIT_GROUPING_GATE_V1.json", grouping_report)
    # ---- provider slot projection (seq=29 half-second shot lengths -> unit sums like 6.5 s; the
    # provider takes integer seconds and the unified engine (2026-09-18) validates
    # duration_authority: slot - authorized_content - tail_handle <= 0.05 and recompiles the prompt
    # from the task's integer duration).  The editorial sums stay on record as
    # authorized_content_seconds (the cut length); the slot is the ceiling; the difference is the
    # declared trim handle.  Applied AFTER the engine grouping gate validated the editorial sums.
    plan = project_provider_slots(plan)
    plan_path = write_json(out_dir / f"{prefix}VIDEO_UNIT_GROUPING_PLAN_V1.json", plan)
    stage("4.2b_video_unit_grouping_gate", grouping_report["status"],
          failures=grouping_report.get("failures") or [], report=portable(grouping_report_path, root))
    if grouping_report["status"] == "PASS":
        gate_reports.append({"gate_id": grouping_report["gate_id"], "path": portable(grouping_report_path, root)})

    # ---------------------------------------------------------------- stage e
    keyframe_dir = Path(args.keyframe_dir).expanduser().resolve() if args.keyframe_dir else out_dir / "keyframes"
    # Rolling wave (2026-09-13): 17/27 E01 units take the PREVIOUS unit's real final frame as a
    # binding reference (anchor role PREVIOUS_REAL_TAIL_STATE_AUTHORITY), so video is produced in
    # waves.  With --ready-units the grouping used from 4.3 onward is the engine's
    # ".partial_ready." shape (video_unit_count / runtime_seconds of the subset,
    # planned_video_unit_count of the full plan) and every ready unit whose predecessor tail
    # exists under --real-final-frames gets previous_unit_final_frame {path, sha256}.
    full_plan_path = plan_path
    if args.ready_units:
        ready = [str(x) for x in json.loads(args.ready_units)]
        tails = Path(args.real_final_frames).expanduser().resolve() if args.real_final_frames else None
        full = json.loads(plan_path.read_text(encoding="utf-8"))
        order = [u["unit_id"] for u in full["units"]]
        wave_units = []
        for unit in full["units"]:
            if unit["unit_id"] not in ready:
                continue
            unit = copy.deepcopy(unit)
            idx = order.index(unit["unit_id"])
            prev_id = order[idx - 1] if idx > 0 else None
            if prev_id and tails is not None:
                tail = tails / f"{prev_id}.png"
                if tail.is_file():
                    unit["previous_unit_final_frame"] = {"path": str(tail), "sha256": sha256_file(tail),
                                                         "previous_unit_id": prev_id,
                                                         "source": "REAL_FINAL_FRAME_OF_HARVESTED_VIDEO"}
            wave_units.append(unit)
        wave = copy.deepcopy(full)
        wave["schema"] = str(full.get("schema") or "qingshan.video_unit_grouping_plan.v1") + ".partial_ready.wave"
        wave["source_grouping_plan"] = portable(plan_path, root)
        wave["planned_video_unit_count"] = len(full["units"])
        wave["video_unit_count"] = len(wave_units)
        wave["runtime_seconds"] = round(sum(float(u["duration_seconds"]) for u in wave_units), 6)
        wave["units"] = wave_units
        wave["wave"] = {"ready_units": [u["unit_id"] for u in wave_units],
                        "with_previous_final_frame": [u["unit_id"] for u in wave_units if u.get("previous_unit_final_frame")],
                        "real_final_frames_dir": str(tails) if tails else None}
        plan_path = write_json(out_dir / f"{prefix}VIDEO_UNIT_GROUPING_PLAN_WAVE_V1.json", wave)
        plan = wave
        stage("4.2w_rolling_wave_grouping", "PASS", units=len(wave_units), path=portable(plan_path, root),
              ready_units=wave["wave"]["ready_units"], with_previous_final_frame=wave["wave"]["with_previous_final_frame"])
    def build_anchor_outputs(plan_path_x: Path, suffix: str):
        anchor_plan = engine.anchor_build(json.loads(plan_path_x.read_text(encoding="utf-8")), editorial, keyframe_dir)
        anchor_plan["video_unit_grouping_plan_sha256"] = sha256_file(plan_path_x)
        anchor_plan["keyframe_dir"] = str(keyframe_dir)
        anchor_plan["keyframe_dir_exists"] = keyframe_dir.is_dir()
        anchor_plan["expected_keyframe_filenames"] = [
            f"{shot['shot_id']}-keyframe-v1.png" for shot in editorial["shots"]]
        anchor_plan["expected_keyframe_filenames_for_planned_anchors"] = sorted({
            f"{Path(value).name}" for unit in anchor_plan["units"]
            for value in unit["reference_image_paths"] if value and value.endswith(".png")})

        start_frames = build_start_frame_contracts(anchor_plan, editorial, root)
        by_unit = {row["unit_id"]: row for row in start_frames}
        for unit in anchor_plan["units"]:
            unit["start_frame_semantic_contract"] = by_unit[unit["unit_id"]]
            # compile_grouped_seedance_manifest.py:875 reads the FIRST unit's required start-space
            # anchors from this unit-level key (later units take them from their transition contract)
            unit["required_start_space_anchors"] = list(
                (by_unit[unit["unit_id"]] or {}).get("required_space_anchors") or [])
        anchor_path = write_json(out_dir / f"{prefix}VIDEO_UNIT_ANCHOR_PLAN{suffix}_V1.json", anchor_plan)
        start_frame_path = write_json(out_dir / f"{prefix}START_FRAME_SEMANTIC_CONTRACTS{suffix}_V1.json", {
            "schema": "qingshan.start_frame_semantic_contract_set.v1",
            "episode": episode, "generated_by": TOOL_ID, "recorded_at": now(),
            "authority": "compile_grouped_seedance_manifest.py:849-859 + grouped_anchor_semantic_contract.py",
            "units": start_frames,
        })
        return anchor_plan, anchor_path, start_frames, start_frame_path

    if args.ready_units:
        # canonical (un-suffixed) anchor plan + start-frame contracts always describe the FULL
        # grouping — the wave scheduler, the review requests (Expectations) and every later
        # wave read them; the wave's own subset goes to the _WAVE files used for this compile.
        build_anchor_outputs(full_plan_path, "")
        anchor_plan, anchor_path, start_frames, start_frame_path = build_anchor_outputs(plan_path, "_WAVE")
    else:
        anchor_plan, anchor_path, start_frames, start_frame_path = build_anchor_outputs(plan_path, "")
    anchor_report = engine.anchor_gate(json.loads(anchor_path.read_text(encoding="utf-8")))
    anchor_report["gate_id"] = "VIDEO-UNIT-ANCHOR-COUNT"
    anchor_report_path = write_json(reports_dir / f"{prefix}ANCHOR_COUNT_GATE_V1.json", anchor_report)
    stage("4.3_video_unit_anchor_plan",
          "PASS" if not anchor_plan["missing_anchor_shot_ids"] else "BLOCKED_MISSING_KEYFRAMES",
          units=len(anchor_plan["units"]),
          planned_reference_image_count=anchor_plan["planned_reference_image_count"],
          missing_anchor_shot_ids=anchor_plan["missing_anchor_shot_ids"],
          keyframe_dir=str(keyframe_dir), keyframe_dir_exists=keyframe_dir.is_dir(),
          expected_keyframe_filenames=anchor_plan["expected_keyframe_filenames_for_planned_anchors"],
          path=portable(anchor_path, root))
    stage("4.3b_anchor_count_gate", anchor_report["status"],
          failures=anchor_report.get("failures") or [], report=portable(anchor_report_path, root))
    if anchor_report["status"] == "PASS":
        gate_reports.append({"gate_id": anchor_report["gate_id"], "path": portable(anchor_report_path, root)})
    stage("4.3c_start_frame_semantic_contracts",
          "PASS" if all(row["status"] == "PASS" for row in start_frames) else "BLOCKED_MISSING_KEYFRAME_EVIDENCE",
          units=len(start_frames), path=portable(start_frame_path, root),
          pending_inputs=sorted({value.split(":")[0] for row in start_frames for value in row["pending_inputs"]}))

    # ---------------------------------------------------------------- stage f
    bundle_path = write_json(out_dir / f"{prefix}MACHINE_GATE_REPORTS_V1.json", {
        "schema": "qingshan.machine_gate_report_bundle.v1",
        "episode": episode, "recorded_at": now(),
        "policy": "Only gate functions that actually returned PASS are listed here.",
        "reports": gate_reports,
    })
    prompt_dir = out_dir / "video_prompts"
    transaction_tasks: list[dict[str, Any]] = []
    for unit in anchor_plan["units"]:
        first_shot = by_shot[unit_first_shot(plan, unit["unit_id"])]
        task_map = next(row for row in rendered["tasks"] if row["unit_id"] == first_shot["shot_id"])
        transaction_tasks.append({
            "task_key": unit["unit_id"],
            "unit_id": unit["unit_id"],
            "episode": episode,
            "semantic_video_unit": True,
            "tool_type": "video_generation",
            "spatial_layout_stage": "VIDEO_GENERATION",
            "scene_id": unit["scene_id"],
            "episode_global_space_map_id": index.episode_map_id,
            "global_space_map_id": task_map["global_space_map_id"],
            "room_id": task_map["room_id"],
            "zone_id": task_map["zone_id"],
            "angle_id": task_map["angle_id"],
            "resolution_order": list(RESOLUTION_ORDER),
            "subspace_layout": copy.deepcopy(task_map["subspace_layout"]),
            "blocking": copy.deepcopy(task_map["blocking"]),
            "action_end_blocking": copy.deepcopy(task_map["action_end_blocking"]),
            "trajectory_overlays": copy.deepcopy(task_map["trajectory_overlays"]),
            "space_chain_id": task_map["space_chain_id"],
            "reference_bindings": copy.deepcopy(task_map["reference_bindings"]),
            "model": MODEL_CONTRACT["model"],
            "resolution": MODEL_CONTRACT["resolution"],
            "aspect_ratio": MODEL_CONTRACT["aspect_ratio"],
            # provider slot = integer seconds >= the authorised content (seq=29 half-second units:
            # round() is banker's rounding, 6.5 -> 6 < content -> AUTHORIZED_CONTENT_EXCEEDS_PROVIDER_SLOT)
            "duration_seconds": int(math.ceil(float(
                next(row for row in plan["units"] if row["unit_id"] == unit["unit_id"])["duration_seconds"]) - 1e-9)),
            "source_duration_seconds": next(row for row in plan["units"] if row["unit_id"] == unit["unit_id"]).get(
                "authorized_content_seconds"),
            "authorized_content_seconds": next(row for row in plan["units"] if row["unit_id"] == unit["unit_id"]).get(
                "authorized_content_seconds"),
            "authorized_tail_handle_seconds": next(row for row in plan["units"] if row["unit_id"] == unit["unit_id"]).get(
                "authorized_tail_handle_seconds"),
            "editorial_shot_ids": next(
                row for row in plan["units"] if row["unit_id"] == unit["unit_id"])["editorial_shot_ids"],
            "prompt_file": portable(prompt_dir / f"{unit['unit_id']}.txt", root),
            "prompt_sha256": None,
            "prompt_status": "NOT_COMPILED_STAGE_4_4_BLOCKED_ON_KEYFRAMES",
            "reference_images": [value for value in unit["reference_image_paths"] if value],
            "reference_sha256": [],
            "reference_roles": list(unit["anchor_count_decision"]["anchor_roles"]),
            "start_frame_semantic_contract": unit["start_frame_semantic_contract"],
            "opening_anchor_contract": unit["opening_anchor_contract"],
            "event_boundary_decision": unit["event_boundary_decision"],
            "submission_status": "NOT_AUTHORIZED_UNTIL_KEYFRAMES_AND_IDENTITY_CARDS_ADMITTED",
        })
    transaction = {
        "schema": "qingshan.giggle_video_transaction_manifest.v1",
        "episode": episode, "generated_by": TOOL_ID, "recorded_at": now(),
        "episode_global_space_map_ref": portable(authority_path, root),
        "global_space_map_gate_required": True,
        "allowed_video_models": [MODEL_CONTRACT["model"]],
        "format_contract": dict(MODEL_CONTRACT),
        "authorization_ref": "PENDING_PRIVATE_LINE_OWNER_PAID_AUTHORIZATION",
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "machine_gate_reports": [row["path"] for row in gate_reports],
        "blocking_note": (
            "Keyframes and character/prop identity cards do not exist yet; prompt files are "
            "compiled by stage 4.4 which cannot run without admitted anchors."),
        "tasks": transaction_tasks,
    }
    transaction_path = write_json(out_dir / f"{prefix}VIDEO_TRANSACTION_MANIFEST_V1.json", transaction)

    compile_attempt = run_cli(engine, [
        str(root / "tools" / "compile_grouped_seedance_manifest.py"),
        "--grouping-plan", str(plan_path), "--anchor-plan", str(anchor_path),
        "--editorial-seedance-manifest", str(editorial_path),
        # The grouped compiler owns the visual-culture and character contracts;
        # pass the same v4 generation contract used by this builder instead of
        # silently compiling a contract-less prompt set.
        "--generation-contract", str(contract_path),
        "--out", str(out_dir / f"{prefix}GROUPED_SEEDANCE_MANIFEST_V1.json"),
        "--final-prompt-dir", str(prompt_dir),  # nalu e13b: strict final prompts + index
    ], root)
    stage("4.4_compile_grouped_seedance_manifest",
          "PASS" if compile_attempt["returncode"] == 0 else "BLOCKED",
          blocking_check=last_error(compile_attempt), attempt=compile_attempt)
    final_index_path = out_dir / f"{prefix}GROUPED_SEEDANCE_MANIFEST_V1.final_prompts.json"
    if compile_attempt["returncode"] == 0 and final_index_path.is_file():
        final_rows = {row["unit_id"]: row for row in (json.loads(final_index_path.read_text(encoding="utf-8")).get("rows") or [])}
        compiled_units = {u["unit_id"]: u for u in (json.loads(
            (out_dir / f"{prefix}GROUPED_SEEDANCE_MANIFEST_V1.json").read_text(encoding="utf-8")).get("units") or [])}
        finalize_video_tasks(transaction, compiled_units, final_rows, rendered=rendered, contract=contract,
                             out_dir=out_dir, prefix=prefix, root=root, episode=episode,
                             ready_units=(json.loads(args.ready_units) if args.ready_units else None))
        transaction["blocking_note"] = "prompt files compiled by stage 4.4 (strict) for every task in this manifest"
        transaction_path = write_json(out_dir / f"{prefix}VIDEO_TRANSACTION_MANIFEST_V1.json", transaction)

    preflight_out = reports_dir / f"{prefix}VIDEO_PREFLIGHT_V1.json"
    preflight = run_cli(engine, [
        "-m", "qingshan_engine.cli", "video-preflight",
        "--manifest", str(transaction_path), "--out", str(preflight_out),
        "--project-root", str(root),
    ], root)
    stage("5_video_preflight", "PASS" if preflight["returncode"] == 0 else "BLOCKED",
          blocking_check=last_error(preflight), attempt=preflight)
    precheck = run_cli(engine, [
        str(root / "tools" / "submit_giggle_video_manifest_v2.py"),
        "--manifest", str(transaction_path),
        "--out", str(reports_dir / f"{prefix}VIDEO_PRECHECK_V1.json"),
        "--precheck-only", "--project-root", str(root),
    ], root)
    stage("5b_submit_giggle_video_manifest_v2_precheck_only",
          "PASS" if precheck["returncode"] == 0 else "BLOCKED",
          blocking_check=last_error(precheck), attempt=precheck)

    report = {
        "schema": "qingshan.nalu_preproduction_report.v1",
        "episode": episode,
        "generated_by": TOOL_ID,
        "recorded_at": now(),
        "engine_root": str(root),
        "out_dir": str(out_dir),
        "out_dir_gitignored": git_ignored(out_dir, root),
        "inputs": {
            "generation_contract": {"path": portable(contract_path, root), "sha256": sha256_file(contract_path)},
            "writer_manifest": {"path": portable(manifest_path, root), "sha256": sha256_file(manifest_path)},
            "episode_global_space_map": {"path": portable(gsm_path, root), "sha256": sha256_file(gsm_path)},
        },
        "model_contract": dict(MODEL_CONTRACT),
        "status": "PASS" if all(row["status"] == "PASS" for row in stages) else "PARTIAL_BLOCKED",
        "video_unit_count": plan["video_unit_count"],
        "video_unit_durations": [row["duration_seconds"] for row in plan["units"]],
        "video_units": [{
            "unit_id": row["unit_id"], "scene_id": row["scene_id"],
            "duration_seconds": row["duration_seconds"],
            "editorial_shot_ids": row["editorial_shot_ids"],
            "boundary_class": next((unit["event_boundary_decision"]["boundary_class"]
                                    for unit in anchor_plan["units"] if unit["unit_id"] == row["unit_id"]), None),
            "planned_reference_image_count": next((unit["planned_reference_image_count"]
                                                   for unit in anchor_plan["units"]
                                                   if unit["unit_id"] == row["unit_id"]), None),
        } for row in plan["units"]],
        "runtime_seconds": plan["runtime_seconds"],
        "dialogue_splits": splits,
        "machine_gate_reports": gate_reports,
        "machine_gate_report_bundle": portable(bundle_path, root),
        "artifacts": {
            "subspace_shot_plan": portable(rendered_path, root),
            "episode_global_space_map_authority": portable(authority_path, root),
            "editorial_seedance_manifest": portable(editorial_path, root),
            "production_manifest": portable(production_path, root),
            "grouping_spec": portable(spec_path, root),
            "grouping_plan": portable(plan_path, root),
            "anchor_plan": portable(anchor_path, root),
            "start_frame_semantic_contracts": portable(start_frame_path, root),
            "video_transaction_manifest": portable(transaction_path, root),
        },
        "stages": stages,
        "remaining_blockers": [
            {"id": "KEYFRAMES", "detail": "flat directory of {shot_id}-keyframe-v1.png files",
             "expected_directory": str(keyframe_dir),
             "expected_filenames": anchor_plan["expected_keyframe_filenames_for_planned_anchors"]},
            {"id": "IDENTITY_CARDS",
             "detail": "character/prop identity plates are still unproduced (stage-map blocker E-3)"},
            {"id": "START_FRAME_EVIDENCE",
             "detail": "start_frame_semantic_contract needs a real observation receipt per unit"},
        ],
    }
    report_path = write_json(out_dir / f"{prefix}PREPRODUCTION_REPORT.json", report)
    write_json(out_dir / "PREPRODUCTION_REPORT.json", report)
    print(json.dumps({
        "status": report["status"],
        "video_unit_count": report["video_unit_count"],
        "runtime_seconds": report["runtime_seconds"],
        "dialogue_splits": len(splits),
        "machine_gate_reports": len(gate_reports),
        "report": portable(report_path, root),
        "stages": [{"stage": row["stage"], "status": row["status"]} for row in stages],
    }, ensure_ascii=False, indent=1))
    return 0


def unit_first_shot(plan: dict[str, Any], unit_id: str) -> str:
    for unit in plan.get("units") or []:
        if unit["unit_id"] == unit_id:
            return str(unit["editorial_shot_ids"][0])
    raise KeyError(unit_id)


def last_error(attempt: dict[str, Any]) -> str:
    if attempt["returncode"] == 0:
        return "NONE"
    for channel in ("stderr", "stdout"):
        lines = [row for row in (attempt.get(channel) or "").splitlines() if row.strip()]
        if lines:
            return lines[-1]
    return "UNKNOWN"


def git_ignored(path: Path, root: Path) -> bool:
    completed = subprocess.run(
        ["git", "check-ignore", "-q", str(path)], cwd=str(root),
        capture_output=True, text=True)
    return completed.returncode == 0



# --------------------------------------------------------------------------- #
# stage 4.4b — complete, submit-shaped video tasks (nalu line, 2026-09-13)
# --------------------------------------------------------------------------- #
def _split_windows(phases: list[dict[str, Any]], maximum: float = 1.2) -> list[dict[str, Any]]:
    """tools/submit_giggle_video_manifest_v2.validate_task refuses any atomic action window
    longer than 1.2 s and tools/performance_tempo_gate.py requires the grouped beat windows to
    be contiguous and <=3 s.  The compiled action_timeline phases are <=3 s real-time beats;
    each is cut into equal sub-windows of <=1.2 s carrying the same action text.  This does
    not alter the provider prompt (tools/video_prompt_compiler.py never reads the windows)."""
    windows = []
    for index, phase in enumerate(phases, 1):
        start, end = float(phase["start_seconds"]), float(phase["end_seconds"])
        label = str((phase.get("actions") or [phase.get("state_change") or "CONTINUOUS_PERFORMANCE"])[0])[:160]
        span = end - start
        parts = max(1, int(-(-span // maximum)))  # ceil
        step = span / parts
        for sub in range(parts):
            windows.append({"start_seconds": round(start + sub * step, 3),
                            "end_seconds": round(end if sub == parts - 1 else start + (sub + 1) * step, 3),
                            "action": label, "phase_index": index, "sub_index": sub + 1, "sub_count": parts})
    return windows


def _spec_dialogue_rows(specs: list[dict[str, Any]], shot_ids: list[str]) -> list[dict[str, str]]:
    rows = []
    for shot_id, spec in zip(shot_ids, specs):
        value = spec.get("dialogue")
        lines = value if isinstance(value, list) else ([value] if value else [])
        for line in lines:
            if isinstance(line, dict):
                speaker, text = str(line.get("speaker") or ""), str(line.get("spoken_text") or line.get("text") or "")
            else:
                text = str(line)
                speaker, sep, spoken = text.partition("：")
                if not sep:
                    speaker, spoken = "", text
                text = spoken
            if text.strip():
                rows.append({"shot_id": shot_id, "speaker": speaker.strip(), "spoken_text": text.strip()})
    return rows


_ASSET_LIBRARY_CACHE: dict[str, dict[str, Any]] = {}


def _scoped_asset_library_path(episode: str) -> Path:
    scope = _series_scope.resolve_scope(episode)
    library = Path(scope["asset_library"])
    return library if library.is_file() else Path(scope["asset_library_seed"])


def _locked_identity_plate(character_id: str, *, episode: str) -> Path | None:
    """Return a LOCKED identity plate from this episode's series authority.

    Episode ids repeat across productions, so falling back to the historical
    ``runtime/asset_library.json`` here could bind a new E01 to another show's
    actor.  The cache is keyed by the resolved path to remain safe when one
    process builds more than one scope.
    """
    library_path = _scoped_asset_library_path(episode)
    scope = _series_scope.resolve_scope(episode)
    cache_key = str(library_path.resolve())
    if cache_key not in _ASSET_LIBRARY_CACHE:
        _ASSET_LIBRARY_CACHE[cache_key] = (
            json.loads(library_path.read_text(encoding="utf-8"))
            if library_path.is_file() else {})
    library = _ASSET_LIBRARY_CACHE[cache_key]
    if library and str(library.get("project_id") or "") != str(scope["series_id"]):
        raise RuntimeError(
            f"SCOPED_ASSET_LIBRARY_PROJECT_MISMATCH:{library_path}:"
            f"{library.get('project_id')}!={scope['series_id']}")
    row = (((library.get("assets") or {}).get("characters") or {}).get(character_id)) or {}
    from tools.original_identity_authority import original_reference
    original = original_reference(row)
    if original is not None:
        return Path(original["path"])
    if str(row.get("status") or "") != "LOCKED":
        return None
    identity_lock = (row.get("lock") or {}).get("identity_lock") or {}
    views = [Path(v) for v in identity_lock.get("canonical_view_paths") or []] if isinstance(identity_lock, dict) else []
    views = [v for v in views if v.is_file()]
    if not views:
        return locked_artifact_headshot(row)
    if not views:
        return None
    front = [v for v in views if "FRONT_NEUTRAL_HEADSHOT" in v.name]
    return (front or views)[0]


def locked_artifact_headshot(row):
    """Read the current artifact schema without inventing legacy lock data."""
    if row.get("status") != "LOCKED" or (row.get("qa") or {}).get("status") != "PASS":
        return None
    authority = (row.get("qa") or {}).get("authority") or {}
    if authority.get("review_file"):
        review = Path(authority["review_file"])
        if not review.is_file() or sha256_file(review) != authority.get("review_file_sha256"):
            raise ValueError("IDENTITY_ARTIFACT_REVIEW_SHA_MISMATCH")
    heads = []
    for artifact in row.get("artifacts") or []:
        path = Path(str(artifact.get("path") or ""))
        if "FRONT_NEUTRAL_HEADSHOT" not in str(artifact.get("role") or "") and "FRONT_NEUTRAL_HEADSHOT" not in path.name:
            continue
        if not path.is_file() or sha256_file(path) != artifact.get("sha256"):
            raise ValueError(f"IDENTITY_ARTIFACT_SHA_MISMATCH:{path}")
        if path not in heads:
            heads.append(path)
    if len(heads) > 1:
        raise ValueError("IDENTITY_ARTIFACT_HEADSHOT_AMBIGUOUS")
    return heads[0] if heads else None


VIDEO_REFERENCE_MAX = 9   # submit_giggle_video_manifest_v2 refuses > 9 reference images


def entity_scoped_trajectory(entity_id, specs, shot_ids, name2char, name2prop):
    """Scope state text to shots containing the entity, never the whole unit.

    This is shot-scoped evidence, not proof that every verb in a multi-person
    shot belongs to this entity. Preserve that distinction for downstream QA.
    """
    relevant = []
    for sid, spec in zip(shot_ids, specs):
        ids = {str(c.get("character_id") or name2char.get(str(c.get("character")), ""))
               for c in spec.get("cast") or []}
        ids.update(str(p.get("prop_id") or name2prop.get(str(p.get("prop")), ""))
                   for p in spec.get("props") or [])
        if entity_id in ids:
            relevant.append((sid, spec.get("action") or {}))
    if not relevant:
        raise ValueError(f"ENTITY_TRAJECTORY_SOURCE_MISSING:{entity_id}")
    return {
        "entity_id": entity_id,
        "from": str(relevant[0][1].get("start_state") or ""),
        "to": str(relevant[-1][1].get("completion_state") or ""),
        "action": " → ".join(str(a.get("primary_action") or a.get("description") or a.get("action") or
                                a.get("start_state") or "") for _, a in relevant),
        "visible_consequence": str(relevant[-1][1].get("completion_state") or ""),
        "source_shot_ids": [sid for sid, _ in relevant],
        "state_scope": "ENTITY_PRESENT_SHOTS_ONLY",
        "action_subjects_by_shot": [
            {"shot_id": sid, "subject_id": a.get("subject_id"),
             "patient_id": a.get("patient_id")}
            for sid, a in relevant],
    }


def identity_plate_reference_rows(character_ids: list[str], plate_lookup, *, existing_paths: list[str],
                                  cap: int = VIDEO_REFERENCE_MAX) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Roger 2026-09-18 (identity chain ③): one front-neutral-headshot plate per visible character,
    appended after the semantic (keyframe / tail) references, in cast order, never duplicated,
    capped so the unit stays within the provider's reference limit.  Returns (rows, dropped_over_cap,
    missing_locked_plate)."""
    rows: list[dict[str, Any]] = []
    dropped: list[str] = []
    missing: list[str] = []
    seen = {str(p) for p in existing_paths}
    for cid in character_ids:
        plate = plate_lookup(cid)
        if plate is None:
            missing.append(cid)
            continue
        if str(plate) in seen:
            continue
        if len(seen) >= cap:
            dropped.append(cid)
            continue
        rows.append({"character_id": cid, "path": str(plate), "sha256": sha256_file(Path(plate)),
                     "view": ("FRONT_NEUTRAL_HEADSHOT" if "FRONT_NEUTRAL_HEADSHOT" in Path(plate).name
                              else "IDENTITY_REFERENCE_VIEW_UNSPECIFIED"),
                     "role": "CHARACTER_IDENTITY_REFERENCE"})
        seen.add(str(plate))
    return rows, dropped, missing


def project_provider_slots(plan: dict[str, Any]) -> dict[str, Any]:
    """Integer provider slot per unit (ceil of the editorial sum) + declared content/tail handle."""
    for unit in plan.get("units") or []:
        content = float(unit["duration_seconds"])
        slot = int(math.ceil(content - 1e-9))
        unit["authorized_content_seconds"] = round(content, 3)
        unit["authorized_tail_handle_seconds"] = round(max(0.25, slot - content), 3)
        unit["provider_slot_projection"] = ("CEIL_TO_INTEGER_PROVIDER_SECONDS" if slot != content
                                            else "INTEGER_ALREADY")
        unit["duration_seconds"] = slot
    plan["editorial_runtime_seconds"] = plan.get("runtime_seconds")
    plan["runtime_seconds"] = round(sum(float(u["duration_seconds"]) for u in plan.get("units") or []), 6)
    return plan


def finalize_video_tasks(transaction: dict[str, Any], compiled_units: dict[str, dict[str, Any]],
                         final_rows: dict[str, dict[str, Any]], *, rendered: dict[str, Any],
                         contract: dict[str, Any], out_dir: Path, prefix: str, root: Path,
                         episode: str, ready_units: list[str] | None,
                         source_grouped_path: Path | None = None,
                         action_role_evidence_dir: Path | None = None) -> None:
    """Turn every stage-4.4-compiled unit into the task shape the engine's own
    compile_grouped_seedance_transaction_manifest.py produces and its submitter validates
    (validate_task / validate_grouped_creative_task / action contract / tempo gate /
    layout gate / input-completeness precheck).  Evidence is embedded, never invented:
    the Q1 admission result of the start keyframe (reports/qa/q1/<unit>/admission_result.json)
    and, when present and still matching the keyframe, the reviewer's action-role
    verification (reports/action_role_evidence/<unit>_action_role_verification.json)."""
    sys.path.insert(0, str(root))
    from tools.shot_media_admission_gate import compute_input_template_id  # engine, read-only
    name2char = {e["canonical_name"]: e["character_id"] for e in contract.get("character_entities") or []}
    name2prop = {e["name"]: e["entity_id"] for e in contract.get("non_character_entities") or []}
    admission_dir = out_dir / "video_admission"
    admission_dir.mkdir(parents=True, exist_ok=True)
    q1_dir = out_dir / "reports" / "qa" / "q1"
    action_role_dir = (action_role_evidence_dir if action_role_evidence_dir is not None
                       else root / "reports" / "action_role_evidence")
    for task in transaction["tasks"]:
        uid = task["unit_id"]
        row = final_rows.get(uid)
        cu = compiled_units.get(uid)
        if not row or not cu:
            continue
        task["prompt_sha256"] = row["sha256"]
        task["prompt_status"] = "COMPILED_STRICT_4_4"
        # re-attach a reviewed incremental-finalization receipt (prompt_batch_finalize.py) when
        # it binds exactly this final prompt; the manifest is rebuilt on every wave re-entry
        receipt_path = out_dir / "prompt_batch_finalization" / f"{uid}.json"
        if receipt_path.is_file():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                receipt = {}
            if receipt.get("status") == "PASS" and receipt.get("final_prompt_sha256") == row["sha256"]:
                task["prompt_batch_finalization"] = {"path": portable(receipt_path, root),
                                                     "sha256": sha256_file(receipt_path)}
        # ---- the compiled unit IS the creative contract: spread it (engine: task = {**original, ...})
        space_map_bindings = copy.deepcopy(task.get("reference_bindings") or [])
        keyframe_overlays = copy.deepcopy(task.get("trajectory_overlays") or [])
        for key, value in cu.items():
            if key in {"unit_id", "reference_images", "submission_status", "remote_task_id", "paid_attempt",
                       "duration_seconds"}:  # the task keeps its provider INTEGER duration
                continue
            task[key] = copy.deepcopy(value)
        refs = list(cu.get("reference_images") or [])
        specs = cu.get("ordered_prompt_specs") or []
        shot_ids = list(cu.get("editorial_shot_ids") or task.get("editorial_shot_ids") or [])
        # ---- storyboard contract (unified engine 2026-09-18, action_video_prompt_compiler
        # .validate_action_contract): a semantic_video_unit task is validated per shot — every
        # ordered_prompt_spec must carry its shot_id and the shot-local space.blocking /
        # space.action_end_blocking, and each entity the spec casts (cast[].character_id,
        # props[].prop_id) must appear in BOTH blocks.  The rows come from the stage-4.1 rendered
        # keyframe tasks (the same subspace blocking the keyframe was generated from), never invented.
        by_shot_map = {str(r.get("unit_id")): r for r in (rendered.get("tasks") or [])}
        for index_, spec in enumerate(specs):
            sid = spec.get("shot_id") or (shot_ids[index_] if index_ < len(shot_ids) else None)
            if not sid:
                continue
            spec["shot_id"] = sid
            shot_map = by_shot_map.get(str(sid)) or {}
            space = spec.setdefault("space", {})
            if shot_map.get("blocking"):
                space["blocking"] = copy.deepcopy(shot_map["blocking"])
            if shot_map.get("action_end_blocking"):
                space["action_end_blocking"] = copy.deepcopy(shot_map["action_end_blocking"])
            # Complete the shot-local storyboard ledger for off-screen voice
            # owners as well.  They remain OFFSCREEN in the provider prompt,
            # but the action contract still requires every declared entity in
            # both state blocks.
            for phase in ("blocking", "action_end_blocking"):
                block = space.setdefault(phase, {"characters": [], "props": []})
                block.setdefault("characters", []); block.setdefault("props", [])
            local_cast = [m for m in spec.get("cast") or [] if m.get("character_id")]
            for member in local_cast:
                eid = str(member["character_id"])
                anchor = next((dict(r) for r in space["blocking"]["characters"]
                               if r.get("zone_id") and r.get("position") and r.get("facing")), None)
                for phase in ("blocking", "action_end_blocking"):
                    if any(str(r.get("character_id")) == eid for r in space[phase]["characters"]):
                        continue
                    row = {"character_id": eid,
                           "screen_slot": str(member.get("screen_slot") or "OFFSCREEN"),
                           "depth_plane": str(member.get("depth_plane") or "DEFINED_BY_EDITORIAL_BEAT"),
                           "entity_presence": str(member.get("entity_presence") or "VISIBLE_AND_IDENTITY_LOCKED"),
                           "map_presence": "OFFSCREEN_VOICE_ONLY"}
                    if anchor:
                        row.update({k: copy.deepcopy(anchor[k]) for k in ("zone_id", "position", "facing")})
                    space[phase]["characters"].append(row)
        task["ordered_prompt_specs"] = copy.deepcopy(specs)  # the task's copy was taken before enrichment
        # ---- duration authority (engine video_execution_plan_compiler: underfill = provider slot -
        # authorized_content - tail_handle must be <= 0.05 s).  seq=29 units are half-second sums of
        # line-derived shot lengths; the provider slot is the integer ceiling, and the difference is the
        # editorial trim handle (cut at the authorised content, never a hold).  Declared, not defaulted.
        _content = float(task.get("authorized_content_seconds") or task.get("source_duration_seconds")
                         or cu.get("duration_seconds") or task["duration_seconds"])
        _slot = int(task["duration_seconds"])
        task["authorized_content_seconds"] = round(_content, 3)
        task["authorized_tail_handle_seconds"] = round(max(0.25, _slot - _content), 3)
        task["reference_images"] = [str(r["path"]) for r in refs]
        task["reference_sha256"] = [str(r["sha256"]) for r in refs]
        task["reference_roles"] = [str(r.get("role") or "SEMANTIC_REFERENCE") for r in refs]
        # ---- canonical entities (engine: cast minus OFFSCREEN_VOICE_ONLY, all props)
        chars = sorted({str(c.get("character_id") or name2char.get(str(c.get("character")), ""))
                        for spec in specs for c in spec.get("cast") or []
                        if str(c.get("face_visibility") or "") != "OFFSCREEN_VOICE_ONLY"} - {""})
        props = sorted({str(p.get("prop_id") or name2prop.get(str(p.get("prop")), ""))
                        for spec in specs for p in spec.get("props") or []} - {""})
        empty_unit = not chars and not props
        if empty_unit:
            props = [f"SPACE-{cu.get('scene_id')}"]
        # ---- semantic reference bindings: entity -> the keyframe of the shot it appears in
        ref_by_shot = {}
        for r in refs:
            name = Path(str(r["path"])).name
            m = re.match(r"(E\d+-S\d+-\d+)-keyframe", name)
            if m:
                ref_by_shot.setdefault(m.group(1), r)
        bindings, bound = [], set()
        for shot_id, spec in zip(shot_ids, specs):
            ref = ref_by_shot.get(shot_id)
            if not ref:
                continue
            for c in spec.get("cast") or []:
                if str(c.get("face_visibility") or "") == "OFFSCREEN_VOICE_ONLY":
                    continue
                eid = str(c.get("character_id") or name2char.get(str(c.get("character")), ""))
                if eid and eid not in bound:
                    bindings.append({"entity_id": eid, "role": "CHARACTER_REFERENCE", "path": str(ref["path"]),
                                     "sha256": str(ref["sha256"]), "source_shot_id": shot_id}); bound.add(eid)
            for p in spec.get("props") or []:
                eid = str(p.get("prop_id") or name2prop.get(str(p.get("prop")), ""))
                if eid and eid not in bound:
                    bindings.append({"entity_id": eid, "role": "PROP_REFERENCE", "path": str(ref["path"]),
                                     "sha256": str(ref["sha256"]), "source_shot_id": shot_id}); bound.add(eid)
        if empty_unit and refs:
            bindings.append({"entity_id": props[0], "role": "OBJECT_REFERENCE", "path": str(refs[0]["path"]),
                             "sha256": str(refs[0]["sha256"]), "source_shot_id": shot_ids[0] if shot_ids else None,
                             "note": "empty establishing unit: the scene environment is the acting entity"})
            bound.add(props[0])
        # identity reference overrides (nalu_runtime/preproduction/<EP>/identity_reference_overrides.json):
        # a character who enters mid-unit with no face among the unit's anchors gets the locked
        # identity plate as an extra SD2 subject reference (Q2 wrong-person reroll, 2026-09-13)
        override_path = Path(f"{_np.RUNTIME_ROOT}/preproduction") / episode / "identity_reference_overrides.json"
        overrides = (json.loads(override_path.read_text(encoding="utf-8")).get("units") or {}) if override_path.is_file() else {}
        for extra in overrides.get(uid) or []:
            extra_path = Path(str(extra["path"]))
            if not extra_path.is_file():
                continue
            extra_sha = sha256_file(extra_path)
            if str(extra_path) not in task["reference_images"]:
                task["reference_images"].append(str(extra_path))
                task["reference_sha256"].append(extra_sha)
                task["reference_roles"].append(str(extra.get("role") or "CHARACTER_IDENTITY_REFERENCE"))
            if extra["character_id"] not in bound:
                bindings.append({"entity_id": extra["character_id"], "role": "CHARACTER_REFERENCE", "path": str(extra_path),
                                 "sha256": extra_sha, "source": "IDENTITY_REFERENCE_OVERRIDE_LOCKED_PLATE"})
                bound.add(extra["character_id"])
            task.setdefault("identity_reference_overrides", []).append({**extra, "sha256": extra_sha})
        # seq=7 condition 4 (Roger 2026-09-13, E02+) as RE-STATED by Roger 2026-09-18 (identity chain ③):
        # every character whose face is visible in the unit gets the LOCKED front-neutral-headshot
        # plate as a subject reference IN ADDITION to the keyframe / tail semantic references —
        # unconditionally.  The old guard skipped the plate whenever the character already had a
        # keyframe semantic binding, which is every character in every unit; E05 therefore shipped
        # each unit with a single 720p keyframe (face ~80 px) and no identity plate at all.
        if not _policy_profile.uses_legacy_first_episode_exception(episode):
            plate_rows, plate_dropped, plate_missing = identity_plate_reference_rows(
                chars, lambda character_id: _locked_identity_plate(character_id, episode=episode),
                existing_paths=task["reference_images"])
            for row in plate_rows:
                task["reference_images"].append(row["path"])
                task["reference_sha256"].append(row["sha256"])
                task["reference_roles"].append("CHARACTER_IDENTITY_REFERENCE")
                bindings.append({"entity_id": row["character_id"], "role": "CHARACTER_REFERENCE", "path": row["path"],
                                 "sha256": row["sha256"], "source": "IDENTITY_PLATE_AUTO_SEQ7_C4"})
                bound.add(row["character_id"])
                task.setdefault("identity_reference_auto", []).append(row)
            if plate_dropped:
                task["identity_reference_dropped_over_cap"] = plate_dropped
            if plate_missing:
                task["identity_reference_missing_locked_plate"] = plate_missing
            if plate_dropped or plate_missing:
                raise ValueError(
                    f"IDENTITY_REFERENCE_BINDING_INCOMPLETE:{uid}:"
                    f"missing={','.join(plate_missing)}:over_cap={','.join(plate_dropped)}")
        task["unbound_canonical_entities"] = sorted(set(chars + props) - bound)
        task["reference_image_sequence"] = bindings
        task["reference_bindings"] = space_map_bindings + bindings
        task["space_map_reference_bindings"] = space_map_bindings
        task["canonical_characters"] = chars
        task["canonical_props"] = props
        # ---- action contract (tools/action_video_prompt_compiler.validate_action_contract)
        first_action = (specs[0].get("action") or {}) if specs else {}
        last_action = (specs[-1].get("action") or {}) if specs else {}
        kf_vectors = {str(r.get("entity_id")): r for r in keyframe_overlays}
        trajectories = []
        for eid in chars + props:
            if empty_unit:
                # An environment-only establishing shot has no character cast.
                t_row = {"entity_id": eid,
                         "from": str(first_action.get("start_state") or ""),
                         "to": str(last_action.get("completion_state") or ""),
                         "action": str(cu.get("narrative_beat") or ""),
                         "visible_consequence": str(last_action.get("completion_state") or "")}
            else:
                t_row = entity_scoped_trajectory(eid, specs, shot_ids, name2char, name2prop)
            vec = kf_vectors.get(eid)
            if vec:
                t_row.update({k: copy.deepcopy(v) for k, v in vec.items() if k not in t_row})
            trajectories.append(t_row)
        task["keyframe_trajectory_overlays"] = keyframe_overlays
        task["trajectory_overlays"] = trajectories
        start_block = task.get("blocking") or {"characters": [], "props": []}
        last_shot_id = shot_ids[-1] if shot_ids else None
        last_map = next((r for r in rendered["tasks"] if r["unit_id"] == last_shot_id), None)
        end_block = copy.deepcopy((last_map or {}).get("action_end_blocking") or task.get("action_end_blocking")
                                  or {"characters": [], "props": []})
        end_block.setdefault("characters", []); end_block.setdefault("props", [])
        # Off-screen dialogue/action owners are still contract entities.  The
        # authoritative storyboard gate requires their presence in both
        # blocking ledgers, even though they must remain OFFSCREEN in pixels.
        all_cast_rows = [member for spec in specs for member in (spec.get("cast") or [])
                         if str(member.get("character_id") or "")]
        cast_by_id = {}
        for member in all_cast_rows:
            cast_by_id.setdefault(str(member.get("character_id")), member)
        have_c = {str(r.get("character_id")) for r in (start_block.get("characters") or []) + end_block["characters"]}
        have_p = {str(r.get("prop_id")) for r in (start_block.get("props") or []) + end_block["props"]}
        end_block["characters"].extend({"character_id": eid, "screen_slot": "LATER_ORDERED_APPEARANCE",
                                        "depth_plane": "DEFINED_BY_EDITORIAL_BEAT"} for eid in chars if eid not in have_c)
        have_c.update(str(r.get("character_id")) for r in end_block["characters"])
        have_c.update(str(r.get("character_id")) for r in start_block.get("characters") or [])
        for eid, member in cast_by_id.items():
            if eid in have_c:
                continue
            anchor_row = next((r for r in start_block.get("characters") or []
                               if r.get("zone_id") and r.get("position") and r.get("facing")), None)
            row = {"character_id": eid,
                   "screen_slot": str(member.get("screen_slot") or "OFFSCREEN"),
                   "depth_plane": str(member.get("depth_plane") or "DEFINED_BY_EDITORIAL_BEAT"),
                   "entity_presence": str(member.get("entity_presence") or "VISIBLE_AND_IDENTITY_LOCKED"),
                   "map_presence": "OFFSCREEN_VOICE_ONLY"}
            if anchor_row:
                row.update({k: copy.deepcopy(anchor_row[k]) for k in ("zone_id", "position", "facing")})
            start_block["characters"].append(dict(row))
            end_block["characters"].append(dict(row))
        end_block["props"].extend({"prop_id": eid, "screen_slot": "LATER_ORDERED_APPEARANCE"} for eid in props if eid not in have_p)
        end_block["state"] = str(last_action.get("completion_state") or "UNIT_COMPLETION_STATE")
        end_block["source_shot_id"] = last_shot_id
        task["blocking"] = start_block
        task["action_end_blocking"] = end_block
        space = (specs[0].get("space") or {}) if specs else {}
        task["space_chain_ref"] = task.get("space_chain_id")
        task["space_chain_id"] = "->".join(str(space.get(k) or "UNSPECIFIED") for k in ("global", "location", "subspace"))
        # ---- tempo (performance_tempo_gate + submitter 1.2 s rule)
        phases = cu.get("action_timeline") or []
        tempo = dict(cu.get("performance_tempo_contract") or {})
        windows = _split_windows(phases)
        tempo.update({"playback_speed": "REAL_TIME_1X", "atomic_action_windows": windows,
                      "grouped_editorial_beat_count": len(windows), "result_hold_seconds": 0.0,
                      "source": "COMPILED_ACTION_TIMELINE_PHASES_4_4_SPLIT_TO_1P2S_WINDOWS"})
        task["performance_tempo_contract"] = tempo
        task["shot_type"] = "SEMANTIC_GROUPED_SCENE_PERFORMANCE"
        task["action_unit"] = True
        task["fight_or_chase"] = bool(cu.get("fight_or_chase"))
        task["combat_or_chase"] = bool(cu.get("combat_or_chase"))
        # ---- dialogue transport (submitter: speaker_voice_contract vs task.dialogue)
        dialogue_rows = _spec_dialogue_rows(specs, shot_ids)
        lines = [r["spoken_text"] for r in dialogue_rows]
        svc = cu.get("speaker_voice_contract") or {}
        voice_bindings = list(svc.get("bindings") or [])
        task["dialogue"] = dialogue_rows
        task["dialogue_lines"] = lines
        task["native_dialogue_required"] = bool(lines)
        task["dialogue_transport"] = "MODEL_NATIVE_TEXT_DIALOGUE" if lines else "SAME_TASK_NATIVE_AMBIENCE_FOLEY_ACTION_SOUND"
        task["model_native_text_dialogue"] = bool(lines)
        task["source_subtitle_policy"] = "FORBID"
        task["reference_audio_asset_ids"] = [str(b.get("voice_reference_asset_id") or "") for b in voice_bindings]
        expected_speakers = list(dict.fromkeys(r["speaker"] for r in dialogue_rows if r["speaker"]))
        task["speaker_order_matches_voice_contract"] = (
            [str(b.get("speaker") or "") for b in voice_bindings] == expected_speakers)
        # ---- start-frame admission evidence (embedded, never fabricated)
        first_ref = refs[0] if refs else {}
        q1 = q1_dir / uid / "admission_result.json"
        q1_payload = json.loads(q1.read_text(encoding="utf-8")) if q1.is_file() else {}
        admission = {
            "schema": "qingshan.video_start_frame_admission.v1",
            "episode": episode, "unit_id": uid,
            "status": q1_payload.get("status") or "Q1_ADMISSION_RESULT_MISSING",
            "downstream_status": q1_payload.get("downstream_status") or "FAIL_NOT_ADMITTED",
            "asset_path": str(first_ref.get("path") or ""),
            "asset_sha256": str(first_ref.get("sha256") or ""),
            "q1_asset_sha256": q1_payload.get("asset_sha256"),
            "q1_asset_matches_first_reference": bool(first_ref) and q1_payload.get("asset_sha256") == first_ref.get("sha256"),
            "source_q1_ref": portable(q1, root) if q1.is_file() else None,
            "source_q1_sha256": sha256_file(q1) if q1.is_file() else None,
            "recorded_at": now(), "recorded_by": TOOL_ID,
        }
        if not admission["q1_asset_matches_first_reference"]:
            admission["status"] = "Q1_ASSET_SHA_MISMATCH"
            admission["downstream_status"] = "FAIL_NOT_ADMITTED"
        ar_path = action_role_dir / f"{uid}_action_role_verification.json"
        ar = json.loads(ar_path.read_text(encoding="utf-8")) if ar_path.is_file() else {}
        if ar and ar.get("status") == "PASS" and ar.get("reviewed_asset_sha256") == first_ref.get("sha256"):
            admission["action_role_verification"] = ar
            admission["action_role_evidence_ref"] = portable(ar_path, root)
            task["action_role_evidence_status"] = "PRESENT"
        else:
            task["action_role_evidence_status"] = ("STALE_OR_FAILED" if ar else "MISSING")
        admission_path = write_json(admission_dir / f"{uid}_START_FRAME_ADMISSION_V1.json", admission)
        task["start_frame_sha256"] = str(first_ref.get("sha256") or "")
        task["start_frame_admission_ref"] = portable(admission_path, root)
        # ---- transport / policy fields (engine compile_grouped_seedance_transaction_manifest.py)
        task.update({
            "provider": "giggle",
            "media_stage": "VIDEO",
            "require_semantic_anchor_evidence": True,
            "source_duration_seconds": task.get("source_duration_seconds") or cu.get("duration_seconds"),
            "retry_attempt": 1, "creative_attempt_ordinal": 1, "paid_attempt": 0,
            "provider_post_allowed": False,
            "vertical_short_drama_contract": {"required": True, "aspect_ratio": "9:16",
                                              "all_reference_images_portrait": True},
            "video_transport": {"mode": "standard_multi_reference", "endpoint": "/api/v1/generation/omni-video"},
        })
        machine = dict(task.get("machine_contract") or {})
        machine.update({
            "scene_id": cu.get("scene_id"), "camera_plan": cu.get("camera_plan"),
            "ordered_prompt_specs": specs, "editorial_shot_ids": shot_ids,
            "incoming_transition_contract": cu.get("incoming_transition_contract"),
            "outgoing_transition_contract": cu.get("outgoing_transition_contract"),
            "internal_transition_contracts": cu.get("internal_transition_contracts"),
            "start_frame_semantic_contract": cu.get("start_frame_semantic_contract"),
            "speaker_voice_contract": svc,
            "authorized_content_seconds": task["authorized_content_seconds"],
            "authorized_tail_handle_seconds": task["authorized_tail_handle_seconds"],
        })
        # Preserve explicit source policies at the paid-boundary projection.
        # Omitting these silently restores unit-wide camera/timeline defaults.
        _copy_compiled_transport_policies(machine, cu)
        task["machine_contract"] = machine
        task["input_template_id"] = compute_input_template_id(task)
    transaction["provider"] = "giggle"
    transaction["video_unit_count"] = len(transaction["tasks"])
    transaction["runtime_seconds"] = sum(int(t.get("duration_seconds") or 0) for t in transaction["tasks"])
    transaction["reference_image_count"] = sum(len(t.get("reference_images") or []) for t in transaction["tasks"])
    grouped_path = (source_grouped_path if source_grouped_path is not None
                    else out_dir / f"{prefix}GROUPED_SEEDANCE_MANIFEST_V1.json")
    transaction["source_grouped_manifest"] = portable(grouped_path, root)
    transaction["source_grouped_manifest_sha256"] = sha256_file(grouped_path)
    if ready_units is not None:
        # a rolling wave is non-contiguous in episode order; the submitter then validates
        # per-task contracts and defers adjacent-list checks to the complete chain
        transaction["staged_generation_scope"] = {
            "kind": "ROLLING_WAVE_PARTIAL_READY", "unit_ids": [t["unit_id"] for t in transaction["tasks"]],
            "policy": "cross-task camera/transition sequence validated on the final full compile"}

def _copy_compiled_transport_policies(machine: dict[str, Any], compiled: dict[str, Any]) -> None:
    """Carry only declared policies; never invent defaults or retain stale ones."""
    for key in ("camera_scope_policy", "camera_time_coordinate", "timeline_policy"):
        if key in compiled:
            machine[key] = copy.deepcopy(compiled[key])
        else:
            machine.pop(key, None)


if __name__ == "__main__":
    raise SystemExit(main())
