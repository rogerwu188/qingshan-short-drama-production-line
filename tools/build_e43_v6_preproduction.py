#!/usr/bin/env python3
"""Build E43 v6 complete-map, editorial and transition-bound video-unit plans.

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
PROD = ROOT / "workflow/claude_writer_agent/production/e43_v6_20260828"
ASSETS = ROOT / "artifacts/e43_v6/complete_map_mode_v1"
QA = ROOT / "qa/e43_v6_preproduction_20260828"
CONTRACT = SCRIPTS / "E43_GENERATION_CONTRACT_v6.json"
CANONICAL = SCRIPTS / "E43_NARRATIVE_CANONICAL_v6.md"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))
from _gen_e43_v6_data import S as SCENES  # noqa: E402
from tools.build_video_unit_grouping_spec import partition_scene  # noqa: E402
from tools.compile_video_unit_plan import compile_grouping_spec  # noqa: E402
from tools.global_space_layout_gate import RESOLUTION_ORDER, evaluate_batch  # noqa: E402
from tools.grouped_transition_contract import boundary_id  # noqa: E402
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
    "LOC-JINGWANGFU-FEIBAICHI": (
        "GSM-E43-FEIBAICHI-BANQUET-V1", "ROOM-E43-FEIBAICHI", 32, 22,
        [
            zone("ZONE-BANQUET-FIRST-ROW", "首排席", 1, 2, 13, 9),
            zone("ZONE-BANQUET-LAST-ROW", "末排席", 15, 2, 29, 9),
            zone("ZONE-BANQUET-AISLE", "席间通道", 13, 2, 15, 18),
            zone("ZONE-BANQUET-WOMEN", "女眷席", 1, 11, 12, 18),
            zone("ZONE-BANQUET-WALL", "墙根", 18, 11, 25, 18),
            zone("ZONE-BANQUET-MOON-GATE", "月洞门", 25, 11, 31, 18),
            zone("ZONE-BANQUET-POND", "飞白池水岸", 0, 19, 32, 22),
        ],
    ),
    "LOC-JINGWANGFU-FEIBAICHI-LIANGTING": (
        "GSM-E43-FEIBAICHI-CURTAIN-PAVILION-V1", "ROOM-E43-LIANGTING", 14, 15,
        [
            zone("ZONE-PAVILION-OUTSIDE", "帘外陈迹位", 0, 0, 6, 12),
            zone("ZONE-PAVILION-CURTAIN", "垂帘分界", 6, 0, 8, 12),
            zone("ZONE-PAVILION-INSIDE", "帘内静妃位", 8, 0, 14, 12),
            zone("ZONE-PAVILION-STEPS", "亭外阶下春华位", 0, 12, 5, 15),
            zone("ZONE-PAVILION-WATER", "石栏与水声入口", 5, 12, 14, 15),
        ],
    ),
    "LOC-WANGFU-LANGXIA": (
        "GSM-E43-WANGFU-CORRIDOR-V1", "ROOM-E43-LANGXIA", 24, 10,
        [
            zone("ZONE-CORRIDOR-EAVES", "回廊檐下", 0, 1, 20, 5),
            zone("ZONE-CORRIDOR-COLUMNS", "廊柱线", 0, 5, 20, 7),
            zone("ZONE-CORRIDOR-LIGHT", "檐外光影交界", 0, 7, 20, 10),
            zone("ZONE-CORRIDOR-BANQUET-VIEW", "望向席面方向", 20, 1, 24, 10),
        ],
    ),
    "LOC-ZHENGHEJIE": (
        "GSM-E43-ZHENGHE-STREET-V1", "ROOM-E43-ZHENGHE-STREET", 32, 14,
        [
            zone("ZONE-STREET-WALK", "政和街行进线", 0, 3, 32, 9),
            zone("ZONE-STREET-SEDAN", "青帷小轿跟随线", 0, 9, 24, 13),
            zone("ZONE-STREET-CLINIC", "医馆转入口", 20, 0, 26, 3),
            zone("ZONE-STREET-NOODLE-EAVE", "穆新斋外檐", 26, 0, 32, 3),
        ],
    ),
    "LOC-TAIPING-YIGUAN-MENKOU": (
        "GSM-E43-TAIPING-CLINIC-DOOR-V1", "ROOM-E43-CLINIC-DOOR", 14, 10,
        [
            zone("ZONE-CLINIC-STREET", "医馆门前街面", 0, 0, 14, 4),
            zone("ZONE-CLINIC-THRESHOLD", "半开门板与门槛", 3, 4, 11, 6),
            zone("ZONE-CLINIC-INSIDE", "门内暗处", 3, 6, 11, 10),
        ],
    ),
    "LOC-ZHENGHEJIE-MUXINZHAI": (
        "GSM-E43-MUXINZHAI-NOODLE-HOUSE-V1", "ROOM-E43-MUXINZHAI", 18, 14,
        [
            zone("ZONE-NOODLE-TABLE", "堂中长桌", 2, 2, 12, 7),
            zone("ZONE-NOODLE-STOVE", "灶口与蒸汽", 12, 2, 18, 9),
            zone("ZONE-NOODLE-BOWL-STACK", "空碗摞", 0, 7, 6, 11),
            zone("ZONE-NOODLE-COUNTER", "掌柜收钱位", 6, 7, 12, 11),
            zone("ZONE-NOODLE-DOOR", "面馆门口", 0, 11, 18, 14),
        ],
    ),
}

EPISODE_MAP_ID = "EGSM-E43-FEIBAICHI-TO-ZHENGHEJIE-V1"
GLOBAL_SPACE = "GLOBAL-SPACE-E43-FEIBAICHI-LIANGTING-LANGXIA-ZHENGHEJIE-MUXINZHAI-SHENSHI-DAO-YOUSHI"

CHAR_IDS = {
    name: f"CHAR-E43-{token}" for name, token in {
        "陈迹": "CHENJI", "白鲤": "BAILI", "世子": "SHIZI", "小和尚": "XIAOHESHANG",
        "静妃": "JINGFEI", "春华": "CHUNHUA", "陈问宗": "CHENWENZONG",
        "陈问孝": "CHENWENXIAO", "佘登科": "SHEDENGKE", "刘曲星": "LIUQUXING",
        "梁猫儿": "LIANGMAOER", "林朝京": "LINCHAOJING", "掌柜": "ZHANGGUI",
        "席间宾客": "BANQUET-GUESTS",
    }.items()
}
PROP_IDS = {
    "杯": "PROP-E43-CUP", "酒壶": "PROP-E43-WINE-POT", "帘": "PROP-E43-CURTAIN",
    "折扇": "PROP-E43-FAN", "扇子": "PROP-E43-FAN", "白霜": "PROP-E43-WALL-FROST",
    "碗": "PROP-E43-BOWL", "筷": "PROP-E43-CHOPSTICKS", "荷包": "PROP-E43-PURSE",
    "铜钱": "PROP-E43-COIN", "药方": "PROP-E43-PRESCRIPTION", "纸": "PROP-E43-PRESCRIPTION",
    "小轿": "PROP-E43-GREEN-SEDAN",
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
        "LOC-JINGWANGFU-FEIBAICHI": [
            (("QIANGGEN",), "ZONE-BANQUET-WALL"), (("YUEDONG", "XIONGDI"), "ZONE-BANQUET-MOON-GATE"),
            (("NVJUAN",), "ZONE-BANQUET-WOMEN"), (("TONGDAO",), "ZONE-BANQUET-AISLE"),
            (("DIYIPAI", "WENREN"), "ZONE-BANQUET-FIRST-ROW"), (("XISHOU", "MOPAI"), "ZONE-BANQUET-LAST-ROW"),
        ],
        "LOC-JINGWANGFU-FEIBAICHI-LIANGTING": [
            (("LIANNEI",), "ZONE-PAVILION-INSIDE"), (("LIANJIAO", "LIANMIAN", "YUQI"), "ZONE-PAVILION-CURTAIN"),
            (("TINGWAI",), "ZONE-PAVILION-STEPS"), (("SHUIMIAN",), "ZONE-PAVILION-WATER"),
            (("LIANWAI",), "ZONE-PAVILION-OUTSIDE"),
        ],
        "LOC-WANGFU-LANGXIA": [
            (("CHUYAN",), "ZONE-CORRIDOR-LIGHT"), (("SHUNSHI",), "ZONE-CORRIDOR-BANQUET-VIEW"),
            (("LANGXIA",), "ZONE-CORRIDOR-EAVES"),
        ],
        "LOC-ZHENGHEJIE": [
            (("QINGWEI",), "ZONE-STREET-SEDAN"), (("JIEKOU",), "ZONE-STREET-NOODLE-EAVE"),
            (("YIGUAN",), "ZONE-STREET-CLINIC"), (("ZHENGHEJIE",), "ZONE-STREET-WALK"),
        ],
        "LOC-TAIPING-YIGUAN-MENKOU": [
            (("LIANGMAOER",), "ZONE-CLINIC-THRESHOLD"), (("GUAIJIN", "JIAOREN"), "ZONE-CLINIC-THRESHOLD"),
            (("YIGUANMENKOU",), "ZONE-CLINIC-STREET"),
        ],
        "LOC-ZHENGHEJIE-MUXINZHAI": [
            (("KONGWAN",), "ZONE-NOODLE-BOWL-STACK"), (("ZHANGGUI",), "ZONE-NOODLE-COUNTER"),
            (("ZAO",), "ZONE-NOODLE-STOVE"), (("MEN",), "ZONE-NOODLE-DOOR"),
            (("MUXINZHAI",), "ZONE-NOODLE-TABLE"),
        ],
    }
    for tokens, zone_id in tests[location]:
        if any(token in subspace for token in tokens):
            return zone_id
    return MAP_DEFS[location][4][0]["zone_id"]


def visible_cast(shot: dict[str, Any]) -> list[str]:
    scene = shot["scene_id"]
    subspace = str(shot.get("subspace_id") or "")
    if any(token in subspace for token in ("LIANNEI", "YUQI", "LIANJIAO", "LIANMIAN")):
        # Jingfei is never visible in E43. Interior-curtain and curtain-detail
        # shots carry only her same-task native voice plus physical cloth motion.
        return []
    text = f"{shot.get('frame_content', '')} {shot.get('dialogue', '')} {shot.get('camera', '')}"
    result = [name for name in CHAR_IDS if name in text]
    if "静妃" in result:
        result.remove("静妃")
    if "掌柜" in result:
        # S10-07 only needs the receiving hand; the functional shopkeeper has
        # no stable visible face and must not consume a new identity slot.
        result.remove("掌柜")
    fallbacks = {
        "E43-S01": ["白鲤", "陈问孝"], "E43-S02": ["陈迹"], "E43-S03": ["陈迹"],
        "E43-S04": ["陈问宗", "佘登科", "陈迹"], "E43-S05": ["白鲤", "世子", "小和尚"],
        "E43-S06": ["林朝京", "陈迹", "佘登科", "刘曲星"], "E43-S07": ["陈迹"],
        "E43-S08": ["陈迹", "佘登科", "刘曲星"], "E43-S09": ["陈迹", "白鲤", "梁猫儿"],
        "E43-S10": ["梁猫儿", "白鲤"], "E43-S11": ["刘曲星", "白鲤", "陈迹"],
        "E43-S12": ["世子", "小和尚", "陈迹"],
    }
    if not result:
        result = fallbacks[scene][:2]
    if shot["shot_id"] == "E43-S01-01":
        result = ["席间宾客"]
    if shot["shot_id"] == "E43-S01-06":
        result = []
    if shot["shot_id"] == "E43-S07-05":
        result = ["席间宾客"]
    if shot["shot_id"] == "E43-S08-05":
        result = []
    return list(dict.fromkeys(result))


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
        "schema": "qingshan.episode_global_space_map.v1", "episode": "E43",
        "episode_global_space_map_id": EPISODE_MAP_ID, "map_version": 1,
        "authority_ref": "ROGER-20260828-E43-COMPLETE-MAP-MODE", "status": "PENDING",
        "inheritance": {"mode": "COMPOSED", "note": "飞白池与凉亭继承 E42 拓扑语义；回廊、政和街、医馆门口与穆新斋依 E43 v6 完整补图。"},
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
            "position": [round(cx + index * .32, 2), round(cy, 2)], "facing": "camera_or_scene_partner",
        } for index, name in enumerate(visible_cast(shot))]
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
    auth_template = PROD / "E43_V6_EPISODE_GLOBAL_SPACE_MAP_TEMPLATE_V1.json"
    shot_template = PROD / "E43_V6_COMPLETE_MAP_SHOT_PLAN_V1.json"
    write_json(auth_template, authority)
    write_json(shot_template, {
        "schema": "qingshan.complete_map_shot_plan.v1", "episode": "E43", "canonical_version": 6,
        "global_space_map_gate_required": True,
        "episode_global_space_map_ref": "workflow/claude_writer_agent/production/e43_v6_20260828/E43_V6_EPISODE_GLOBAL_SPACE_MAP_AUTHORITY_LOCKED_V1.json",
        "tasks": tasks,
    })
    locked, plan, receipt = render_maps(authority, json.loads(shot_template.read_text()), ASSETS)
    auth_locked = PROD / "E43_V6_EPISODE_GLOBAL_SPACE_MAP_AUTHORITY_LOCKED_V1.json"
    plan_locked = PROD / "E43_V6_COMPLETE_MAP_SHOT_PLAN_LOCKED_V1.json"
    render_receipt = PROD / "E43_V6_COMPLETE_MAP_RENDER_RECEIPT_V1.json"
    write_json(auth_locked, locked)
    write_json(plan_locked, plan)
    receipt.update({
        "authority_path": str(auth_locked.relative_to(ROOT)), "authority_sha256": sha(auth_locked),
        "shot_plan_path": str(plan_locked.relative_to(ROOT)), "shot_plan_sha256": sha(plan_locked),
    })
    write_json(render_receipt, receipt)
    gate = evaluate_batch(locked, plan["tasks"], episode="E43", required=False)
    gate_path = QA / "E43_V6_COMPLETE_MAP_MODE_GATE_V1.json"
    write_json(gate_path, gate)
    lock = {
        "schema": "qingshan.complete_map_mode_lock.v1", "episode": "E43", "canonical_version": 6,
        "status": gate["status"], "policy": "E42+ complete map mode is non-bypassable.",
        "counts": {"episode_maps": 1, "place_maps": len(locked["space_maps"]), "shot_subspace_maps": len(plan["tasks"])},
        "authority": {"path": str(auth_locked.relative_to(ROOT)), "sha256": sha(auth_locked)},
        "shot_plan": {"path": str(plan_locked.relative_to(ROOT)), "sha256": sha(plan_locked)},
        "render_receipt": {"path": str(render_receipt.relative_to(ROOT)), "sha256": sha(render_receipt)},
        "gate_report": {"path": str(gate_path.relative_to(ROOT)), "sha256": sha(gate_path)},
        "generation_contract": {"path": str(CONTRACT.relative_to(ROOT)), "sha256": sha(CONTRACT)},
    }
    write_json(PROD / "E43_V6_COMPLETE_MAP_MODE_LOCK_V1.json", lock)
    if gate["status"] != "PASS":
        raise ValueError("E43 complete map gate failed")
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
            "screen_slot": "CENTER" if index == 0 else ("LEFT_THIRD" if index % 2 else "RIGHT_THIRD"),
            "depth_plane": "PRIMARY_ACTION_PLANE" if index == 0 else "REACTION_PLANE",
            "face_visibility": "VISIBLE_PER_FRAME_CONTENT", "identity_card_required": True,
        } for index, actor in enumerate((map_row["blocking"] or {}).get("characters") or [])]
        dialogue = str(row.get("dialogue") or "")
        if dialogue.startswith("静妃："):
            cast.append({
                "character": "静妃", "screen_slot": "OFFSCREEN", "depth_plane": "BEHIND_CURTAIN",
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
        "schema": "qingshan.editorial_seedance_manifest.v2_performance_complete", "episode": "E43",
        "canonical_version": 6, "source_generation_contract": str(CONTRACT.relative_to(ROOT)),
        "source_generation_contract_sha256": sha(CONTRACT),
        "complete_map_shot_plan": str((PROD / "E43_V6_COMPLETE_MAP_SHOT_PLAN_LOCKED_V1.json").relative_to(ROOT)),
        "complete_map_shot_plan_sha256": sha(PROD / "E43_V6_COMPLETE_MAP_SHOT_PLAN_LOCKED_V1.json"),
        "model_contract": {"model": "seedance-2.0-pro", "resolution": "720p", "aspect_ratio": "9:16", "route": "STANDARD_MULTI_REFERENCE"},
        "shots": shots,
    }
    write_json(PROD / "E43_V6_EDITORIAL_SEEDANCE_MANIFEST_V1.json", result)
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
    family, direction = CAMERA_SEQUENCE[index - 1]
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
        "authorship": "DIRECTOR_AUTHORED_E43_V6",
    }


def build_units(editorial: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    shots = editorial["shots"]
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
        "episode": "E43", "runtime_seconds": 180.0,
        "source": {"canonical_script": str(CANONICAL.relative_to(ROOT)), "script_sha256": sha(CANONICAL),
                   "generation_contract": str(CONTRACT.relative_to(ROOT)), "generation_contract_sha256": sha(CONTRACT)},
        "production_overlay": {
            "authorization_ref": "ROGER-20260828-START-E43-PRODUCTION", "mode": "director", "language": "zh",
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
            "unit_id": f"E43-VU-{index:03d}", "editorial_shot_ids": [x["shot_id"] for x in group],
            "action_unit": True,
            "narrative_beat": " → ".join(str(x["prompt_spec"]["action"]["primary_action"]) for x in group),
            "camera_plan": camera,
        }
        if not 5 <= duration <= 8:
            row["duration_exception_reason"] = "SCENE_LOCAL_CONTINUOUS_CAUSAL_ACTION"
        spec_groups.append(row)
    shot_by_id = {row["shot_id"]: row for row in shots}
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
        "episode": "E43", "source_script_sha256": sha(CANONICAL),
        "duration_policy_seconds": {"minimum": 3, "maximum": 12, "authority": "GIGGLE-SEEDANCE2-4-15S+ROGER-20260828-E43"},
        "preferred_duration_seconds": {"minimum": 5, "maximum": 8}, "groups": spec_groups,
    }
    prod_path = PROD / "E43_V6_EDITORIAL_PRODUCTION_MANIFEST_V1.json"
    spec_path = PROD / "E43_V6_VIDEO_UNIT_GROUPING_SPEC_V1.json"
    plan_path = PROD / "E43_V6_VIDEO_UNIT_GROUPING_PLAN_V1.json"
    write_json(prod_path, production)
    write_json(spec_path, spec)
    plan = compile_grouping_spec(production, spec)
    write_json(plan_path, plan)
    gate = evaluate_grouping(plan)
    gate.update({
        "schema": "qingshan.video_unit_grouping_gate_report.v2_transition_contract", "episode": "E43",
        "production_manifest": str(prod_path.relative_to(ROOT)), "production_manifest_sha256": sha(prod_path),
        "grouping_spec": str(spec_path.relative_to(ROOT)), "grouping_spec_sha256": sha(spec_path),
        "grouping_plan": str(plan_path.relative_to(ROOT)), "grouping_plan_sha256": sha(plan_path),
    })
    write_json(QA / "E43_V6_VIDEO_UNIT_GROUPING_GATE_V1.json", gate)
    if gate["status"] != "PASS":
        raise ValueError("E43 video-unit grouping gate failed")
    return spec, plan


def main() -> int:
    source = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if source.get("episode") != "E43" or source.get("version") != 6:
        raise ValueError("E43 v6 generation contract required")
    _authority, map_plan = build_complete_map(source)
    editorial = build_editorial(source, map_plan)
    _spec, plan = build_units(editorial)
    summary = {
        "schema": "qingshan.e43_v6_preproduction_summary.v1", "episode": "E43", "status": "PASS",
        "canonical_version": 6, "map_mode": "COMPLETE", "place_map_count": 6,
        "editorial_shot_count": len(editorial["shots"]), "video_unit_count": plan["video_unit_count"],
        "transition_boundary_count": max(0, plan["video_unit_count"] - 1),
        "model_contract": editorial["model_contract"],
        "paid_post_allowed": False,
        "next_gate": "GENERATE_AND_ADMIT_SEMANTIC_START_FRAMES_THEN_COMPILE_PROMPTS",
    }
    write_json(QA / "E43_V6_PREPRODUCTION_SUMMARY_V1.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
