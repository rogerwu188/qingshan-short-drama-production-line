#!/usr/bin/env python3
"""Build E46 v6 H3 complete-map and prompt-ready preproduction contracts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.build_video_unit_grouping_spec import build as derive_groups
from tools.compile_video_unit_plan import compile_grouping_spec
from tools.global_space_layout_gate import RESOLUTION_ORDER, evaluate_batch
from tools.grouped_transition_contract import boundary_id
from tools.render_global_space_map_assets import build as render_maps
from tools.video_unit_grouping_gate import evaluate as evaluate_grouping


CONTRACT = ROOT / "workflow/claude_writer_agent/scripts/E46_GENERATION_CONTRACT_v6.json"
CANONICAL = ROOT / "workflow/claude_writer_agent/scripts/E46_NARRATIVE_CANONICAL_v6.md"
PROD = ROOT / "workflow/claude_writer_agent/production/e46_v6_20260829"
QA = ROOT / "qa/e46_v6_preproduction_20260829"
ASSETS = ROOT / "artifacts/e46_v6/complete_map_mode_v1"
EPISODE_MAP_ID = "EGSM-E46-YIGUAN-JINGCHENG-WANGSHI-V1"
GLOBAL_SPACE = "GLOBAL-SPACE-E46-YIGUAN-ZHENGTANG-HOUYUAN-JINGCHENG-XUEZHONG-WUYAN-TAIYIYUAN"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def zone(zone_id: str, name: str, x0: float, y0: float, x1: float, y1: float) -> dict[str, Any]:
    return {"zone_id": zone_id, "name": name, "polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


MAP_DEFS = {
    "LOC-TAIPING-YIGUAN-ZHENGTANG": (
        "GSM-E46-YIGUAN-HALL-V1", "ROOM-E46-YIGUAN-HALL", 20, 14,
        [zone("ZONE-HALL-COUNTER", "柜台、白晶与陶碗", 1, 1, 9, 6),
         zone("ZONE-HALL-LONG-TABLE", "长案、炭盆与油灯", 7, 5, 16, 11),
         zone("ZONE-HALL-MEDICINE-WALL", "无可读字药柜、窗纸与屋梁", 14, 2, 20, 14),
         zone("ZONE-HALL-DOOR", "正堂门槛与后院方向", 0, 8, 6, 14)],
    ),
    "LOC-TAIPING-YIGUAN-HOUYUAN": (
        "GSM-E46-YIGUAN-COURTYARD-V1", "ROOM-E46-YIGUAN-COURTYARD", 20, 16,
        [zone("ZONE-COURTYARD-CORRIDOR", "走廊、廊柱与竹躺椅", 0, 0, 12, 6),
         zone("ZONE-COURTYARD-YAO-DOOR", "姚老头房门与堂屋漏光", 12, 0, 20, 6),
         zone("ZONE-COURTYARD-CENTER", "后院中央与竹凳", 3, 6, 15, 14),
         zone("ZONE-COURTYARD-GATE", "院门与院墙外屋脊", 15, 6, 20, 16)],
    ),
    "LOC-JINGCHENG-XUEZHONG-WUYAN": (
        "GSM-E46-SNOW-EAVES-V1", "ROOM-E46-SNOW-EAVES", 24, 16,
        [zone("ZONE-SNOW-EAVES", "积雪屋檐与雪拱", 0, 0, 12, 7),
         zone("ZONE-SNOW-COURTYARD", "跪雪宅院与冰壳", 6, 7, 18, 16),
         zone("ZONE-SNOW-LANE", "三顶软轿经过的巷道", 12, 0, 24, 8)],
    ),
    "LOC-JINGCHENG-TAIYIYUAN": (
        "GSM-E46-IMPERIAL-MEDICAL-INSTITUTE-V1", "ROOM-E46-TAIYIYUAN", 20, 14,
        [zone("ZONE-TAIYIYUAN-DESK", "案、素面铜钱与背面朝上生辰帖", 1, 1, 10, 7),
         zone("ZONE-TAIYIYUAN-SICKBED", "病榻、搭脉位与垂手", 9, 4, 18, 12),
         zone("ZONE-TAIYIYUAN-WINDOW", "雪光窗与油灯", 1, 8, 9, 14)],
    ),
}

CHAR_IDS = {
    "陈迹": "CHAR-E46-CHENJI", "姚老头": "CHAR-E46-YAO-CURRENT",
    "年轻姚老头": "CHAR-E46-YAO-YOUNG", "幼年养子": "CHAR-E46-SON-CHILD",
    "十六岁养子": "CHAR-E46-SON-SIXTEEN", "成年养子": "CHAR-E46-SON-ADULT",
    "工部监丞": "CHAR-E46-OFFICIAL", "乌云": "CHAR-E46-WUYUN", "乌鸦": "CHAR-E46-CROW",
}
ANIMALS = {"乌云", "乌鸦"}
PROP_WORDS = {
    "白晶": "PROP-E46-WHITE-CRYSTAL", "陶碗": "PROP-E46-CLAY-BOWL", "纸包": "PROP-E46-PAPER-PACKET",
    "纸": "PROP-E46-PAPER", "炭盆": "PROP-E46-BRAZIER", "油灯": "PROP-E46-OIL-LAMP",
    "灯焰": "PROP-E46-LAMP-FLAME", "人参": "PROP-E46-GINSENG", "竹躺椅": "PROP-E46-BAMBOO-RECLINER",
    "生辰帖": "PROP-E46-BIRTH-SLIP-FACE-DOWN", "铜钱": "PROP-E46-WORN-BLANK-COINS",
    "药方": "PROP-E46-UNREADABLE-PRESCRIPTION", "汤药": "PROP-E46-MEDICINE-BOWL", "竹凳": "PROP-E46-BAMBOO-STOOL",
}

WARDROBE_BIBLE = {
    "bible_id": "E46-V6-WARDROBE-IDENTITY-BIBLE-V1", "animal_characters": sorted(ANIMALS),
    "characters": [
        {"character": "陈迹", "social_tier": "TRAVELING_INVESTIGATOR", "role_basis": "医馆徒弟兼隐秘官署关系人",
         "silhouette": "窄袖直身、便于动作的长袍轮廓", "outer_layer": "深靛青细密斜纹交领长袍", "inner_layer": "灰蓝细棉窄袖内衫",
         "primary_color": "深靛青", "secondary_color": "灰蓝", "material": "细棉与耐磨斜纹布", "pattern": "领缘极低对比回纹",
         "belt_or_fastening": "乌木色窄革带", "footwear": "黑色软底短靴", "accessory": "低调铜扣与暗袋", "condition": "整洁但袖口有轻微药灰",
         "continuity_key": "E46-CHENJI-INDIGO-V1"},
        {"character": "姚老头", "social_tier": "SENIOR_PHYSICIAN", "role_basis": "阅历深、生活节俭但非贫民的医馆主人",
         "silhouette": "宽袖叠领、肩背略弯的长袍轮廓", "outer_layer": "墨褐旧缎面宽袖外袍", "inner_layer": "沉香色细棉中衣",
         "primary_color": "墨褐", "secondary_color": "沉香与暗铜", "material": "旧缎面与细棉", "pattern": "袖缘药草暗纹",
         "belt_or_fastening": "深褐布带与旧铜环", "footwear": "棕黑布面履", "accessory": "药香木珠一枚", "condition": "保养得当、边缘磨旧",
         "continuity_key": "E46-YAO-CURRENT-INK-BROWN-V1"},
        {"character": "年轻姚老头", "social_tier": "IMPERIAL_PHYSICIAN_YOUNG", "role_basis": "五十三年前尚未白头的太医",
         "silhouette": "挺直肩线、宽襟收腰的官医常服", "outer_layer": "深松绿细呢交领袍", "inner_layer": "月白细绢内衫",
         "primary_color": "深松绿", "secondary_color": "月白", "material": "细呢与细绢", "pattern": "暗压云雷纹",
         "belt_or_fastening": "深绿织带配素铜扣", "footwear": "黑色官靴", "accessory": "素面药囊", "condition": "洁净、雪水打湿下摆",
         "continuity_key": "E46-YAO-YOUNG-PINE-V1"},
        {"character": "幼年养子", "social_tier": "RESCUED_CHILD", "role_basis": "雪中获救、后被收养的明确幼童",
         "silhouette": "小体量层叠保暖轮廓", "outer_layer": "赭红补片小棉袍", "inner_layer": "烟灰棉布内衣",
         "primary_color": "赭红", "secondary_color": "烟灰", "material": "旧棉布与棉絮", "pattern": "无纹样、仅有方形补片",
         "belt_or_fastening": "布绳系带", "footwear": "旧棉鞋", "accessory": "无配饰", "condition": "冻湿、获救后裹入成人外袍",
         "continuity_key": "E46-SON-CHILD-OCHRE-V1"},
        {"character": "十六岁养子", "social_tier": "PHYSICIAN_APPRENTICE", "role_basis": "十六岁的太医养子与学徒",
         "silhouette": "少年修长、窄袖医者学徒袍", "outer_layer": "青灰窄袖交领袍", "inner_layer": "淡米白细棉内衫",
         "primary_color": "青灰", "secondary_color": "淡米白", "material": "细棉与薄呢", "pattern": "袖口单道深青压线",
         "belt_or_fastening": "深青织带", "footwear": "灰黑软底靴", "accessory": "小药囊", "condition": "整洁",
         "continuity_key": "E46-SON-SIXTEEN-BLUEGRAY-V1"},
        {"character": "成年养子", "social_tier": "DISGRACED_PHYSICIAN", "role_basis": "犯错后在雪中认错的成年养子",
         "silhouette": "成年修长、衣摆被雪压重的医者袍", "outer_layer": "暗青长袍", "inner_layer": "灰白细棉内衫",
         "primary_color": "暗青", "secondary_color": "灰白", "material": "细棉与旧薄呢", "pattern": "无显眼纹样",
         "belt_or_fastening": "暗灰织带", "footwear": "湿透黑靴", "accessory": "旧药囊", "condition": "跪雪后湿冷有折痕",
         "continuity_key": "E46-SON-ADULT-DARKTEAL-V1"},
        {"character": "工部监丞", "social_tier": "COURT_OFFICIAL", "role_basis": "病榻上的工部官员",
         "silhouette": "病中官袍宽肩轮廓", "outer_layer": "黯绯无字官常服", "inner_layer": "米白中衣",
         "primary_color": "黯绯", "secondary_color": "米白", "material": "细呢与绢", "pattern": "不可辨识低对比织纹",
         "belt_or_fastening": "素黑革带", "footwear": "病榻上不见鞋履", "accessory": "无可读官阶标识", "condition": "病中褶皱明显",
         "continuity_key": "E46-OFFICIAL-MAROON-V1"},
    ],
}


def place_map(location: str, scenes: list[dict[str, Any]]) -> dict[str, Any]:
    map_id, room_id, width, depth, zones = MAP_DEFS[location]
    axes, cameras, fixed = [], [], []
    for row in zones:
        xs, ys = [p[0] for p in row["polygon"]], [p[1] for p in row["polygon"]]
        cx, cy = sum(xs) / 4, sum(ys) / 4
        suffix = row["zone_id"].removeprefix("ZONE-")
        axes.append({"axis_id": f"AXIS-{suffix}", "endpoint_a": [min(xs), cy], "endpoint_b": [max(xs), cy],
                     "default_screen_direction": "WEST_LEFT_EAST_RIGHT", "crossing_policy": "NO_CROSS_WITHOUT_VISIBLE_REESTABLISH"})
        cameras.append({"angle_id": f"ANGLE-{suffix}-LOCKED", "zone_id": row["zone_id"], "position": [cx, min(ys) + .4],
                        "facing": "north", "axis_id": f"AXIS-{suffix}", "screen_direction": "WEST_LEFT_EAST_RIGHT"})
        fixed.append({"element_id": f"FIXED-{suffix}", "type": "location_anchor", "zone_id": row["zone_id"],
                      "position": [cx, cy], "traversable": True})
    return {"global_space_map_id": map_id, "map_version": 1, "name": location,
            "coordinate_system": {"origin": "southwest", "x_axis": "east", "y_axis": "north", "unit": "m"},
            "overall_bounds": {"width": width, "depth": depth}, "layout_image": {},
            "rooms": [{"room_id": room_id, "zones": zones, "fixed_elements": fixed,
                       "entrances": [{"entrance_id": f"ENTRY-{room_id}", "zone_id": zones[0]["zone_id"], "position": [0, 1]}],
                       "axes": axes, "camera_positions": cameras}],
            "scene_mappings": [{"scene_id": s["scene_id"], "room_id": room_id, "zone_ids": [z["zone_id"] for z in zones]}
                               for s in scenes if s["location_id"] == location]}


def zone_for(location: str, subspace: str) -> str:
    if location.endswith("ZHENGTANG"):
        if any(x in subspace for x in ("GUITAI", "BAIJING", "TAOWAN", "ZHIBAO")): return "ZONE-HALL-COUNTER"
        if any(x in subspace for x in ("YAOGUI", "CHUANGZHI", "WUYA", "LIANG")): return "ZONE-HALL-MEDICINE-WALL"
        if any(x in subspace for x in ("MENKAN", "MEN")): return "ZONE-HALL-DOOR"
        return "ZONE-HALL-LONG-TABLE"
    if location.endswith("HOUYUAN"):
        if any(x in subspace for x in ("MENHE", "HUIWU")): return "ZONE-COURTYARD-YAO-DOOR"
        if any(x in subspace for x in ("YUANMEN", "WUJI", "DAHUO")): return "ZONE-COURTYARD-GATE"
        if any(x in subspace for x in ("ZOULANG", "ZHUYI")): return "ZONE-COURTYARD-CORRIDOR"
        return "ZONE-COURTYARD-CENTER"
    if location.endswith("XUEZHONG-WUYAN"):
        if any(x in subspace for x in ("RUANJIAO", "XIANGZI")): return "ZONE-SNOW-LANE"
        if any(x in subspace for x in ("GUIXUE", "SANTIAN", "YAOFANG", "TANGYAO")): return "ZONE-SNOW-COURTYARD"
        return "ZONE-SNOW-EAVES"
    if any(x in subspace for x in ("BINGCHENG", "JIANCHENG", "DAMAI")): return "ZONE-TAIYIYUAN-SICKBED"
    if any(x in subspace for x in ("DENGYAN", "HUITOU")): return "ZONE-TAIYIYUAN-WINDOW"
    return "ZONE-TAIYIYUAN-DESK"


def cast_for(shot: dict[str, Any]) -> list[str]:
    sid, scene = shot["shot_id"], shot["scene_id"]
    if scene in {"E46-S01", "E46-S02", "E46-S03", "E46-S04", "E46-S05", "E46-S06", "E46-S08"}: return ["陈迹", "姚老头"]
    if scene == "E46-S07": return ["年轻姚老头"] + (["幼年养子"] if sid.endswith(("03", "04")) else [])
    if scene == "E46-S09":
        if sid.endswith(("01", "02", "03", "04")): return ["年轻姚老头", "幼年养子"]
        if sid.endswith("06"): return ["十六岁养子", "工部监丞"]
        return ["十六岁养子"]
    if scene == "E46-S10": return ["成年养子", "姚老头"]
    if scene == "E46-S11": return ["陈迹", "姚老头"] + (["乌鸦"] if sid.endswith("04") else []) + (["乌云"] if sid.endswith("05") else [])
    if scene == "E46-S12": return ["陈迹", "姚老头", "乌云"]
    return []


def build_map(source: dict[str, Any]) -> dict[str, Any]:
    authority = {"schema": "qingshan.episode_global_space_map.v1", "episode": "E46", "episode_global_space_map_id": EPISODE_MAP_ID,
                 "map_version": 1, "authority_ref": "ROGER-20260829-START-E46-COMPLETE-MAP-H3", "status": "PENDING",
                 "inheritance": {"mode": "COMPOSED", "note": "医馆继承既有拓扑；往事的雪中屋檐和太医院按 ch51 新建且不使用回忆滤镜。"},
                 "map_image": {}, "space_maps": [place_map(k, source["scene_states"]) for k in MAP_DEFS]}
    scene_by_id = {s["scene_id"]: s for s in source["scene_states"]}
    tasks = []
    for shot in source["shots"]:
        scene = scene_by_id[shot["scene_id"]]; location = scene["location_id"]; zid = zone_for(location, shot["subspace_id"])
        map_id, room_id, _w, _d, zones = MAP_DEFS[location]; z = next(x for x in zones if x["zone_id"] == zid)
        xs, ys = [p[0] for p in z["polygon"]], [p[1] for p in z["polygon"]]; cx, cy = sum(xs)/4, sum(ys)/4
        suffix = zid.removeprefix("ZONE-")
        chars = [{"character_id": CHAR_IDS[n], "zone_id": zid, "position": [round(cx + (i-len(cast_for(shot))/2)*.55,2), round(cy,2)],
                  "facing": "camera_or_scene_partner"} for i,n in enumerate(cast_for(shot))]
        text = " ".join(str(shot.get(k) or "") for k in ("frame_content","dialogue","first_frame_motion_state"))
        prop_ids = list(dict.fromkeys(v for k,v in PROP_WORDS.items() if k in text))
        props = [{"prop_id": p, "zone_id": zid, "position": [round(cx,2), round(cy+.4+i*.2,2)], "facing": "camera"} for i,p in enumerate(prop_ids)]
        tasks.append({"task_key": f"{shot['shot_id']}-MAP-LOCK-V1", "unit_id": shot["shot_id"], "tool_type": "image_generation",
                      "spatial_layout_stage": "SHOT_KEYFRAME", "scene_id": shot["scene_id"], "episode_global_space_map_id": EPISODE_MAP_ID,
                      "global_space_map_id": map_id, "room_id": room_id, "zone_id": zid, "angle_id": f"ANGLE-{suffix}-LOCKED",
                      "resolution_order": RESOLUTION_ORDER, "subspace_layout": {"subspace_id": shot["subspace_id"],
                      "derived_from_episode_global_space_map_id": EPISODE_MAP_ID, "derived_from_global_space_map_id": map_id,
                      "room_id": room_id, "zone_ids": [zid], "angle_id": f"ANGLE-{suffix}-LOCKED", "camera_position_id": f"ANGLE-{suffix}-LOCKED",
                      "axis_id": f"AXIS-{suffix}", "visible_fixed_element_ids": [f"FIXED-{suffix}"], "polygon": z["polygon"]},
                      "blocking": {"resolved_after_subspace_lock": True, "characters": chars, "props": props},
                      "action_end_blocking": {"characters": chars, "props": props}, "trajectory_overlays": [], "entity_reference_bindings": [],
                      "source_shot_contract": {"path": str(CONTRACT.relative_to(ROOT)), "sha256": sha(CONTRACT), "shot_id": shot["shot_id"],
                      "camera": shot["camera"], "action": shot["frame_content"], "completion_state": shot["first_frame_motion_state"]}})
    template = PROD / "E46_V6_COMPLETE_MAP_SHOT_PLAN_V1.json"; write_json(template, {"schema":"qingshan.complete_map_shot_plan.v1",
        "episode":"E46","canonical_version":6,"global_space_map_gate_required":True,"tasks":tasks})
    locked, plan, receipt = render_maps(authority, json.loads(template.read_text()), ASSETS)
    auth_path = PROD/"E46_V6_EPISODE_GLOBAL_SPACE_MAP_AUTHORITY_LOCKED_V1.json"; plan_path=PROD/"E46_V6_COMPLETE_MAP_SHOT_PLAN_LOCKED_V1.json"
    write_json(auth_path,locked);write_json(plan_path,plan);write_json(PROD/"E46_V6_COMPLETE_MAP_RENDER_RECEIPT_V1.json",receipt)
    gate=evaluate_batch(locked,plan["tasks"],episode="E46",required=True);write_json(QA/"E46_V6_COMPLETE_MAP_MODE_GATE_V1.json",gate)
    if gate["status"]!="PASS": raise ValueError(gate)
    write_json(PROD/"E46_V6_COMPLETE_MAP_MODE_LOCK_V1.json",{"schema":"qingshan.complete_map_mode_lock.v1","episode":"E46","canonical_version":6,
        "status":"PASS","counts":{"episode_maps":1,"place_maps":len(MAP_DEFS),"shot_subspace_maps":len(tasks)},
        "authority":{"path":str(auth_path.relative_to(ROOT)),"sha256":sha(auth_path)},"shot_plan":{"path":str(plan_path.relative_to(ROOT)),"sha256":sha(plan_path)}})
    return plan


def build_editorial(source: dict[str, Any], map_plan: dict[str, Any]) -> dict[str, Any]:
    mapped={x["unit_id"]:x for x in map_plan["tasks"]}; states={x["scene_id"]:x for x in source["scene_states"]}
    bible={x["character"]:x for x in WARDROBE_BIBLE["characters"]}; shots=[]
    for row in source["shots"]:
        names=cast_for(row); scene=states[row["scene_id"]]; dialogue=str(row.get("dialogue") or "")
        cast=[{"character":n,"entity_type":"ANIMAL" if n in ANIMALS else "HUMAN","screen_slot":f"SLOT_{i+1}",
               "depth_plane":"PRIMARY_ACTION_PLANE" if i<2 else "REACTION_PLANE","face_visibility":"VISIBLE_PER_FRAME_CONTENT",
               "identity_card_required":n not in ANIMALS} for i,n in enumerate(names)]
        speaker=dialogue.partition("：")[0].strip() if "：" in dialogue else ""
        aliases={"养子":"成年养子"}
        actual_speaker=aliases.get(speaker,speaker)
        if actual_speaker and actual_speaker not in names:
            cast.append({"character":actual_speaker,"entity_type":"HUMAN","screen_slot":"OFFSCREEN","depth_plane":"OFFSCREEN_SOURCE",
                         "face_visibility":"OFFSCREEN_VOICE_ONLY","identity_card_required":False})
        props=[{"prop":p["prop_id"],"anchor":"PRIMARY_ACTION_PLANE","continuity_scope":"SCENE_OR_RECURRING_PROP"}
               for p in (mapped[row["shot_id"]]["blocking"].get("props") or [])]
        action=str(row.get("first_frame_motion_state") or row["frame_content"])
        shots.append({"shot_id":row["shot_id"],"scene_id":row["scene_id"],"duration_seconds":row["duration_seconds"],"model":"MiniMax-H3",
          "resolution":"768p","aspect_ratio":"9:16","prompt_spec":{"space":{"global":GLOBAL_SPACE,"location":scene["location_id"],"subspace":row["subspace_id"]},
          "scene_state":{"time":scene["time_of_day_state"],"weather":scene["weather_state"],"palette":scene["palette_temperature"]},
          "cast":cast,"props":props,"camera":row["camera"],"action":{"t0_seconds":row["start_seconds"],"t1_seconds":round(row["start_seconds"]+row["duration_seconds"],3),
          "start_state":action,"primary_action":row["frame_content"],"completion_state":action,"contact_point":"当前镜明确动作或反应落点",
          "motion_direction":"单一方向完成后保持，不循环复位","physical_causality":"动作或人声先发生，眼神、下颌、肩颈和重心依次响应",
          "freeze_or_speed_ramp_forbidden":True,"microexpression_design":"眼神先于头部，只在因果点发生一次细微变化并保持",
          "physical_action_design":"接触动作一次完成，尾帧保留呼吸、衣料和道具惯性微动"},
          "performance":{"psychological_state":"只处理当前事件，不预演下一拍","expression_arc":"克制观察到事件落点后的细微确认",
          "continuous_micro_action":"呼吸连续，眼神先动，下颌与肩颈随后","body_sync":"身体重心最后完成并保持"},
          "dialogue":dialogue,"dialogue_delivery":{"pace":"自然克制，按原文停连，不播报提示词"} if dialogue else None,
          "sound_design":{"ambience":"同场景原生空间底声连续","foley":"衣料、脚步与道具真实接触声","action_sound":"只强化当前因果动作接触声"},
          "audio_contract":"SAME_VIDEO_TASK_NATIVE_AUDIO" if dialogue else "DIEGETIC_OR_SILENT_NO_TTS","negative_prompts":row.get("negative_prompts") or []},
          "wardrobe_contract":{"schema":"qingshan.wardrobe_identity_contract.v1_role_and_peer_distinction","animal_characters":sorted(ANIMALS),
                               "characters":[bible[n] for n in names if n not in ANIMALS]}})
    result={"schema":"qingshan.editorial_h3_manifest.v2_dialogue_isolation","episode":"E46","canonical_version":6,
            "source_generation_contract":str(CONTRACT.relative_to(ROOT)),"source_generation_contract_sha256":sha(CONTRACT),
            "model_contract":{"model":"MiniMax-H3","resolution":"768p","native_raster":"768x1366","delivery_raster":"1440x2560",
                              "delivery_upscale":"HIGH_QUALITY_2K_RELEASE_UPSCALE","aspect_ratio":"9:16","route":"STANDARD_MULTI_REFERENCE"},
            "post_generation_required_gates":["TECHNICAL_MEDIA","BASIC_PLOT_IDENTITY","H3_NATIVE_AUDIO_DIALOGUE_WHITELIST","REAL_MEDIA_BOUNDARY"],
            "shots":shots}
    write_json(PROD/"E46_V6_EDITORIAL_H3_MANIFEST_V1.json",result);write_json(PROD/"E46_V6_WARDROBE_IDENTITY_BIBLE_V1.json",WARDROBE_BIBLE)
    return result


def build_units(editorial: dict[str, Any]) -> dict[str, Any]:
    production,spec=derive_groups(editorial,sha(CANONICAL));shot_by_id={x["shot_id"]:x for x in editorial["shots"]}
    production.update({"source":{"canonical_script":str(CANONICAL.relative_to(ROOT)),"script_sha256":sha(CANONICAL),
                                 "generation_contract":str(CONTRACT.relative_to(ROOT)),"generation_contract_sha256":sha(CONTRACT)},
                       "production_overlay":{"authorization_ref":"ROGER-20260829-START-E46-H3-PRODUCTION","model":"MiniMax-H3","resolution":"768p",
                       "aspect_ratio":"9:16","route":"STANDARD_MULTI_REFERENCE","complete_map_mode_required":True,
                       "h3_dialogue_whitelist_required":True,"paid_submit_requires_all_registered_prechecks_pass":True}})
    for index,row in enumerate(spec["groups"]):
        row["internal_transition_contracts"]=[]
        if index==0: continue
        prev=spec["groups"][index-1]; a=shot_by_id[prev["editorial_shot_ids"][-1]]; b=shot_by_id[row["editorial_shot_ids"][0]]
        same_location=a["prompt_spec"]["space"]["location"]==b["prompt_spec"]["space"]["location"]
        same_subspace=a["prompt_spec"]["space"]["subspace"]==b["prompt_spec"]["space"]["subspace"]
        source_state=a["prompt_spec"]["action"]["completion_state"];target_state=b["prompt_spec"]["action"]["start_state"]
        row["transition_contract"]={"boundary_id":boundary_id(prev["unit_id"],row["unit_id"]),"from_unit_id":prev["unit_id"],"to_unit_id":row["unit_id"],
          "authorship":"DIRECTOR_AUTHORED","cut_reason":"CONTINUOUS_ACTION" if same_subspace else ("NEW_SPACE_MATCH_CUT" if same_location else "SOUND_BRIDGE_NEW_SPACE"),
          "space_relation":"SAME_SUBSPACE" if same_subspace else ("SAME_LOCATION_NEW_SUBSPACE" if same_location else "NEW_LOCATION_SAME_GLOBAL"),
          "transition_device":"ACTION_MATCH" if same_location else "SOUND_BRIDGE",
          "outgoing_handle_seconds":1.0,"incoming_handle_seconds":0.8,"plot_motivation":f"前一结果触发后一拍，不插入无关空镜。",
          "visual_bridge":f"前段保持{source_state}，下一段从{target_state}承接。","action_bridge":f"{source_state} -> {target_state}",
          "sound_bridge":"前段现场声尾跨过切点，下一段首个真实声接管；人声不得截断。","axis_strategy":"保持地图既定人物轴；跨时空以固定物和声桥重建。",
          "continuity_intent":"剧情、人物、服装、道具、地图、光向与声音连续。","source_terminal_state":{"scene_id":a["scene_id"],"space":a["prompt_spec"]["space"],
          "camera_framing":prev["camera_plan"]["end_framing"],"camera_side":prev["camera_plan"]["camera_side"],"blocking":source_state},
          "target_initial_state":{"scene_id":b["scene_id"],"space":b["prompt_spec"]["space"],"camera_framing":row["camera_plan"]["start_framing"],
          "camera_side":row["camera_plan"]["camera_side"],"blocking":target_state},"anchor_semantic_requirements":{"target_visible_characters":[x["character"] for x in b["prompt_spec"]["cast"] if x["face_visibility"]!="OFFSCREEN_VOICE_ONLY"],
          "target_visible_props":[x["prop"] for x in b["prompt_spec"]["props"]],"target_space_anchors":[b["prompt_spec"]["space"]["location"],b["prompt_spec"]["space"]["subspace"]],"empty_establishing_frame_allowed":False}}
    prod_path=PROD/"E46_V6_EDITORIAL_PRODUCTION_MANIFEST_V1.json";spec_path=PROD/"E46_V6_VIDEO_UNIT_GROUPING_SPEC_V1.json";plan_path=PROD/"E46_V6_VIDEO_UNIT_GROUPING_PLAN_V1.json"
    write_json(prod_path,production);write_json(spec_path,spec);plan=compile_grouping_spec(production,spec);write_json(plan_path,plan)
    gate=evaluate_grouping(plan);write_json(QA/"E46_V6_VIDEO_UNIT_GROUPING_GATE_V1.json",gate)
    if gate["status"]!="PASS":raise ValueError(gate)
    return plan


def main() -> int:
    source=json.loads(CONTRACT.read_text(encoding="utf-8"))
    if source.get("episode")!="E46" or source.get("version")!=6:raise ValueError("E46 v6 contract required")
    map_plan=build_map(source);editorial=build_editorial(source,map_plan);plan=build_units(editorial)
    summary={"schema":"qingshan.e46_v6_preproduction_summary.v1","episode":"E46","status":"PASS","canonical_version":6,
             "map_mode":"COMPLETE","place_map_count":len(MAP_DEFS),"editorial_shot_count":len(editorial["shots"]),
             "video_unit_count":plan["video_unit_count"],"planned_runtime_seconds":plan["runtime_seconds"],"model_contract":editorial["model_contract"],
             "h3_prompt_policy":"qingshan.minimax_h3_prompt.v2_dialogue_isolation","h3_native_audio_dialogue_whitelist_required":True,
             "adult_female_h3_policy_registered":True,"adult_female_roles_in_e46":0,"paid_post_allowed":False,
             "next_gate":"SEMANTIC_KEYFRAME_PLAN_AND_PREPAID_PROMPT_QA"}
    write_json(QA/"E46_V6_PREPRODUCTION_SUMMARY_V1.json",summary);print(json.dumps(summary,ensure_ascii=False));return 0


if __name__=="__main__":raise SystemExit(main())
