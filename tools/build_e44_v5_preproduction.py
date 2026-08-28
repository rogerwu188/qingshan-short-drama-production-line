#!/usr/bin/env python3
"""Build E44 v5 complete-map, editorial and transition-bound video-unit plans.

This is a production overlay.  It never mutates the admitted writer package.
Every generated unit receives an authored camera plan, while every boundary
receives one deterministic transition contract shared by the two adjacent
units.  Prompt compilation remains blocked until semantic start frames exist.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "workflow/claude_writer_agent/scripts"
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
ASSETS = ROOT / "artifacts/e44_v5/complete_map_mode_v1"
QA = ROOT / "qa/e44_v5_preproduction_20260828"
CONTRACT = SCRIPTS / "E44_GENERATION_CONTRACT_v5.json"
CANONICAL = SCRIPTS / "E44_NARRATIVE_CANONICAL_v5.md"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))
from _gen_e44_v5_data import S as SCENES  # noqa: E402
from tools.build_video_unit_grouping_spec import partition_scene  # noqa: E402
from tools.compile_video_unit_plan import compile_grouping_spec  # noqa: E402
from tools.global_space_layout_gate import RESOLUTION_ORDER, evaluate_batch  # noqa: E402
from tools.grouped_transition_contract import boundary_id  # noqa: E402
from tools.grouped_internal_continuity_contract import internal_boundary_id  # noqa: E402
from tools.render_global_space_map_assets import build as render_maps  # noqa: E402
from tools.video_unit_grouping_gate import evaluate as evaluate_grouping  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def zone(zone_id: str, name: str, x0: float, y0: float, x1: float, y1: float) -> dict[str, Any]:
    return {"zone_id": zone_id, "name": name, "polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


MAP_DEFS = {
    "LOC-ZHENGHEJIE": (
        "GSM-E44-ZHENGHE-STREET-V1", "ROOM-E44-ZHENGHE-STREET", 32, 14,
        [
            zone("ZONE-STREET-NOODLE-EAVE", "穆新斋外檐与门槛", 25, 0, 32, 4),
            zone("ZONE-STREET-CENTER", "政和街街心", 5, 4, 25, 10),
            zone("ZONE-STREET-DARK-END", "街尾暗处", 0, 4, 5, 10),
            zone("ZONE-STREET-NORTH-LINE", "城北视线方向", 5, 10, 25, 14),
        ],
    ),
    "LOC-TAIPING-YIGUAN-MENKOU": (
        "GSM-E44-TAIPING-CLINIC-DOOR-V1", "ROOM-E44-CLINIC-DOOR", 14, 10,
        [
            zone("ZONE-CLINIC-OUTSIDE", "门外金猪位与草鞋落点", 0, 0, 14, 4),
            zone("ZONE-CLINIC-DOOR", "门板门闩与门槛", 3, 4, 11, 6),
            zone("ZONE-CLINIC-INSIDE", "门内陈迹位", 3, 6, 11, 10),
        ],
    ),
    "LOC-TAIPING-YIGUAN-HOUYUAN": (
        "GSM-E44-TAIPING-CLINIC-COURTYARD-V1", "ROOM-E44-CLINIC-COURTYARD", 20, 16,
        [
            zone("ZONE-COURTYARD-WALL-ROOT", "北墙墙根与白霜", 0, 12, 20, 16),
            zone("ZONE-COURTYARD-VEGETABLE", "菜畦与白鲤落点", 0, 0, 7, 8),
            zone("ZONE-COURTYARD-STONE-TABLE", "石桌与银花生", 7, 3, 13, 9),
            zone("ZONE-COURTYARD-LADDER", "靠墙木梯", 13, 6, 20, 16),
            zone("ZONE-COURTYARD-HALL-DOOR", "正堂开门与门内声向", 13, 0, 20, 6),
        ],
    ),
    "LOC-TAIPING-YIGUAN-ZHENGTANG": (
        "GSM-E44-TAIPING-CLINIC-HALL-V1", "ROOM-E44-CLINIC-HALL", 18, 12,
        [
            zone("ZONE-HALL-LONG-TABLE", "正堂长案与水碗", 4, 2, 14, 7),
            zone("ZONE-HALL-MEDICINE-CABINET", "药柜与陈迹退身位", 14, 2, 18, 10),
            zone("ZONE-HALL-DOOR", "门后斗笠木钉与院门声向", 0, 0, 4, 7),
            zone("ZONE-HALL-BEAM", "房梁阴影位", 0, 7, 18, 12),
            zone("ZONE-HALL-OIL-LAMP", "油灯与案面规则手势", 4, 7, 14, 10),
        ],
    ),
    "LOC-ZHENGHEJIE-MUXINZHAI": (
        "GSM-E44-MUXINZHAI-NOODLE-HOUSE-V1", "ROOM-E44-MUXINZHAI", 18, 14,
        [
            zone("ZONE-NOODLE-TABLE", "堂中长桌", 2, 2, 12, 7),
            zone("ZONE-NOODLE-STOVE", "灶口与蒸汽", 12, 2, 18, 9),
            zone("ZONE-NOODLE-BOWL-STACK", "空碗摞", 0, 7, 6, 11),
            zone("ZONE-NOODLE-COUNTER", "掌柜收钱位", 6, 7, 12, 11),
            zone("ZONE-NOODLE-DOOR", "面馆门口", 0, 11, 18, 14),
        ],
    ),
}

EPISODE_MAP_ID = "EGSM-E44-MUXINZHAI-TO-TAIPING-YIGUAN-V1"
GLOBAL_SPACE = "GLOBAL-SPACE-E44-MUXINZHAI-ZHENGHEJIE-TAIPING-YIGUAN-YOUSHIMO-TO-ZIYE"

CHAR_IDS = {
    name: f"CHAR-E44-{token}" for name, token in {
        "陈迹": "CHENJI", "白鲤": "BAILI", "世子": "SHIZI", "小和尚": "XIAOHESHANG",
        "金猪": "JINZHU", "朱灵韵": "ZHULINGYUN", "梁猫儿": "LIANGMAOER",
        "梁狗儿": "LIANGGOUER", "乌云": "WUYUN", "佘登科": "SHEDENGKE",
        "刘曲星": "LIUQUXING",
    }.items()
}
PROP_IDS = {
    "碗": "PROP-E44-BOWL", "荷包": "PROP-E44-PURSE", "金瓜子": "PROP-E44-GOLD-SEED",
    "银锭": "PROP-E44-SILVER-INGOT", "银子": "PROP-E44-SILVER-INGOT",
    "白霜": "PROP-E44-WALL-FROST", "白粉": "PROP-E44-WALL-FROST",
    "刀背": "PROP-E44-KNIFE", "竹筒": "PROP-E44-BAMBOO-TUBE",
    "门板": "PROP-E44-DOOR", "门闩": "PROP-E44-DOOR-BAR", "斗笠": "PROP-E44-BAMBOO-HAT",
    "草鞋": "PROP-E44-STRAW-SANDALS", "药柜": "PROP-E44-MEDICINE-CABINET",
    "油灯": "PROP-E44-OIL-LAMP", "梯子": "PROP-E44-LADDER",
    "银花生": "PROP-E44-SILVER-PEANUT", "石桌": "PROP-E44-STONE-TABLE",
}

SCREEN_SLOT_BY_CHARACTER = {
    "陈迹": "CENTER_LEFT", "金猪": "CENTER_RIGHT", "白鲤": "LEFT_THIRD",
    "世子": "RIGHT_THIRD", "小和尚": "FAR_RIGHT", "朱灵韵": "FAR_LEFT",
    "梁猫儿": "FOREGROUND_LEFT", "梁狗儿": "FOREGROUND_RIGHT",
    "佘登科": "BACKGROUND_LEFT", "刘曲星": "BACKGROUND_RIGHT",
    "乌云": "GROUND_FOREGROUND",
}

# Map blocking must remain attached to identity, never to the order in which a
# shot happens to list its cast.  An earlier enumerate(cast) implementation
# swapped Chen Ji and the heir whenever the same two names appeared in reverse
# narrative order, which then looked like an identity-changing match cut.
SCREEN_SLOT_X_OFFSET = {
    "FAR_LEFT": -0.48,
    "FOREGROUND_LEFT": -0.40,
    "LEFT_THIRD": -0.28,
    "BACKGROUND_LEFT": -0.20,
    "CENTER_LEFT": -0.10,
    "GROUND_FOREGROUND": 0.0,
    "CENTER_RIGHT": 0.10,
    "BACKGROUND_RIGHT": 0.20,
    "RIGHT_THIRD": 0.28,
    "FOREGROUND_RIGHT": 0.40,
    "FAR_RIGHT": 0.48,
}

# E44 does not permit text inference or a generic fallback to invent a face.
# Every visible identity is director-authored per shot.  Dialogue speakers not
# in this table are added separately as OFFSCREEN_VOICE_ONLY.
VISIBLE_CAST_BY_SHOT = {
    "E44-S01-01": ["世子", "小和尚"], "E44-S01-02": ["世子"],
    "E44-S01-03": ["世子"], "E44-S01-04": ["小和尚", "世子"],
    "E44-S01-05": ["世子", "小和尚"],
    "E44-S02-01": ["世子"], "E44-S02-02": ["白鲤"],
    "E44-S02-03": ["白鲤", "陈迹", "世子"], "E44-S02-04": ["白鲤"],
    "E44-S02-05": ["陈迹", "世子", "白鲤"],
    "E44-S03-01": ["陈迹", "白鲤", "梁猫儿"],
    "E44-S03-02": ["世子", "陈迹"], "E44-S03-03": ["世子", "陈迹"],
    "E44-S03-04": ["陈迹", "世子"], "E44-S03-05": ["世子", "陈迹"],
    "E44-S04-01": ["陈迹", "白鲤", "梁猫儿"],
    "E44-S04-02": ["世子", "小和尚"], "E44-S04-03": ["小和尚", "世子"],
    "E44-S04-04": ["世子", "小和尚"],
    "E44-S05-01": [], "E44-S05-02": ["陈迹"], "E44-S05-03": ["陈迹"],
    "E44-S05-04": ["陈迹"], "E44-S05-05": ["陈迹"], "E44-S05-06": ["乌云"],
    "E44-S06-01": [], "E44-S06-02": ["陈迹"], "E44-S06-03": [],
    "E44-S06-04": [], "E44-S06-05": ["陈迹"], "E44-S06-06": ["陈迹"],
    "E44-S07-01": ["金猪"], "E44-S07-02": ["金猪"],
    "E44-S07-03": ["金猪", "陈迹"], "E44-S07-04": ["金猪", "陈迹"],
    "E44-S07-05": ["陈迹", "金猪"], "E44-S07-06": ["金猪", "陈迹"],
    "E44-S07-07": ["金猪", "陈迹"],
    "E44-S08-01": ["金猪", "陈迹"], "E44-S08-02": ["陈迹", "金猪"],
    "E44-S08-03": ["金猪", "陈迹"], "E44-S08-04": ["金猪", "陈迹"],
    "E44-S08-05": ["陈迹", "金猪"], "E44-S08-06": ["陈迹", "金猪"],
    "E44-S09-01": ["金猪", "陈迹"], "E44-S09-02": ["金猪", "陈迹"],
    "E44-S09-03": ["陈迹", "金猪"], "E44-S09-04": ["金猪", "陈迹"],
    "E44-S09-05": ["金猪", "陈迹"], "E44-S09-06": [],
    "E44-S09-07": ["金猪", "陈迹"],
    "E44-S10-01": ["白鲤"], "E44-S10-02": ["白鲤"], "E44-S10-03": ["白鲤"],
    "E44-S10-04": ["白鲤", "陈迹"], "E44-S10-05": ["白鲤", "陈迹"],
    "E44-S10-06": ["白鲤", "朱灵韵", "世子", "小和尚"], "E44-S10-07": [],
    "E44-S11-01": ["朱灵韵", "陈迹", "白鲤"],
    "E44-S11-02": ["白鲤", "朱灵韵", "陈迹"],
    "E44-S11-03": ["世子", "朱灵韵", "白鲤", "陈迹"],
    "E44-S11-04": ["朱灵韵"], "E44-S11-05": ["陈迹", "白鲤"],
    "E44-S11-06": ["陈迹", "白鲤"], "E44-S11-07": ["陈迹", "梁猫儿", "世子"],
    "E44-S12-01": ["金猪", "陈迹"], "E44-S12-02": ["金猪", "陈迹"],
    "E44-S12-03": ["金猪", "陈迹"], "E44-S12-04": ["金猪", "陈迹"],
    "E44-S12-05": [], "E44-S12-06": ["陈迹", "金猪"],
}


def place_map(location: str) -> dict[str, Any]:
    map_id, room_id, width, depth, zones = MAP_DEFS[location]
    axes, cameras, fixed = [], [], []
    for row in zones:
        xs = [p[0] for p in row["polygon"]]
        ys = [p[1] for p in row["polygon"]]
        cx, cy = sum(xs) / 4, sum(ys) / 4
        suffix = row["zone_id"].removeprefix("ZONE-")
        axes.append({
            "axis_id": f"AXIS-{suffix}", "endpoint_a": [min(xs), cy], "endpoint_b": [max(xs), cy],
            "default_screen_direction": "WEST_LEFT_EAST_RIGHT",
            "crossing_policy": "NO_CROSS_WITHOUT_VISIBLE_REESTABLISH",
        })
        cameras.append({
            "angle_id": f"ANGLE-{suffix}-LOCKED", "zone_id": row["zone_id"],
            "position": [cx, min(ys) + 0.4], "facing": "north", "axis_id": f"AXIS-{suffix}",
            "screen_direction": "WEST_LEFT_EAST_RIGHT",
        })
        fixed.append({
            "element_id": f"FIXED-{suffix}", "type": "location_anchor", "zone_id": row["zone_id"],
            "position": [cx, cy], "traversable": True,
        })
    return {
        "global_space_map_id": map_id, "map_version": 1, "name": location,
        "coordinate_system": {"origin": "southwest", "x_axis": "east", "y_axis": "north", "unit": "m"},
        "overall_bounds": {"width": width, "depth": depth}, "layout_image": {},
        "rooms": [{
            "room_id": room_id, "zones": zones, "fixed_elements": fixed,
            "entrances": [{"entrance_id": f"ENTRY-{room_id}", "zone_id": zones[0]["zone_id"], "position": [0, 1]}],
            "axes": axes, "camera_positions": cameras,
        }],
        "scene_mappings": [{
            "scene_id": scene["scene_id"], "room_id": room_id,
            "zone_ids": [row["zone_id"] for row in zones],
        } for scene in SCENES if scene["location_id"] == location],
    }


def zone_for(location: str, subspace: str) -> str:
    tests = {
        "LOC-ZHENGHEJIE": [
            (("JIEWEI", "ANCHU"), "ZONE-STREET-DARK-END"),
            (("JIEKOU", "MENKOU"), "ZONE-STREET-NOODLE-EAVE"),
            (("CHENGBEI",), "ZONE-STREET-NORTH-LINE"),
            (("JIE", "SHIZI", "XIAOHESHANG"), "ZONE-STREET-CENTER"),
        ],
        "LOC-TAIPING-YIGUAN-MENKOU": [
            (("MENWAI", "DOULI", "CAOXIE", "JINZHU"), "ZONE-CLINIC-OUTSIDE"),
            (("MENBAN", "MENSHUAN", "MENKOU"), "ZONE-CLINIC-DOOR"),
            (("MENNEI", "CHENJI"), "ZONE-CLINIC-INSIDE"),
        ],
        "LOC-TAIPING-YIGUAN-HOUYUAN": [
            (("QIANGGEN", "QIANGTOU", "FANBAI", "GUAQIANG", "WUYUN"), "ZONE-COURTYARD-WALL-ROOT"),
            (("CAIQI",), "ZONE-COURTYARD-VEGETABLE"),
            (("SHIZHUO", "YINHUASHENG"), "ZONE-COURTYARD-STONE-TABLE"),
            (("TIZI", "PATI"), "ZONE-COURTYARD-LADDER"),
            (("TANGWU", "MENKAI"), "ZONE-COURTYARD-HALL-DOOR"),
        ],
        "LOC-TAIPING-YIGUAN-ZHENGTANG": [
            (("FANGLIANG", "LUOLIANG", "YING"), "ZONE-HALL-BEAM"),
            (("DOULI", "MENHOU", "YUANZI"), "ZONE-HALL-DOOR"),
            (("YAO", "TUI", "BEITIE"), "ZONE-HALL-MEDICINE-CABINET"),
            (("YOUDENG",), "ZONE-HALL-OIL-LAMP"),
            (("ZHENGTANG", "AN", "SHOUZHI", "JINZHU", "CHENJI"), "ZONE-HALL-LONG-TABLE"),
        ],
        "LOC-ZHENGHEJIE-MUXINZHAI": [
            (("KONGWAN", "WANLUO"), "ZONE-NOODLE-BOWL-STACK"), (("ZHANGGUI",), "ZONE-NOODLE-COUNTER"),
            (("ZAO",), "ZONE-NOODLE-STOVE"), (("MEN",), "ZONE-NOODLE-DOOR"),
            (("MUXINZHAI",), "ZONE-NOODLE-TABLE"),
        ],
    }
    for tokens, zone_id in tests[location]:
        if any(token in subspace for token in tokens):
            return zone_id
    return MAP_DEFS[location][4][0]["zone_id"]


def visible_cast(shot: dict[str, Any]) -> list[str]:
    shot_id = shot["shot_id"]
    if shot_id not in VISIBLE_CAST_BY_SHOT:
        raise ValueError(f"missing director-authored visible cast contract: {shot_id}")
    return VISIBLE_CAST_BY_SHOT[shot_id]


def visible_props(shot: dict[str, Any]) -> list[str]:
    text = f"{shot.get('frame_content', '')} {shot.get('dialogue', '')} {shot.get('first_frame_motion_state', '')}"
    return list(dict.fromkeys(PROP_IDS[word] for word in PROP_IDS if word in text))


def playable_completion(shot: dict[str, Any]) -> str:
    """Convert source-faithful stillness into one visible, non-looping reaction.

    Narrative non-understanding is a result, not a direction to freeze actors.
    The completion keeps that result while giving Seedance a causal action path.
    """
    completion = str(shot.get("first_frame_motion_state") or shot["frame_content"])
    if "保持不动" in completion:
        return (
            "众人先在话音落点停顿半拍，目光各自错向邻座；"
            "一人扇面落低、另一人杯箸碰案，各自停在新的位置"
        )
    return completion


def build_complete_map(source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    authority = {
        "schema": "qingshan.episode_global_space_map.v1", "episode": "E44",
        "episode_global_space_map_id": EPISODE_MAP_ID, "map_version": 1,
        "authority_ref": "ROGER-20260828-E44-COMPLETE-MAP-MODE", "status": "PENDING",
        "inheritance": {"mode": "COMPOSED", "note": "穆新斋与政和街继承 E43 已验收拓扑语义；太平医馆门口、后院与正堂依 E44 v5 完整补图并统一轴线。"},
        "map_image": {}, "space_maps": [place_map(location) for location in MAP_DEFS],
    }
    scene_by_id = {row["scene_id"]: row for row in source["scene_states"]}
    tasks = []
    for shot in source["shots"]:
        scene = scene_by_id[shot["scene_id"]]
        location, subspace = scene["location_id"], shot["subspace_id"]
        map_id, room_id, _w, _d, zones = MAP_DEFS[location]
        zid = zone_for(location, subspace)
        z = next(row for row in zones if row["zone_id"] == zid)
        xs, ys = [p[0] for p in z["polygon"]], [p[1] for p in z["polygon"]]
        cx, cy = sum(xs) / 4, sum(ys) / 4
        suffix = zid.removeprefix("ZONE-")
        chars = [{
            "character_id": CHAR_IDS[name], "zone_id": zid,
            "position": [round(cx + SCREEN_SLOT_X_OFFSET[SCREEN_SLOT_BY_CHARACTER[name]], 2), round(cy, 2)],
            "facing": "camera_or_scene_partner",
        } for name in visible_cast(shot)]
        props = [{
            "prop_id": prop_id, "zone_id": zid,
            "position": [round(cx, 2), round(cy + .4 + index * .25, 2)], "facing": "camera",
        } for index, prop_id in enumerate(visible_props(shot))]
        tasks.append({
            "task_key": f"{shot['shot_id']}-MAP-LOCK-V1", "unit_id": shot["shot_id"],
            "tool_type": "image_generation", "spatial_layout_stage": "SHOT_KEYFRAME",
            "scene_id": shot["scene_id"], "episode_global_space_map_id": EPISODE_MAP_ID,
            "global_space_map_id": map_id, "room_id": room_id, "zone_id": zid,
            "angle_id": f"ANGLE-{suffix}-LOCKED", "resolution_order": RESOLUTION_ORDER,
            "subspace_layout": {
                "subspace_id": subspace, "derived_from_episode_global_space_map_id": EPISODE_MAP_ID,
                "derived_from_global_space_map_id": map_id, "room_id": room_id, "zone_ids": [zid],
                "angle_id": f"ANGLE-{suffix}-LOCKED", "camera_position_id": f"ANGLE-{suffix}-LOCKED",
                "axis_id": f"AXIS-{suffix}", "visible_fixed_element_ids": [f"FIXED-{suffix}"],
                "polygon": z["polygon"],
            },
            "blocking": {"resolved_after_subspace_lock": True, "characters": chars, "props": props},
            "action_end_blocking": {"characters": chars, "props": props},
            "trajectory_overlays": [], "entity_reference_bindings": [],
            "source_shot_contract": {
                "path": str(CONTRACT.relative_to(ROOT)), "sha256": sha(CONTRACT),
                "shot_id": shot["shot_id"], "camera": shot["camera"],
                "action": shot["frame_content"], "completion_state": shot["first_frame_motion_state"],
            },
        })
    auth_template = PROD / "E44_V5_EPISODE_GLOBAL_SPACE_MAP_TEMPLATE_V1.json"
    shot_template = PROD / "E44_V5_COMPLETE_MAP_SHOT_PLAN_V1.json"
    write_json(auth_template, authority)
    write_json(shot_template, {
        "schema": "qingshan.complete_map_shot_plan.v1", "episode": "E44", "canonical_version": 5,
        "global_space_map_gate_required": True,
        "episode_global_space_map_ref": "workflow/claude_writer_agent/production/e44_v5_20260828/E44_V5_EPISODE_GLOBAL_SPACE_MAP_AUTHORITY_LOCKED_V1.json",
        "tasks": tasks,
    })
    locked, plan, receipt = render_maps(authority, json.loads(shot_template.read_text()), ASSETS)
    auth_locked = PROD / "E44_V5_EPISODE_GLOBAL_SPACE_MAP_AUTHORITY_LOCKED_V1.json"
    plan_locked = PROD / "E44_V5_COMPLETE_MAP_SHOT_PLAN_LOCKED_V1.json"
    render_receipt = PROD / "E44_V5_COMPLETE_MAP_RENDER_RECEIPT_V1.json"
    write_json(auth_locked, locked)
    write_json(plan_locked, plan)
    receipt.update({
        "authority_path": str(auth_locked.relative_to(ROOT)), "authority_sha256": sha(auth_locked),
        "shot_plan_path": str(plan_locked.relative_to(ROOT)), "shot_plan_sha256": sha(plan_locked),
    })
    write_json(render_receipt, receipt)
    gate = evaluate_batch(locked, plan["tasks"], episode="E44", required=True)
    gate_path = QA / "E44_V5_COMPLETE_MAP_MODE_GATE_V1.json"
    write_json(gate_path, gate)
    lock = {
        "schema": "qingshan.complete_map_mode_lock.v1", "episode": "E44", "canonical_version": 5,
        "status": gate["status"], "policy": "E42+ complete map mode is non-bypassable.",
        "counts": {"episode_maps": 1, "place_maps": len(locked["space_maps"]), "shot_subspace_maps": len(plan["tasks"])},
        "authority": {"path": str(auth_locked.relative_to(ROOT)), "sha256": sha(auth_locked)},
        "shot_plan": {"path": str(plan_locked.relative_to(ROOT)), "sha256": sha(plan_locked)},
        "render_receipt": {"path": str(render_receipt.relative_to(ROOT)), "sha256": sha(render_receipt)},
        "gate_report": {"path": str(gate_path.relative_to(ROOT)), "sha256": sha(gate_path)},
        "generation_contract": {"path": str(CONTRACT.relative_to(ROOT)), "sha256": sha(CONTRACT)},
    }
    write_json(PROD / "E44_V5_COMPLETE_MAP_MODE_LOCK_V1.json", lock)
    if gate["status"] != "PASS":
        raise ValueError("E44 complete map gate failed")
    return locked, plan


def build_editorial(source: dict[str, Any], map_plan: dict[str, Any]) -> dict[str, Any]:
    mapped = {row["unit_id"]: row for row in map_plan["tasks"]}
    states = {row["scene_id"]: row for row in source["scene_states"]}
    id_to_name = {value: key for key, value in CHAR_IDS.items()}
    prop_names = {value: key for key, value in PROP_IDS.items()}
    shots = []
    for row in source["shots"]:
        map_row, scene = mapped[row["shot_id"]], states[row["scene_id"]]
        cast = [{
            "character": id_to_name[actor["character_id"]],
            "screen_slot": SCREEN_SLOT_BY_CHARACTER[id_to_name[actor["character_id"]]],
            "depth_plane": "PRIMARY_ACTION_PLANE" if index < 2 else "REACTION_PLANE",
            "face_visibility": "VISIBLE_PER_FRAME_CONTENT", "identity_card_required": True,
        } for index, actor in enumerate((map_row["blocking"] or {}).get("characters") or [])]
        dialogue = str(row.get("dialogue") or "")
        speaker = dialogue.partition("：")[0].strip() if "：" in dialogue else ""
        if speaker in CHAR_IDS and speaker not in {item["character"] for item in cast}:
            cast.append({
                "character": speaker, "screen_slot": "OFFSCREEN", "depth_plane": "OFFSCREEN_SOURCE",
                "face_visibility": "OFFSCREEN_VOICE_ONLY", "identity_card_required": False,
            })
        visible_names = [item["character"] for item in cast]
        props = [{
            "prop": prop_names.get(prop["prop_id"], prop["prop_id"]), "anchor": "PRIMARY_ACTION_PLANE",
            "continuity_scope": "SCENE_OR_RECURRING_PROP",
        } for prop in (map_row["blocking"] or {}).get("props") or []]
        completion = playable_completion(row)
        performance = {
            "psychological_state": "人物只处理当前交易、判断或关系压力，不预演下一拍",
            "emotion": "克制而有明确因果落点",
            "emotion_intensity": 2,
            "expression_arc": "动作起点的克制观察→事件落点后的细微确认并保持",
            "continuous_micro_action": "呼吸连续，眼神先于头部改变一次，眼睑与下颌只在因果点响应",
            "event_reaction": f"只对“{row['frame_content']}”发生一次可见反应，随后保持结果态",
            "body_sync": "视线先动，随后下颌、肩颈与重心按同一方向完成响应，不循环复位",
            "actor_performance": {
                name: {
                    "expression_arc": "原有表情→因当前事件产生一次细微变化并保持",
                    "continuous_micro_action": "自然呼吸持续，眼睑与瞳孔只在台词重音或动作接触点变化一次",
                    "event_reaction": f"对“{row['frame_content']}”作角色内反应，不抢先进入下一镜",
                    "body_sync": "眼神先行，下颌与肩颈随后，手部或重心最后完成动作",
                } for name in visible_names
            },
        }
        dialogue_delivery = None
        if dialogue:
            spoken = dialogue.partition("：")[2].strip()
            emphasis = spoken.strip("？！。，“”‘’；：") or spoken
            dialogue_delivery = {
                "pace": "自然克制，不均匀播报",
                "pause_map": "只在原文逗号、问号或因果转折处短停，句末留半拍给对方反应",
                "emphasis_words": [emphasis],
                "volume_arc": "贴近现场音量起句，重音轻抬，句末收回而不戏剧化喊叫",
                "breath_pattern": "开口前一次短吸气，长句在原文停连处补气，不切断词组",
                "delivery_transition": "从试探、陈述或反问进入本句明确落点，句末转为观察听者",
            }
        visual_design = {
            "depth_layers": ["前景固定物或衣料边缘", "中景人物与当前动作", "背景建筑、水面或街巷纵深"],
            "scale_anchor": "柱径、石栏、桌案高度与人物肩宽保持真实比例",
            "key_light": f"动机光只来自{scene['time_of_day_state']}的自然光与现场实用灯",
            "atmosphere": scene["weather_state"],
            "environmental_motion": ["风只推动帘、衣摆、柳枝或蒸汽中的相关一项", "水面或街面反光低幅连续变化"],
            "material_detail": ["丝帘细密经纬与受力褶皱", "石栏水汽旧磨痕或木桌油润使用痕迹", "瓷器与粗布只出现真实高光"],
            "still_prompt_contract": "首帧同时交代空间、人物/画外声方向、关键物证与动作起点",
            "video_motion_contract": "环境仅维持微风、反光与衣料惯性；人物动作一次完成并保持结果态",
            "palette": {"dominant": scene["palette_temperature"], "contrast": "冷灰与暖肤色", "accent": "瓷青或帘紫只作小面积强调"},
        }
        sound_design = {
            "ambience": "同任务原生场景底声：池水、风、远席或街市按所在场景保持空间混响",
            "foley": "同任务原生衣料、瓷器、帘布、脚步或碗筷的真实接触声",
            "action_sound": "只强化当前一次因果动作的接触声，不加跨任务音轨或默认BGM",
        }
        shots.append({
            "shot_id": row["shot_id"], "scene_id": row["scene_id"],
            "duration_seconds": row["duration_seconds"], "model": "seedance-2.0-pro",
            "resolution": "720p", "aspect_ratio": "9:16",
            "prompt_spec": {
                "space": {"global": GLOBAL_SPACE, "location": scene["location_id"], "subspace": row["subspace_id"]},
                "scene_state": {"time": scene["time_of_day_state"], "weather": scene["weather_state"], "palette": scene["palette_temperature"]},
                "cast": cast, "props": props,
                "camera": row["camera"],
                "action": {
                    "t0_seconds": row["start_seconds"], "start_state": completion,
                    "primary_action": row["frame_content"], "completion_state": completion,
                    "contact_point": f"当前镜明确接触或反应落点：{completion}",
                    "motion_direction": "眼神/布料/手部从既定起点沿单一方向到达结果态",
                    "physical_causality": "接触或台词先发生，眼神与下颌随后，肩颈和重心最后完成并保持",
                    "t1_seconds": round(float(row["start_seconds"]) + float(row["duration_seconds"]), 3),
                    "freeze_or_speed_ramp_forbidden": True,
                    "microexpression_design": "眼神先于头部，呼吸与下颌随后；只做一次因果可见变化，变化后保持结果态",
                    "physical_action_design": "接触先由手指/唇/视线发生，再由下颌、肩颈和重心响应，动作一次完成不循环",
                },
                "performance": performance,
                "dialogue": dialogue,
                "dialogue_delivery": dialogue_delivery,
                "visual_design": visual_design,
                "sound_design": sound_design,
                "audio_contract": "SAME_VIDEO_TASK_NATIVE_AUDIO" if dialogue else "DIEGETIC_OR_SILENT_NO_TTS",
                "negative_prompts": row.get("negative_prompts") or [],
            },
        })
    result = {
        "schema": "qingshan.editorial_seedance_manifest.v2_performance_complete", "episode": "E44",
        "canonical_version": 5, "source_generation_contract": str(CONTRACT.relative_to(ROOT)),
        "source_generation_contract_sha256": sha(CONTRACT),
        "complete_map_shot_plan": str((PROD / "E44_V5_COMPLETE_MAP_SHOT_PLAN_LOCKED_V1.json").relative_to(ROOT)),
        "complete_map_shot_plan_sha256": sha(PROD / "E44_V5_COMPLETE_MAP_SHOT_PLAN_LOCKED_V1.json"),
        "model_contract": {
            "model": "seedance-2.0-pro", "resolution": "720p", "native_raster": "720x1280",
            "delivery_raster": "1440x2560", "delivery_upscale": "HIGH_QUALITY_2K_RELEASE_UPSCALE",
            "aspect_ratio": "9:16", "route": "STANDARD_MULTI_REFERENCE",
        },
        "shots": shots,
    }
    write_json(PROD / "E44_V5_EDITORIAL_SEEDANCE_MANIFEST_V1.json", result)
    return result


def relation(previous: dict[str, Any], current: dict[str, Any]) -> tuple[str, str]:
    a = previous["prompt_spec"]["space"]
    b = current["prompt_spec"]["space"]
    if a["subspace"] == b["subspace"]:
        return "SAME_SUBSPACE", "CONTINUOUS_ACTION"
    if a["location"] == b["location"]:
        return "SAME_LOCATION_NEW_SUBSPACE", "NEW_SPACE_MATCH_CUT"
    return "NEW_LOCATION_SAME_GLOBAL", "SOUND_BRIDGE_NEW_SPACE"


def transition_device(previous: dict[str, Any], current: dict[str, Any], space_relation: str, index: int) -> str:
    if space_relation != "SAME_SUBSPACE":
        return "SOUND_BRIDGE" if index % 2 else "ENVIRONMENT_BRIDGE"
    if previous["prompt_spec"].get("props") and current["prompt_spec"].get("props"):
        return "PROP_MATCH"
    return ("ACTION_MATCH", "GAZE_MATCH", "MOTIVATED_CUT")[index % 3]


CAMERA_SEQUENCE = [
    ("CRANE", "FALL"), ("DOLLY", "PUSH_IN"), ("DOLLY", "PULL_OUT"),
    ("PAN", "LEFT_TO_RIGHT"), ("LOCKED", "NONE"), ("ARC", "CLOCKWISE"),
    ("DOLLY", "PUSH_IN"), ("PAN", "RIGHT_TO_LEFT"), ("TRACK", "LEFT_TO_RIGHT"),
    ("DOLLY", "PUSH_IN"), ("PAN", "LEFT_TO_RIGHT"), ("LOCKED", "NONE"),
    ("LOCKED", "NONE"), ("DOLLY", "PUSH_IN"), ("PAN", "RIGHT_TO_LEFT"),
    ("DOLLY", "PUSH_IN"), ("ARC", "COUNTERCLOCKWISE"), ("TRACK", "RIGHT_TO_LEFT"),
    ("TRACK", "LEFT_TO_RIGHT"), ("DOLLY", "PULL_OUT"), ("TRACK", "RIGHT_TO_LEFT"),
    ("CRANE", "FALL"), ("PAN", "LEFT_TO_RIGHT"), ("DOLLY", "PUSH_IN"),
    ("LOCKED", "NONE"), ("DOLLY", "PULL_OUT"),
]


def authored_camera_plan(group: list[dict[str, Any]], index: int) -> dict[str, str]:
    family, direction = CAMERA_SEQUENCE[(index - 1) % len(CAMERA_SEQUENCE)]
    first_action = str(group[0]["prompt_spec"]["action"]["primary_action"])
    last_action = str(group[-1]["prompt_spec"]["action"]["primary_action"])
    cast_count = len({
        row["character"] for shot in group for row in shot["prompt_spec"].get("cast") or []
        if row.get("face_visibility") != "OFFSCREEN_VOICE_ONLY"
    })
    shot_scale = "MEDIUM_WIDE" if cast_count > 2 else ("MEDIUM" if cast_count > 1 else "MEDIUM_CLOSE_UP")
    if not cast_count:
        shot_scale = "WIDE"
    axis_side = "AXIS_A" if index % 2 else "AXIS_B"
    if family == "LOCKED":
        framing = f"以{first_action}的主体、接触物和视线落点组成稳定构图"
        start_framing = end_framing = framing
    else:
        start_framing = f"从{first_action}的动作起点与人物视线关系开始"
        end_framing = f"在{last_action}的不可逆结果与反应落点停稳"
    movement_reason = {
        "CRANE": "高度变化只用于从环境秩序落到触发剧情的具体物件和人物反应",
        "DOLLY": "纵深变化只用于把观众注意力从话语表面移到眼神、手部或道具结果",
        "PAN": "摇镜只连接当前说话者与被迫作出反应的人或物，不扫过无关风景",
        "TRACK": "横向跟拍只保持真实行进、转身或离席动作及其空间终点连续可读",
        "ARC": "有限弧线只揭示人物关系位移与权力变化，移动一次后停住",
        "LOCKED": "摄影机不动，让对白、呼吸、微表情与接触动作自行改变画面权重",
    }[family]
    return {
        "shot_scale": shot_scale,
        "lens_intent": "35mm保留空间与群体关系" if shot_scale in {"WIDE", "MEDIUM_WIDE"} else "50mm自然透视压住背景干扰",
        "camera_height": "EYE_LEVEL", "camera_side": axis_side,
        "axis_relation": "服从场景地图既定180度轴；换侧必须由门框、廊柱、帘面或桌案重新建立方向",
        "motion_family": family, "motion_direction": direction,
        "start_framing": start_framing, "end_framing": end_framing,
        "motivation": f"{movement_reason}；本段因果是“{first_action}”推进到“{last_action}”。",
        "authorship": "DIRECTOR_AUTHORED_E44_V5",
    }


def authored_internal_transition(
    unit_id: str,
    previous: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    """Author the cast/scene/prop/sound/action handoff inside one provider clip."""
    previous_spec, current_spec = previous["prompt_spec"], current["prompt_spec"]
    visible = lambda spec: sorted({
        str(row["character"]) for row in spec.get("cast") or []
        if row.get("character") and row.get("face_visibility") != "OFFSCREEN_VOICE_ONLY"
    })
    props = lambda spec: sorted({str(row["prop"]) for row in spec.get("props") or [] if row.get("prop")})
    space = lambda spec: {key: str(spec["space"][key]) for key in ("global", "location", "subspace")}
    sound = lambda spec: {key: str(spec["sound_design"][key]) for key in ("ambience", "foley", "action_sound")}
    previous_cast, current_cast = visible(previous_spec), visible(current_spec)
    previous_space, current_space = space(previous_spec), space(current_spec)
    cast_changes = previous_cast != current_cast
    space_changes = previous_space != current_space
    if cast_changes:
        mode = "MOTIVATED_CUT"
        entry = (
            f"在上一动作结果落稳后明确切镜，从{','.join(previous_cast) or '环境'}切到"
            f"{','.join(current_cast) or '环境'}；退场与入场由真实空间和剧情因果建立，禁止变脸或同位替换"
        )
    elif space_changes:
        mode = "MATCH_CUT"
        entry = "人物身份和服装保持锁定，以动作结果、固定物或现场声匹配切入真实新子空间"
    else:
        mode = "CONTINUOUS_ACTION"
        entry = "同一人物构图与身份保持不变，新动作从上一结果态直接发生，不另起无关动作"
    previous_terminal = str(previous_spec["action"]["completion_state"])
    current_initial = str(current_spec["action"]["start_state"])
    return {
        "boundary_id": internal_boundary_id(unit_id, previous["shot_id"], current["shot_id"]),
        "from_shot_id": previous["shot_id"],
        "to_shot_id": current["shot_id"],
        "transition_mode": mode,
        "authorship": "DIRECTOR_AUTHORED",
        "cast_bridge": {
            "from_visible_characters": previous_cast,
            "to_visible_characters": current_cast,
            "identity_preservation": "所有既有人物面貌、发型、年龄、服装和体型锁定不变，禁止一人变成另一人",
            "entry_exit_or_reveal": entry,
        },
        "scene_bridge": {
            "from_space": previous_space,
            "to_space": current_space,
            "continuity": "保持完整地图拓扑、固定建筑、天气、时间和光向；子空间变化必须由可见固定物、动作或现场声建立",
        },
        "prop_bridge": {
            "from_props": props(previous_spec),
            "to_props": props(current_spec),
            "ownership_or_handoff": (
                f"道具从{','.join(props(previous_spec)) or '无'}连续到{','.join(props(current_spec)) or '无'}；"
                "新增道具由人物手部、衣袋或既有台面真实取出，离场道具完成可见交接或离画"
            ),
        },
        "sound_bridge": {
            "from_sound": sound(previous_spec),
            "to_sound": sound(current_spec),
            "bridge": "同一环境底声保持空间连续，上一动作真实声尾跨过交接，下一次衣料、脚步或道具接触声自然接管",
        },
        "camera_bridge": {
            "axis_strategy": "严格维持地图既定人物轴同侧；明确切镜时以门框、廊柱、桌案或街面固定物重新建立方向",
            "transition_execution": "上一动作结果保持后只执行一次连续运镜或明确切镜，落稳后再开始下一对白或动作，禁止反复同向扫镜",
        },
        "action_bridge": f"上一终态“{previous_terminal}”保持到交接点，下一初态“{current_initial}”从该结果继续，禁止复位重演",
        "reference_bridge": {
            "entity_mapping": "每张参考图只绑定其具名人物、场景和道具；不同参考图中的人物不得互换身份或覆盖同位角色",
            "different_character_same_slot_forbidden": True,
            "same_slot_reuse_allowed": cast_changes,
        },
    }


def build_units(editorial: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    shots = editorial["shots"]
    shot_by_id = {row["shot_id"]: row for row in shots}
    groups = []
    start = 0
    while start < len(shots):
        scene_id = shots[start]["scene_id"]
        end = start + 1
        while end < len(shots) and shots[end]["scene_id"] == scene_id:
            end += 1
        groups.extend(partition_scene(shots[start:end]))
        start = end
    production = {
        "episode": "E44", "runtime_seconds": 180.0,
        "source": {"canonical_script": str(CANONICAL.relative_to(ROOT)), "script_sha256": sha(CANONICAL),
                   "generation_contract": str(CONTRACT.relative_to(ROOT)), "generation_contract_sha256": sha(CONTRACT)},
        "production_overlay": {
            "authorization_ref": "ROGER-20260828-START-E44-PRODUCTION", "mode": "director", "language": "zh",
            "model": "seedance-2.0-pro", "resolution": "720p", "aspect_ratio": "9:16",
            "route": "STANDARD_MULTI_REFERENCE", "canonical_mutated": False,
            "paid_submit_requires_all_registered_prechecks_pass": True,
            "transition_prompt_binding_required": True,
        },
        "shots": [{"shot_id": row["shot_id"], "scene_id": row["scene_id"], "duration_seconds": row["duration_seconds"]} for row in shots],
    }
    spec_groups = []
    for index, group in enumerate(groups, start=1):
        camera = authored_camera_plan(group, index)
        duration = round(sum(float(row["duration_seconds"]) for row in group), 3)
        row = {
            "unit_id": f"E44-VU-{index:03d}", "editorial_shot_ids": [x["shot_id"] for x in group],
            "action_unit": True,
            "narrative_beat": " → ".join(str(x["prompt_spec"]["action"]["primary_action"]) for x in group),
            "camera_plan": camera,
            "internal_transition_contracts": [
                authored_internal_transition(f"E44-VU-{index:03d}", group[boundary], group[boundary + 1])
                for boundary in range(len(group) - 1)
            ],
        }
        if not 5 <= duration <= 8:
            row["duration_exception_reason"] = "SCENE_LOCAL_CONTINUOUS_CAUSAL_ACTION"
        spec_groups.append(row)
    for index in range(1, len(spec_groups)):
        previous, current = spec_groups[index - 1], spec_groups[index]
        source_shot = shot_by_id[previous["editorial_shot_ids"][-1]]
        target_shot = shot_by_id[current["editorial_shot_ids"][0]]
        space_relation, cut_reason = relation(source_shot, target_shot)
        target_cast = sorted({
            x["character"] for x in target_shot["prompt_spec"].get("cast") or []
            if x.get("face_visibility") != "OFFSCREEN_VOICE_ONLY"
        })
        target_props = sorted({x["prop"] for x in target_shot["prompt_spec"].get("props") or []})
        device = transition_device(source_shot, target_shot, space_relation, index)
        source_action = source_shot["prompt_spec"]["action"]["completion_state"]
        target_action = target_shot["prompt_spec"]["action"]["start_state"]
        bnd = boundary_id(previous["unit_id"], current["unit_id"])
        current["transition_contract"] = {
            "boundary_id": bnd, "from_unit_id": previous["unit_id"], "to_unit_id": current["unit_id"],
            "authorship": "DIRECTOR_AUTHORED", "cut_reason": cut_reason, "space_relation": space_relation,
            "transition_device": device, "outgoing_handle_seconds": 1.0, "incoming_handle_seconds": 0.8,
            "plot_motivation": f"前一拍“{source_shot['prompt_spec']['action']['primary_action']}”的结果直接触发后一拍“{target_shot['prompt_spec']['action']['primary_action']}”，不插入空景。",
            "visual_bridge": f"前段末尾保持“{source_action}”并把视觉注意力交给下一段首帧的“{target_action}”。",
            "action_bridge": f"前段最后1秒完成并保持“{source_action}”；下一段前0.8秒从同一结果态承接后再执行“{target_action}”。",
            "sound_bridge": "保留前段现场声尾，下一段首个真实接触声或环境声接管；禁止默认BGM与突兀静音。",
            "axis_strategy": f"前段保持{previous['camera_plan']['camera_side']}侧，下一段从{current['camera_plan']['camera_side']}侧建立；跨空间先用固定物确认新轴。",
            "continuity_intent": "让因果动作、人物视线、道具位置与现场声跨独立生成单元形成可剪辑的单一连续事件。",
            "source_terminal_state": {
                "scene_id": previous.get("scene_id") or source_shot["scene_id"],
                "space": source_shot["prompt_spec"]["space"],
                "camera_framing": previous["camera_plan"]["end_framing"],
                "camera_side": previous["camera_plan"]["camera_side"],
                "blocking": f"{source_action}；动作结果保持到切点，不复位、不回摆。",
            },
            "target_initial_state": {
                "scene_id": current.get("scene_id") or target_shot["scene_id"],
                "space": target_shot["prompt_spec"]["space"],
                "camera_framing": current["camera_plan"]["start_framing"],
                "camera_side": current["camera_plan"]["camera_side"],
                "blocking": f"{target_action}；从前段结果态进入，不另起无关动作。",
            },
            "anchor_semantic_requirements": {
                "target_visible_characters": target_cast, "target_visible_props": target_props,
                "target_space_anchors": [target_shot["prompt_spec"]["space"]["location"], target_shot["prompt_spec"]["space"]["subspace"]],
                "empty_establishing_frame_allowed": not bool(target_cast),
            },
        }
    spec = {
        "episode": "E44", "source_script_sha256": sha(CANONICAL),
        "duration_policy_seconds": {"minimum": 3, "maximum": 12, "authority": "GIGGLE-SEEDANCE2-4-15S+ROGER-20260828-E44"},
        "preferred_duration_seconds": {"minimum": 5, "maximum": 8}, "groups": spec_groups,
    }
    prod_path = PROD / "E44_V5_EDITORIAL_PRODUCTION_MANIFEST_V1.json"
    spec_path = PROD / "E44_V5_VIDEO_UNIT_GROUPING_SPEC_V1.json"
    plan_path = PROD / "E44_V5_VIDEO_UNIT_GROUPING_PLAN_V1.json"
    write_json(prod_path, production)
    write_json(spec_path, spec)
    plan = compile_grouping_spec(production, spec)
    write_json(plan_path, plan)
    gate = evaluate_grouping(plan)
    gate.update({
        "schema": "qingshan.video_unit_grouping_gate_report.v2_transition_contract", "episode": "E44",
        "production_manifest": str(prod_path.relative_to(ROOT)), "production_manifest_sha256": sha(prod_path),
        "grouping_spec": str(spec_path.relative_to(ROOT)), "grouping_spec_sha256": sha(spec_path),
        "grouping_plan": str(plan_path.relative_to(ROOT)), "grouping_plan_sha256": sha(plan_path),
    })
    write_json(QA / "E44_V5_VIDEO_UNIT_GROUPING_GATE_V1.json", gate)
    if gate["status"] != "PASS":
        raise ValueError("E44 video-unit grouping gate failed")
    return spec, plan


def main() -> int:
    source = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if source.get("episode") != "E44" or source.get("version") != 5:
        raise ValueError("E44 v5 generation contract required")
    _authority, map_plan = build_complete_map(source)
    editorial = build_editorial(source, map_plan)
    _spec, plan = build_units(editorial)
    summary = {
        "schema": "qingshan.e44_v5_preproduction_summary.v1", "episode": "E44", "status": "PASS",
        "canonical_version": 5, "map_mode": "COMPLETE", "place_map_count": 5,
        "editorial_shot_count": len(editorial["shots"]), "video_unit_count": plan["video_unit_count"],
        "transition_boundary_count": max(0, plan["video_unit_count"] - 1),
        "model_contract": editorial["model_contract"],
        "paid_post_allowed": False,
        "next_gate": "GENERATE_AND_ADMIT_SEMANTIC_START_FRAMES_THEN_COMPILE_PROMPTS",
    }
    write_json(QA / "E44_V5_PREPRODUCTION_SUMMARY_V1.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
