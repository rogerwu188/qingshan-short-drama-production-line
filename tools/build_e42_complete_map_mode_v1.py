#!/usr/bin/env python3
"""Build and lock E42's complete visual map chain before shot production.

This is a preproduction overlay; it does not rewrite Claude Writer's admitted
four-layer package.  It turns the v11 location/subspace contract into two
real top-down place maps, one episode overview and one per-shot subspace map,
then runs the registered fail-closed spatial gate over all 65 shots.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "workflow/claude_writer_agent/scripts"
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e42_v11_20260827"
ASSETS = ROOT / "artifacts/e42_v11/complete_map_mode_v1"
AUTH_TEMPLATE = PRODUCTION / "E42_V11_EPISODE_GLOBAL_SPACE_MAP_TEMPLATE_V1.json"
SHOT_PLAN = PRODUCTION / "E42_V11_COMPLETE_MAP_SHOT_PLAN_V1.json"
AUTH_LOCKED = PRODUCTION / "E42_V11_EPISODE_GLOBAL_SPACE_MAP_AUTHORITY_LOCKED_V1.json"
SHOT_PLAN_LOCKED = PRODUCTION / "E42_V11_COMPLETE_MAP_SHOT_PLAN_LOCKED_V1.json"
RENDER_RECEIPT = PRODUCTION / "E42_V11_COMPLETE_MAP_RENDER_RECEIPT_V1.json"
GATE_REPORT = ROOT / "qa/e42_v11_complete_map_mode/E42_V11_COMPLETE_MAP_MODE_GATE_V1.json"
LOCK_RECEIPT = PRODUCTION / "E42_V11_COMPLETE_MAP_MODE_LOCK_V1.json"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))
from _gen_e42_v11_data import S as SCENES  # noqa: E402
from tools.global_space_layout_gate import RESOLUTION_ORDER, evaluate_batch  # noqa: E402
from tools.render_global_space_map_assets import build, write_json  # noqa: E402

EPISODE_MAP_ID = "EGSM-E42-FEIBAICHI-BANQUET-AND-CURTAIN-PAVILION-V1"
PLACE_BY_LOCATION = {
    "LOC-JINGWANGFU-FEIBAICHI": "GSM-JINGWANGFU-FEIBAICHI-BANQUET-V1",
    "LOC-JINGWANGFU-FEIBAICHI-LIANGTING": "GSM-JINGWANGFU-FEIBAICHI-CURTAIN-PAVILION-V1",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def zone(zone_id: str, name: str, points: list[list[float]]) -> dict[str, Any]:
    return {"zone_id": zone_id, "name": name, "polygon": points}


def banquet_map() -> dict[str, Any]:
    zones = [
        zone("ZONE-BANQUET-FIRST-ROW", "首排与世子席", [[1, 2], [13, 2], [13, 9], [1, 9]]),
        zone("ZONE-BANQUET-LAST-ROW", "末排与西头席", [[15, 2], [29, 2], [29, 9], [15, 9]]),
        zone("ZONE-BANQUET-CENTRAL-AISLE", "席间通道", [[13, 2], [15, 2], [15, 18], [13, 18]]),
        zone("ZONE-BANQUET-WOMEN-CURTAIN", "女眷帘席", [[1, 11], [12, 11], [12, 18], [1, 18]]),
        zone("ZONE-BANQUET-MOON-GATE", "月洞门", [[25, 11], [31, 11], [31, 18], [25, 18]]),
        zone("ZONE-BANQUET-POND-EDGE", "飞白池水岸", [[0, 19], [32, 19], [32, 22], [0, 22]]),
    ]
    cameras = []
    axes = []
    for index, row in enumerate(zones):
        zid = row["zone_id"]
        aid = f"AXIS-{zid.removeprefix('ZONE-')}"
        cid = f"ANGLE-{zid.removeprefix('ZONE-')}-LOCKED"
        poly = row["polygon"]
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        axes.append({"axis_id": aid, "endpoint_a": [min(xs), cy], "endpoint_b": [max(xs), cy], "default_screen_direction": "WEST_LEFT_EAST_RIGHT", "crossing_policy": "NO_CROSS_WITHOUT_VISIBLE_REESTABLISH"})
        cameras.append({"angle_id": cid, "zone_id": zid, "position": [cx, max(min(ys) + 0.5, 0.5)], "facing": "north", "axis_id": aid, "screen_direction": "WEST_LEFT_EAST_RIGHT"})
    return {
        "global_space_map_id": PLACE_BY_LOCATION["LOC-JINGWANGFU-FEIBAICHI"],
        "map_version": 1, "name": "靖王府飞白池宴席完整空间",
        "coordinate_system": {"origin": "southwest", "x_axis": "east", "y_axis": "north", "unit": "m"},
        "overall_bounds": {"width": 32, "depth": 22}, "layout_image": {},
        "rooms": [{
            "room_id": "ROOM-FEIBAICHI-BANQUET-GARDEN", "zones": zones,
            "fixed_elements": [
                {"element_id": "FIXED-FEIBAICHI-WATER", "type": "pond", "zone_id": "ZONE-BANQUET-POND-EDGE", "position": [16, 21], "traversable": False},
                {"element_id": "FIXED-FIRST-ROW-TABLES", "type": "banquet_tables", "zone_id": "ZONE-BANQUET-FIRST-ROW", "position": [7, 6], "traversable": False},
                {"element_id": "FIXED-LAST-ROW-TABLES", "type": "banquet_tables", "zone_id": "ZONE-BANQUET-LAST-ROW", "position": [22, 6], "traversable": False},
                {"element_id": "FIXED-WOMEN-CURTAIN", "type": "curtain", "zone_id": "ZONE-BANQUET-WOMEN-CURTAIN", "position": [6, 15], "traversable": False},
                {"element_id": "FIXED-MOON-GATE", "type": "moon_gate", "zone_id": "ZONE-BANQUET-MOON-GATE", "position": [28, 15], "traversable": True},
            ],
            "entrances": [
                {"entrance_id": "ENTRY-BANQUET-SOUTH", "zone_id": "ZONE-BANQUET-CENTRAL-AISLE", "position": [14, 2]},
                {"entrance_id": "ENTRY-MOON-GATE", "zone_id": "ZONE-BANQUET-MOON-GATE", "position": [31, 15]},
            ],
            "axes": axes, "camera_positions": cameras,
        }],
        "scene_mappings": [
            {"scene_id": scene["scene_id"], "room_id": "ROOM-FEIBAICHI-BANQUET-GARDEN", "zone_ids": [row["zone_id"] for row in zones]}
            for scene in SCENES if scene["location_id"] == "LOC-JINGWANGFU-FEIBAICHI"
        ],
    }


def pavilion_map() -> dict[str, Any]:
    zones = [
        zone("ZONE-PAVILION-CURTAIN-OUTSIDE", "帘外陈迹位", [[0, 0], [6, 0], [6, 12], [0, 12]]),
        zone("ZONE-PAVILION-CURTAIN-LINE", "垂帘分界", [[6, 0], [8, 0], [8, 12], [6, 12]]),
        zone("ZONE-PAVILION-CURTAIN-INSIDE", "帘内静妃位", [[8, 0], [14, 0], [14, 12], [8, 12]]),
        zone("ZONE-PAVILION-WATER-EDGE", "水声入口", [[0, 12], [14, 12], [14, 15], [0, 15]]),
    ]
    axes = [
        {"axis_id": "AXIS-PAVILION-CURTAIN-NORMAL", "endpoint_a": [3, 6], "endpoint_b": [11, 6], "default_screen_direction": "CHENJI_LEFT_CURTAIN_RIGHT", "crossing_policy": "NEVER_CROSS_CURTAIN"},
        {"axis_id": "AXIS-PAVILION-WATER-SOUND", "endpoint_a": [0, 13.5], "endpoint_b": [14, 13.5], "default_screen_direction": "WEST_SOUND_TO_EAST", "crossing_policy": "SOUND_ONLY_NO_SIGHTLINE"},
    ]
    cameras = [
        {"angle_id": "ANGLE-PAVILION-OUTSIDE-LOCKED", "zone_id": "ZONE-PAVILION-CURTAIN-OUTSIDE", "position": [2, 2], "facing": "east", "axis_id": "AXIS-PAVILION-CURTAIN-NORMAL", "screen_direction": "CHENJI_LEFT_CURTAIN_RIGHT"},
        {"angle_id": "ANGLE-PAVILION-CURTAIN-LOCKED", "zone_id": "ZONE-PAVILION-CURTAIN-LINE", "position": [7, 2], "facing": "north", "axis_id": "AXIS-PAVILION-CURTAIN-NORMAL", "screen_direction": "CURTAIN_DIVIDES_FRAME"},
        {"angle_id": "ANGLE-PAVILION-INSIDE-HIDDEN", "zone_id": "ZONE-PAVILION-CURTAIN-INSIDE", "position": [11, 2], "facing": "west", "axis_id": "AXIS-PAVILION-CURTAIN-NORMAL", "screen_direction": "NO_VISIBLE_JINGFEI_FACE"},
        {"angle_id": "ANGLE-PAVILION-WATER-SOUND", "zone_id": "ZONE-PAVILION-WATER-EDGE", "position": [7, 13], "facing": "south", "axis_id": "AXIS-PAVILION-WATER-SOUND", "screen_direction": "WATER_CARRIES_SOUND_ONLY"},
    ]
    return {
        "global_space_map_id": PLACE_BY_LOCATION["LOC-JINGWANGFU-FEIBAICHI-LIANGTING"],
        "map_version": 1, "name": "飞白池东头垂帘凉亭完整空间",
        "coordinate_system": {"origin": "southwest", "x_axis": "east", "y_axis": "north", "unit": "m"},
        "overall_bounds": {"width": 14, "depth": 15}, "layout_image": {},
        "rooms": [{
            "room_id": "ROOM-FEIBAICHI-CURTAIN-PAVILION", "zones": zones,
            "fixed_elements": [
                {"element_id": "FIXED-PAVILION-CURTAIN", "type": "curtain", "zone_id": "ZONE-PAVILION-CURTAIN-LINE", "position": [7, 6], "traversable": False},
                {"element_id": "FIXED-PAVILION-STONE-RAIL", "type": "stone_rail", "zone_id": "ZONE-PAVILION-WATER-EDGE", "position": [7, 13.5], "traversable": False},
                {"element_id": "FIXED-PAVILION-INNER-TABLE", "type": "low_table", "zone_id": "ZONE-PAVILION-CURTAIN-INSIDE", "position": [11, 6], "traversable": False},
            ],
            "entrances": [
                {"entrance_id": "ENTRY-PAVILION-WEST", "zone_id": "ZONE-PAVILION-CURTAIN-OUTSIDE", "position": [0, 6]},
                {"entrance_id": "ENTRY-PAVILION-INNER", "zone_id": "ZONE-PAVILION-CURTAIN-INSIDE", "position": [14, 6]},
            ],
            "axes": axes, "camera_positions": cameras,
        }],
        "scene_mappings": [
            {"scene_id": scene["scene_id"], "room_id": "ROOM-FEIBAICHI-CURTAIN-PAVILION", "zone_ids": [row["zone_id"] for row in zones]}
            for scene in SCENES if scene["location_id"] == "LOC-JINGWANGFU-FEIBAICHI-LIANGTING"
        ],
    }


CHARACTERS = {
    "陈迹": "CHAR-E42-CHENJI", "春华": "CHAR-E42-CHUNHUA", "陈问宗": "CHAR-E42-CHENWENZONG",
    "陈问孝": "CHAR-E42-CHENWENXIAO", "静妃": "CHAR-E42-JINGFEI", "佘登科": "CHAR-E42-SHEDENGKE",
    "刘曲星": "CHAR-E42-LIUQUXING", "白鲤": "CHAR-E42-BAILI", "世子": "CHAR-E42-SHIZI",
    "文人甲": "CHAR-E42-WENREN-JIA",
    "文人乙": "CHAR-E42-WENREN-YI",
    "席间宾客若干": "CHAR-E42-BANQUET-GUESTS",
}
PROPS = {"杯": "PROP-E42-CUP", "帘": "PROP-E42-CURTAIN", "桌": "PROP-E42-BANQUET-TABLE", "信": "PROP-E42-LETTER", "图": "PROP-E42-ARSENAL-DRAWING"}

# The canonical uses omitted subjects and pronouns extensively.  Exact visible
# cast is therefore authored per shot; substring mining is not an admissible
# identity source for complete-map blocking.
VISIBLE_CAST_BY_SHOT = {
    "E42-S01-01": ["春华", "陈迹"], "E42-S01-02": ["陈迹"],
    "E42-S01-03": ["陈迹", "席间宾客若干"], "E42-S01-04": ["陈迹", "春华"],
    "E42-S01-05": ["春华", "陈迹"], "E42-S01-06": ["陈迹"],
    "E42-S02-01": ["文人甲", "陈问宗"], "E42-S02-02": ["陈问宗"],
    "E42-S02-03": ["文人乙", "陈问宗", "陈问孝"], "E42-S02-04": ["陈问宗"],
    "E42-S02-05": ["陈问孝"],
    "E42-S03-01": [], "E42-S03-02": [], "E42-S03-03": ["陈迹"], "E42-S03-04": [],
    "E42-S03-05": ["陈迹"], "E42-S03-06": ["陈迹"], "E42-S03-07": ["陈迹"], "E42-S03-08": [],
    "E42-S04-01": ["陈问孝"], "E42-S04-02": ["陈问孝"],
    "E42-S04-03": ["席间宾客若干"], "E42-S04-04": ["陈问孝"],
    "E42-S04-05": ["席间宾客若干"], "E42-S04-06": ["佘登科"],
    "E42-S05-01": [], "E42-S05-02": ["陈迹"], "E42-S05-03": ["陈迹"],
    "E42-S05-04": [], "E42-S05-05": ["陈迹"],
    "E42-S06-01": [], "E42-S06-02": [], "E42-S06-03": ["陈迹"], "E42-S06-04": [],
    "E42-S06-05": [], "E42-S06-06": ["陈迹"], "E42-S06-07": [],
    "E42-S07-01": ["佘登科"], "E42-S07-02": ["佘登科"],
    "E42-S07-03": ["席间宾客若干"], "E42-S07-04": ["席间宾客若干"],
    "E42-S07-05": ["刘曲星", "佘登科"], "E42-S07-06": ["白鲤"],
    "E42-S08-01": ["文人甲", "佘登科"], "E42-S08-02": ["席间宾客若干"],
    "E42-S08-03": ["文人乙", "刘曲星"], "E42-S08-04": ["佘登科"],
    "E42-S09-01": ["陈迹"], "E42-S09-02": ["陈迹"], "E42-S09-03": [],
    "E42-S09-04": ["陈迹"], "E42-S09-05": ["陈迹"], "E42-S09-06": [],
    "E42-S10-01": ["白鲤"], "E42-S10-02": ["白鲤"], "E42-S10-03": ["白鲤"],
    "E42-S10-04": ["席间宾客若干"], "E42-S10-05": ["白鲤"],
    "E42-S10-06": ["世子", "席间宾客若干"],
    "E42-S11-01": ["席间宾客若干"], "E42-S11-02": ["世子"], "E42-S11-03": ["世子"],
    "E42-S11-04": ["刘曲星"], "E42-S11-05": ["白鲤"], "E42-S11-06": ["陈迹"],
}


def placement_for(location: str, subspace: str) -> tuple[str, str, str, list[list[float]], str]:
    if location.endswith("LIANGTING"):
        if "SHUIMIAN" in subspace:
            return "ROOM-FEIBAICHI-CURTAIN-PAVILION", "ZONE-PAVILION-WATER-EDGE", "ANGLE-PAVILION-WATER-SOUND", [[1, 12.2], [13, 12.2], [13, 14.8], [1, 14.8]], "FIXED-PAVILION-STONE-RAIL"
        if "LIANNEI" in subspace:
            return "ROOM-FEIBAICHI-CURTAIN-PAVILION", "ZONE-PAVILION-CURTAIN-INSIDE", "ANGLE-PAVILION-INSIDE-HIDDEN", [[8.2, 1], [13.8, 1], [13.8, 11], [8.2, 11]], "FIXED-PAVILION-INNER-TABLE"
        if "LIAN" in subspace and "CHENJI" not in subspace:
            return "ROOM-FEIBAICHI-CURTAIN-PAVILION", "ZONE-PAVILION-CURTAIN-LINE", "ANGLE-PAVILION-CURTAIN-LOCKED", [[6.1, 1], [7.9, 1], [7.9, 11], [6.1, 11]], "FIXED-PAVILION-CURTAIN"
        return "ROOM-FEIBAICHI-CURTAIN-PAVILION", "ZONE-PAVILION-CURTAIN-OUTSIDE", "ANGLE-PAVILION-OUTSIDE-LOCKED", [[0.2, 1], [5.8, 1], [5.8, 11], [0.2, 11]], "FIXED-PAVILION-CURTAIN"
    if "NVJUAN" in subspace or "BAILI" in subspace:
        return "ROOM-FEIBAICHI-BANQUET-GARDEN", "ZONE-BANQUET-WOMEN-CURTAIN", "ANGLE-BANQUET-WOMEN-CURTAIN-LOCKED", [[1.2, 11.2], [11.8, 11.2], [11.8, 17.8], [1.2, 17.8]], "FIXED-WOMEN-CURTAIN"
    if "YUEDONGMEN" in subspace or "CHENJI" in subspace and "XISHOU" not in subspace:
        return "ROOM-FEIBAICHI-BANQUET-GARDEN", "ZONE-BANQUET-MOON-GATE", "ANGLE-BANQUET-MOON-GATE-LOCKED", [[25.2, 11.2], [30.8, 11.2], [30.8, 17.8], [25.2, 17.8]], "FIXED-MOON-GATE"
    if any(token in subspace for token in ("DIYIPAI", "QIANZHUO", "SHIZI", "CHENWEN")):
        return "ROOM-FEIBAICHI-BANQUET-GARDEN", "ZONE-BANQUET-FIRST-ROW", "ANGLE-BANQUET-FIRST-ROW-LOCKED", [[1.2, 2.2], [12.8, 2.2], [12.8, 8.8], [1.2, 8.8]], "FIXED-FIRST-ROW-TABLES"
    if "SHUIMIAN" in subspace or "FEIBAICHI" in subspace:
        return "ROOM-FEIBAICHI-BANQUET-GARDEN", "ZONE-BANQUET-POND-EDGE", "ANGLE-BANQUET-POND-EDGE-LOCKED", [[0.2, 19.2], [31.8, 19.2], [31.8, 21.8], [0.2, 21.8]], "FIXED-FEIBAICHI-WATER"
    return "ROOM-FEIBAICHI-BANQUET-GARDEN", "ZONE-BANQUET-LAST-ROW", "ANGLE-BANQUET-LAST-ROW-LOCKED", [[15.2, 2.2], [28.8, 2.2], [28.8, 8.8], [15.2, 8.8]], "FIXED-LAST-ROW-TABLES"


def main() -> int:
    contract_path = SCRIPTS / "E42_GENERATION_CONTRACT_v11.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    scene_by_id = {scene["scene_id"]: scene for scene in SCENES}
    flat = [(*row, scene) for scene in SCENES for row in scene["lines"]]
    assert len(contract["shots"]) == len(flat) == 65
    authority = {
        "schema": "qingshan.episode_global_space_map.v1", "episode": "E42",
        "episode_global_space_map_id": EPISODE_MAP_ID, "map_version": 1,
        "authority_ref": "ROGER-20260827-E42-COMPLETE-MAP-MODE", "status": "PENDING",
        "inheritance": {"mode": "COMPOSED", "note": "飞白池宴席继承 E41 地理语义但因 E41 缺正式地图图像，本集建立首个可继承的真实拓扑 authority；凉亭为本集新增地点。"},
        "map_image": {}, "space_maps": [banquet_map(), pavilion_map()],
    }
    tasks = []
    for shot, source in zip(contract["shots"], flat):
        text, _duration, speaker, _kind, camera, subspace, motion, _move_type, scene = source
        location = scene["location_id"]
        room, zid, angle, poly, fixed = placement_for(location, subspace)
        names = VISIBLE_CAST_BY_SHOT.get(shot["shot_id"])
        if names is None:
            raise ValueError(f"Missing exact visible-cast contract for {shot['shot_id']}")
        props = [word for word in PROPS if word in text or word in motion]
        center_x = sum(point[0] for point in poly) / len(poly)
        center_y = sum(point[1] for point in poly) / len(poly)
        characters = [
            {"character_id": CHARACTERS[name], "zone_id": zid, "position": [round(center_x + index * 0.35, 2), round(center_y, 2)], "facing": "camera_or_scene_partner"}
            for index, name in enumerate(names)
        ]
        prop_rows = [
            {"prop_id": PROPS[word], "zone_id": zid, "position": [round(center_x, 2), round(center_y + 0.45 + index * 0.3, 2)], "facing": "camera"}
            for index, word in enumerate(props)
        ]
        place_id = PLACE_BY_LOCATION[location]
        tasks.append({
            "task_key": f"{shot['shot_id']}-MAP-LOCK-V1", "unit_id": shot["shot_id"],
            "tool_type": "image_generation", "spatial_layout_stage": "SHOT_KEYFRAME",
            "scene_id": shot["scene_id"], "episode_global_space_map_id": EPISODE_MAP_ID,
            "global_space_map_id": place_id, "room_id": room, "zone_id": zid, "angle_id": angle,
            "resolution_order": RESOLUTION_ORDER,
            "subspace_layout": {
                "subspace_id": subspace, "derived_from_episode_global_space_map_id": EPISODE_MAP_ID,
                "derived_from_global_space_map_id": place_id, "room_id": room, "zone_ids": [zid],
                "angle_id": angle, "camera_position_id": angle,
                "axis_id": "AXIS-PAVILION-CURTAIN-NORMAL" if location.endswith("LIANGTING") and "SHUIMIAN" not in subspace else ("AXIS-PAVILION-WATER-SOUND" if location.endswith("LIANGTING") else f"AXIS-{zid.removeprefix('ZONE-')}"),
                "visible_fixed_element_ids": [fixed], "polygon": poly,
            },
            "blocking": {"resolved_after_subspace_lock": True, "characters": characters, "props": prop_rows},
            "action_end_blocking": {"characters": characters, "props": prop_rows},
            "trajectory_overlays": [], "entity_reference_bindings": [],
            "source_shot_contract": {"path": str(contract_path.relative_to(ROOT)), "sha256": sha(contract_path), "shot_id": shot["shot_id"], "camera": camera, "action": text, "completion_state": motion},
        })
    PRODUCTION.mkdir(parents=True, exist_ok=True)
    write_json(AUTH_TEMPLATE, authority)
    shot_plan = {
        "schema": "qingshan.complete_map_shot_plan.v1",
        "episode": "E42",
        "canonical_version": 11,
        "global_space_map_gate_required": True,
        "episode_global_space_map_ref": str(AUTH_LOCKED.relative_to(ROOT)),
        "tasks": tasks,
    }
    write_json(SHOT_PLAN, shot_plan)
    locked, plan, render_receipt = build(authority, shot_plan, ASSETS)
    write_json(AUTH_LOCKED, locked)
    write_json(SHOT_PLAN_LOCKED, plan)
    render_receipt.update({
        "authority_path": str(AUTH_LOCKED.relative_to(ROOT)), "authority_sha256": sha(AUTH_LOCKED),
        "shot_plan_path": str(SHOT_PLAN_LOCKED.relative_to(ROOT)), "shot_plan_sha256": sha(SHOT_PLAN_LOCKED),
    })
    write_json(RENDER_RECEIPT, render_receipt)
    gate = evaluate_batch(locked, plan["tasks"], episode="E42", required=False)
    GATE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    write_json(GATE_REPORT, gate)
    lock = {
        "schema": "qingshan.complete_map_mode_lock.v1", "episode": "E42", "canonical_version": 11,
        "status": "PASS" if gate["status"] == "PASS" else "FAIL",
        "policy": "E42+ non-bypassable complete visual map mode before keyframe READY or paid video submit.",
        "counts": {"episode_maps": 1, "place_maps": len(locked["space_maps"]), "shot_subspace_maps": len(plan["tasks"])},
        "authority": {"path": str(AUTH_LOCKED.relative_to(ROOT)), "sha256": sha(AUTH_LOCKED)},
        "shot_plan": {"path": str(SHOT_PLAN_LOCKED.relative_to(ROOT)), "sha256": sha(SHOT_PLAN_LOCKED)},
        "render_receipt": {"path": str(RENDER_RECEIPT.relative_to(ROOT)), "sha256": sha(RENDER_RECEIPT)},
        "gate_report": {"path": str(GATE_REPORT.relative_to(ROOT)), "sha256": sha(GATE_REPORT)},
        "generation_contract": {"path": str(contract_path.relative_to(ROOT)), "sha256": sha(contract_path)},
        "generation_rule": "Every E42 keyframe/video task must be derived from the locked shot plan and retain the exact episode/place/subspace path+SHA reference bindings.",
    }
    write_json(LOCK_RECEIPT, lock)
    print(json.dumps({"status": lock["status"], **lock["counts"], "lock": str(LOCK_RECEIPT.relative_to(ROOT))}, ensure_ascii=False))
    return 0 if lock["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
