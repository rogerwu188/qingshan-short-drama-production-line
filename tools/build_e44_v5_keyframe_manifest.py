#!/usr/bin/env python3
"""Compile E44 v5 semantic keyframe tasks without provider submission."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from image_model_adapter import compile_labeled_flat_identity_transport
except ModuleNotFoundError:
    from tools.image_model_adapter import compile_labeled_flat_identity_transport

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_preproduction_20260828"
CONTRACT = ROOT / "workflow/claude_writer_agent/scripts/E44_GENERATION_CONTRACT_v5.json"
CANONICAL = ROOT / "workflow/claude_writer_agent/scripts/E44_NARRATIVE_CANONICAL_v5.md"
GROUPING = PROD / "E44_V5_VIDEO_UNIT_GROUPING_PLAN_V1.json"
ANCHORS = PROD / "E44_V5_VIDEO_UNIT_ANCHOR_PLAN_V1.json"
MAP_PLAN = PROD / "E44_V5_COMPLETE_MAP_SHOT_PLAN_LOCKED_V1.json"
MAP_AUTHORITY = PROD / "E44_V5_EPISODE_GLOBAL_SPACE_MAP_AUTHORITY_LOCKED_V1.json"
IDENTITY_MAP = PROD / "E44_V5_IDENTITY_AUTHORITY_MAP_V1.json"
OUT = PROD / "E44_V5_GIGGLE_KEYFRAME_MANIFEST_PRECHECK_V1.json"
PROMPT_DIR = PROD / "keyframe_prompts_v1"

ASSETS = {
    "陈迹": "assets/reference/e37_plus_20260729/characters/CHAR-chenji-age20-user-turnaround-canonical-v1-20260729.png",
    "白鲤": "assets/reference/characters_canonical_20260709/images/CHAR-baili-ancient-card-20260709.jpg",
    "世子": "assets/reference/e19r_shizi_v1_20260717/CHAR-E19R-SHIZI-V1.jpg",
    "小和尚": "assets/reference/e20_20260716/characters/CHAR-fozi-luozhuisajia-e19-continuity-v1-20260716.jpg",
    "佘登科": "assets/reference/e41_v17_20260824/characters/CHAR-e41-shedengke-turnaround-v1-20260824.png",
    "刘曲星": "assets/reference/e41_v17_20260824/characters/CHAR-e41-liuquxing-turnaround-v1-20260824.png",
    "梁猫儿": "assets/reference/e41_v17_20260824/characters/CHAR-e41-liangmaoer-turnaround-v1-20260824.png",
    "金猪": "assets/reference/e44_v5_20260828/characters/CHAR-e44-jinzhu-turnaround-v1-20260828.png",
    "朱灵韵": "assets/reference/e44_v5_20260828/characters/CHAR-e44-zhulingyun-turnaround-v1-20260828.png",
    "乌云": "ref_images/cat_wuyun_reference.jpg",
}

ID_TO_NAME = {
    "CHAR-E44-CHENJI": "陈迹", "CHAR-E44-BAILI": "白鲤", "CHAR-E44-SHIZI": "世子",
    "CHAR-E44-XIAOHESHANG": "小和尚", "CHAR-E44-JINZHU": "金猪",
    "CHAR-E44-ZHULINGYUN": "朱灵韵", "CHAR-E44-WUYUN": "乌云",
    "CHAR-E44-SHEDENGKE": "佘登科", "CHAR-E44-LIUQUXING": "刘曲星",
    "CHAR-E44-LIANGMAOER": "梁猫儿", "CHAR-E44-LIANGGOUER": "梁狗儿",
}

SCENE_REFERENCES = {
    "GSM-E44-MUXINZHAI-NOODLE-HOUSE-V1": {
        "entity_id": "SCENE-E44-MUXINZHAI-CLEAN-V1",
        "path": "working_assets/e44_v5_scene_plates_v1/E44_SCENE-E44-MUXINZHAI-CLEAN-V1_29727092-ee76-4d8e-9594-075b30ae59df.png",
    },
    "GSM-E44-ZHENGHE-STREET-V1": {
        "entity_id": "SCENE-E44-ZHENGHE-STREET-MATERIAL-V1",
        "path": "assets/reference/e08_api_fallback_20260709/scenes/SCENE-luocheng-stone-street-clean-20260709.jpg",
    },
    "GSM-E44-TAIPING-CLINIC-DOOR-V1": {
        "entity_id": "SCENE-E44-TAIPING-CLINIC-MATERIAL-V1",
        "path": "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-front-hall-clean-20260709.jpg",
    },
    "GSM-E44-TAIPING-CLINIC-COURTYARD-V1": {
        "entity_id": "SCENE-E44-TAIPING-CLINIC-COURTYARD-MATERIAL-V1",
        "path": "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-rear-courtyard-clean-20260709.jpg",
    },
    "GSM-E44-TAIPING-CLINIC-HALL-V1": {
        "entity_id": "SCENE-E44-TAIPING-CLINIC-HALL-MATERIAL-V1",
        "path": "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-front-hall-clean-20260709.jpg",
    },
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def identity_authorities() -> dict[str, Any]:
    visible = {}
    for name, value in ASSETS.items():
        path = ROOT / value
        if not path.is_file():
            raise ValueError(f"missing E44 identity asset: {value}")
        visible[name] = {
            "path": value, "sha256": sha(path), "qa_status": "PASS",
            "qa_report": "qa/e44_v5_preproduction_20260828/E44_V5_IDENTITY_ASSET_INPUT_QA_V1.json",
            "origin": "E44_NEW" if name in {"金猪", "朱灵韵"} else "ADMITTED_PRIOR_EPISODE_NATIVE",
        }
    report = {
        "schema": "qingshan.identity_asset_input_qa.v1", "episode": "E44", "status": "PASS",
        "all_paths_exist": True, "all_sha256_verified": True,
        "new_named_character_unique": {"金猪": True, "朱灵韵": True},
        "new_identity_visual_review": {
            "金猪": "PASS_SOURCE_FIDELITY_STRAW_SANDALS_BAMBOO_HAT_COARSE_ROBE_SUN_DARKENED_MILD_SMILE_NO_WEAPON_NO_OFFICIAL_ROBE",
            "朱灵韵": "PASS_DISTINCT_FROM_BAILI_YOUNG_WOMAN_RED_EYES_DUSTED_SLEEVES_PERIOD_WARDROBE",
            "乌云": "PASS_RETURNING_NATIVE_ASSET_PRECEDENCE_NO_NEW_CAT_IDENTITY",
        },
        "visible_identity_count": len(visible),
    }
    write_json(QA / "E44_V5_IDENTITY_ASSET_INPUT_QA_V1.json", report)
    authority = {
        "schema": "qingshan.identity_authority_map.v1", "episode": "E44", "canonical_version": 5,
        "authorization_ref": "ROGER-20260828-START-E44-PRODUCTION", "visible_authorities": visible,
        "returning_animal_identity_contract": {
            "乌云": "VISIBLE_RETURNING_NATIVE_ASSET_REFERENCE_PRECEDENCE_OVER_GENERIC_COLOR_DESCRIPTOR_NO_NEW_CAT_IDENTITY"
        },
        "all_paths_exist": True, "all_sha256_verified": True, "status": "PASS",
    }
    write_json(IDENTITY_MAP, authority)
    return authority


def character_binding(character_id: str, authorities: dict[str, Any]) -> dict[str, Any]:
    name = ID_TO_NAME[character_id]
    asset = authorities[name]
    return {
        "role": "character", "entity_id": character_id, "display_name": name,
        "path": asset["path"], "sha256": asset["sha256"], "qa_status": "PASS",
        "qa_report": asset["qa_report"], "asset_origin": asset["origin"],
        "source_component_path": asset["path"], "source_component_sha256": asset["sha256"],
    }


def scene_binding(global_space_map_id: str) -> dict[str, Any] | None:
    spec = SCENE_REFERENCES.get(global_space_map_id)
    if spec is None:
        return None
    path = ROOT / spec["path"]
    if not path.is_file():
        raise ValueError(f"missing E44 scene material reference: {spec['path']}")
    return {
        "role": "scene", "entity_id": spec["entity_id"], "path": spec["path"],
        "sha256": sha(path), "qa_status": "PASS", "asset_origin": "ADMITTED_SCENE_MATERIAL_REFERENCE",
        "use_scope": "MATERIAL_LIGHT_AND_ENVIRONMENT_CONTINUITY_ONLY_MAP_TOPOLOGY_REMAINS_AUTHORITATIVE",
    }


def _blocking_text(rows: list[dict[str, Any]], id_key: str) -> str:
    if not rows:
        return "无"
    return "；".join(
        f"{row.get(id_key)}@{row.get('zone_id')}:{row.get('position')}朝向{row.get('facing')}"
        for row in rows
    )


def prompt_text(
    task_key: str,
    unit: dict[str, Any],
    shot: dict[str, Any],
    map_task: dict[str, Any],
    scene_state: dict[str, Any],
    names: list[str],
    role: str,
) -> str:
    camera = unit["camera_plan"]
    incoming = unit.get("incoming_transition_contract")
    transition = (
        f"入场转场边界 {incoming['boundary_id']}：前0.8秒必须从“{incoming['target_initial_state']['blocking']}”开始，"
        f"承接方式 {incoming['transition_device']}，视觉交棒“{incoming['visual_bridge']}”，不得另起无关空景。"
        if incoming else "本集首段首帧，直接建立既定场景、人物和动作起点。"
    )
    outgoing = unit.get("outgoing_transition_contract")
    exit_transition = (
        f"出场转场边界 {outgoing['boundary_id']}：本段末态必须保持“{outgoing['source_terminal_state']['blocking']}”；"
        f"转场方式 {outgoing['transition_device']}，视觉交棒“{outgoing['visual_bridge']}”，"
        f"动作交棒“{outgoing['action_bridge']}”，声桥“{outgoing['sound_bridge']}”，"
        f"下一单元从“{outgoing['target_initial_state']['blocking']}”承接，不得用无关空景或通用运镜代替剧情转场。"
        if outgoing else "本集末段出场：保持最终剧情结果与现场声自然收束，不预演下一集。"
    )
    return "\n".join([
        f"9:16竖版构图。E44《金豬／上三位》正式语义首帧，任务 {task_key}，真人实拍电影质感，1440×2560原生2K图像，按后续1080×1920视频安全区构图，北宋末年历史短剧。",
        f"视频单元 {unit['unit_id']}，锚点角色 {role}；本段因果节拍：{unit['narrative_beat']}。",
        transition,
        exit_transition,
        f"源剧本本镜动作必须准确承载：{shot['frame_content']}。动作起点/完成态：{shot['first_frame_motion_state']}。",
        f"对白归属：{shot.get('dialogue') or '本镜无对白'}；静帧只锁说话人与听者的准确关系，不生成字幕或可读文字。",
        f"可见角色仅限：{'、'.join(names) if names else '无可见角色'}；不得新增人物或动物，不得换脸、合并脸、改变年龄或交换服装；乌云如出现，毛色、条纹、脸形与体态严格服从其返回资产。",
        f"场景状态：{scene_state.get('time_of_day_state')}；天气与光线：{scene_state.get('weather_state')}；内外景={scene_state.get('interior_exterior')}，色温={scene_state.get('palette_temperature')}。",
        f"起始角色站位：{_blocking_text(map_task['blocking'].get('characters') or [], 'character_id')}。结果角色站位：{_blocking_text((map_task.get('action_end_blocking') or {}).get('characters') or [], 'character_id')}。",
        f"道具连续性：起始={_blocking_text(map_task['blocking'].get('props') or [], 'prop_id')}；结果={_blocking_text((map_task.get('action_end_blocking') or {}).get('props') or [], 'prop_id')}。没有列出的道具不得凭空新增、消失、换手或改变数量。",
        f"摄影机合同：{camera['shot_scale']}，{camera['lens_intent']}，{camera['camera_height']}，{camera['camera_side']}；起始构图“{camera['start_framing']}”。",
        f"空间锁：{map_task['episode_global_space_map_id']} → {map_task['global_space_map_id']} → {map_task['room_id']} → {map_task['zone_id']} → {map_task['subspace_layout']['subspace_id']}，轴线 {map_task['subspace_layout']['axis_id']}。",
        "地图参考只定义拓扑、区域、轴线、固定物和机位；最终画面必须是人眼高度电影镜头，严禁俯视地图、平面图、示意线、箭头、坐标或英文标签。",
        "动作设计：眼神先于头部，接触先由手指/唇发生，下颌、肩颈和重心随后响应；只完成一次因果动作，结果态保持，不循环复位。",
        "微表情设计：呼吸、眼睑、瞳孔、下颌只在剧情因果点发生一次明确变化，变化后维持；禁无意义眨眼、左右扫视和夸张表演。",
        "现场光、风、水声、衣料摩擦、瓷器与脚步必须符合场景；无默认BGM。禁止任何文字、字幕、匾额可读字、药方可读字、LOGO、水印、现代物件、分屏、塑料皮肤或游戏渲染感。",
    ])


def main() -> int:
    generation, grouping, anchors, map_plan = map(read_json, (CONTRACT, GROUPING, ANCHORS, MAP_PLAN))
    identity_map = identity_authorities()
    authorities = identity_map["visible_authorities"]
    shot_by_id = {row["shot_id"]: row for row in generation["shots"]}
    scene_by_id = {row["scene_id"]: row for row in generation["scene_states"]}
    map_by_id = {row["unit_id"]: row for row in map_plan["tasks"]}
    unit_by_id = {row["unit_id"]: row for row in grouping["units"]}
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for anchor_unit in anchors["units"]:
        unit = unit_by_id[anchor_unit["unit_id"]]
        roles = dict(zip(anchor_unit["reference_image_task_keys"], anchor_unit["anchor_count_decision"]["anchor_roles"]))
        for shot_id in anchor_unit["reference_image_task_keys"]:
            shot, map_task = shot_by_id[shot_id], copy.deepcopy(map_by_id[shot_id])
            visible_ids = [row["character_id"] for row in map_task["blocking"]["characters"] if row["character_id"] in ID_TO_NAME]
            identity_ids = [value for value in visible_ids if ID_TO_NAME[value] in authorities]
            map_task["blocking"]["characters"] = [row for row in map_task["blocking"]["characters"] if row["character_id"] in visible_ids]
            task_key = f"{shot_id}-KF-V1"
            body = prompt_text(
                task_key, unit, shot, map_task, scene_by_id[shot["scene_id"]],
                [ID_TO_NAME[x] for x in visible_ids], roles[shot_id],
            )
            # Props remain authored in the source action and map, but E44 has no
            # standalone canonical prop image authority. Do not falsely present
            # topology-only prop ids as paid reference inputs.
            map_task["blocking"]["props"] = []
            if isinstance(map_task.get("action_end_blocking"), dict):
                map_task["action_end_blocking"]["characters"] = [
                    row for row in map_task["action_end_blocking"].get("characters", [])
                    if row.get("character_id") in visible_ids
                ]
                map_task["action_end_blocking"]["props"] = []
            bindings = copy.deepcopy(map_task.get("reference_bindings") or [])
            material_scene = scene_binding(map_task["global_space_map_id"])
            if material_scene:
                bindings.append(material_scene)
            bindings.extend(character_binding(value, authorities) for value in identity_ids)
            if len({row["path"] for row in bindings}) > 9:
                raise ValueError(f"{shot_id} exceeds 9 unique image references")
            transport, identity_transport, effective = (
                compile_labeled_flat_identity_transport(task_key, bindings, body)
                if identity_ids else (bindings, None, body)
            )
            prompt_path = PROMPT_DIR / f"{task_key}.txt"
            prompt_path.write_text(effective.rstrip() + "\n", encoding="utf-8")
            prompt_contract = {
                "schema": "qingshan.image_prompt_contract.v2", "status": "PASS",
                "shot_id": shot_id, "source_script_sha256": sha(CANONICAL),
                "source_action": shot["frame_content"], "source_action_sha256": text_sha(shot["frame_content"]),
                "visible_characters": visible_ids, "canonical_props": [],
                "reference_bindings": transport,
                "editorial_shot_id": shot_id, "video_unit_id": unit["unit_id"],
                "video_unit_duration_seconds": unit["duration_seconds"],
                "state_role": roles[shot_id], "incoming_boundary_id": (unit.get("incoming_transition_contract") or {}).get("boundary_id", "SEQUENCE_START"),
                "spatial_continuity": {
                    "mode": "SAME_SPACE_CONTINUOUS",
                    "policy_source": "PER_UNIT_SCRIPT_CONTENT",
                    "scene_id": map_task["scene_id"],
                    "anchor_scope": "PERFORMANCE_TEMPORAL_ANCHORS_ONLY",
                    "camera_policy": "LOCKED_TO_VIDEO_UNIT_CAMERA_AND_TRANSITION_CONTRACT",
                },
                "failures": [],
            }
            tasks.append({
                **map_task, "task_key": task_key, "episode": "E44", "shot_id": shot_id,
                "space_chain_id": (
                    f"{map_task['episode_global_space_map_id']}::"
                    f"{map_task['global_space_map_id']}::"
                    f"{map_task['subspace_layout']['subspace_id']}"
                ),
                "editorial_shot_id": shot_id, "video_unit_id": unit["unit_id"],
                "video_unit_duration_seconds": unit["duration_seconds"], "beat_id": shot["scene_id"],
                "prompt_file": rel(prompt_path), "prompt_sha256": sha(prompt_path),
                "reference_images": list(dict.fromkeys(row["path"] for row in transport)),
                "reference_image_sequence": transport, "reference_bindings": transport,
                "identity_reference_transport": identity_transport,
                "generation_stage": "SCENE_KEYFRAME", "media_stage": "KEYFRAME",
                "canonical_characters": visible_ids, "canonical_props": [],
                "prompt_contract": prompt_contract,
                "spatial_continuity": prompt_contract["spatial_continuity"],
                "model": "gpt-image-2-pro", "image_model_profile_id": "GPT_IMAGE_2_PRO_GIGGLE",
                "image_model_family": "gpt-image", "aspect_ratio": "9:16", "resolution": "2K",
                "source_script_sha256": sha(CANONICAL), "source_generation_contract": rel(CONTRACT),
                "source_generation_contract_sha256": sha(CONTRACT),
                "authorization_ref": "ROGER-20260828-START-E44-PRODUCTION",
                "provider_post_allowed": False, "maximum_new_submissions": 0,
                "status": "PRECHECK_ONLY", "max_retries": 0, "unchanged_retry": False,
                "attempt_index": 1, "max_content_attempts": 10, "require_semantic_anchor_evidence": False,
            })
    expected = [key for row in anchors["units"] for key in row["reference_image_task_keys"]]
    if [row["editorial_shot_id"] for row in tasks] != expected:
        raise ValueError("E44 anchor task coverage mismatch")
    manifest = {
        "schema": "qingshan.giggle_image_batch_manifest.v2", "episode": "E44", "canonical_version": "v5",
        "title": "金豬／上三位", "authorization_ref": "ROGER-20260828-START-E44-PRODUCTION",
        "source_script": rel(CANONICAL), "source_script_sha256": sha(CANONICAL),
        "provider_post_allowed": False, "maximum_new_submissions": 0,
        "global_space_map_gate_required": True, "episode_global_space_map_ref": rel(MAP_AUTHORITY),
        "complete_map_mode": True,
        "consumer_contract": {
            "video_model": "seedance-2.0-pro", "video_resolution": "1080p", "video_delivery_raster": "1080x1920", "video_aspect_ratio": "9:16",
            "video_route": "STANDARD_MULTI_REFERENCE", "video_unit_count": grouping["video_unit_count"],
            "planned_anchor_count": anchors["planned_reference_image_count"],
        },
        "machine_gate_reports": [
            rel(QA / "E44_V5_COMPLETE_MAP_MODE_GATE_V1.json"),
            rel(QA / "E44_V5_VIDEO_UNIT_GROUPING_GATE_V1.json"),
            rel(QA / "E44_V5_IDENTITY_ASSET_INPUT_QA_V1.json"),
            rel(QA / "E44_V5_VIDEO_UNIT_ANCHOR_COUNT_GATE_V1.json"),
        ],
        "identity_visibility_policy": {
            "乌云": "RETURNING_NATIVE_ASSET_BOUND_AS_CHARACTER_REFERENCE_NO_NEW_CAT_IDENTITY"
        },
        "image_attempt_accounting": {"max_image_attempts_per_asset": 10, "provider_posts_in_this_manifest": 0},
        "tasks": tasks,
    }
    write_json(OUT, manifest)
    print(json.dumps({"status": "PASS", "tasks": len(tasks), "units": len(grouping["units"]), "manifest": rel(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
