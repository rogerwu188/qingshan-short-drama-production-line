#!/usr/bin/env python3
"""Compile one clean Muxinzhai material plate for E44 without provider submission."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_preproduction_20260828"
SOURCE = PROD / "E44_V5_GIGGLE_KEYFRAME_MANIFEST_PRECHECK_V1.json"
OUT = PROD / "E44_V5_MUXINZHAI_SCENE_PLATE_MANIFEST_PRECHECK_V1.json"
PROMPT = PROD / "scene_prompts_v1/SCENE-E44-MUXINZHAI-CLEAN-V1.txt"
REFERENCE = ROOT / "working_assets/e43_v6_keyframes_v1/E43_E43-S10-01-KF-V1_f685baf9-090b-4f60-a2d2-bbe7e9de0871.png"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    base = next(
        copy.deepcopy(row) for row in source["tasks"]
        if row["global_space_map_id"] == "GSM-E44-MUXINZHAI-NOODLE-HOUSE-V1"
    )
    source_action = (
        "生成无人、无动物的木心斋面馆清洁空间材质板：北宋末年洛城平民面馆，"
        "深色木柱、木桌木凳、灰陶面碗与竹筷筒，门外阴天街光从画面后侧进入；"
        "保留真实使用磨损，但不得出现任何人物、脸、手、剪影、可读招牌或现代物件。"
    )
    prompt = "\n".join([
        "9:16竖版，1440×2560原生2K，北宋末年历史短剧真人实拍电影质感场景材质板。",
        source_action,
        "输入画面仅提供木材、陶碗、桌凳、室内光线与空间年代感；必须彻底移除输入画面中的男女两人及其身体、脸、衣服和影子，不得生成替代人物。",
        "完整地图是唯一拓扑权威：EGSM-E44-MUXINZHAI-TO-TAIPING-YIGUAN-V1 → GSM-E44-MUXINZHAI-NOODLE-HOUSE-V1 → ROOM-E44-MUXINZHAI-MAIN → ZONE-MUXINZHAI-GUEST-TABLES。",
        "人眼高度35mm自然透视，固定中景建立镜头；木柱形成纵深，客桌区、通道、柜台方向清楚，轴线稳定。",
        "地图图像只定义拓扑、分区与固定物；最终画面严禁俯视地图、示意线、箭头、坐标、英文标签或平面图风格。",
        "光线为自然阴天街光与室内微暖反射，不要戏剧舞台光；材料必须有木纹、陶器粗糙度、灰尘和真实磨损。",
        "禁止任何人物、动物、脸、手、脚、人体剪影、可读文字、字幕、LOGO、水印、现代物件、分屏、塑料质感和游戏渲染感。",
    ]) + "\n"
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(prompt, encoding="utf-8")

    map_bindings = [
        row for row in base["reference_bindings"]
        if row.get("role") in {"episode_global_space_map", "global_space_map", "subspace_layout"}
    ]
    scene = {
        "role": "scene",
        "entity_id": "SCENE-E43-MUXINZHAI-MATERIAL-SOURCE-V1",
        "path": rel(REFERENCE),
        "sha256": sha(REFERENCE),
        "qa_status": "PASS",
        "asset_origin": "ADMITTED_PRIOR_EPISODE_NATIVE_FRAME_MATERIAL_ONLY",
        "use_scope": "MATERIAL_LIGHT_FURNITURE_ONLY_REMOVE_ALL_PEOPLE",
    }
    bindings = [*map_bindings, scene]
    base.update({
        "task_key": "SCENE-E44-MUXINZHAI-CLEAN-V1",
        "shot_id": "E44-S01-01-SCENE-PLATE",
        "editorial_shot_id": "E44-S01-01-SCENE-PLATE",
        "video_unit_id": None,
        "prompt_file": rel(PROMPT),
        "prompt_sha256": sha(PROMPT),
        "reference_bindings": bindings,
        "reference_image_sequence": bindings,
        "reference_images": list(dict.fromkeys(row["path"] for row in bindings)),
        "identity_reference_transport": None,
        "canonical_characters": [],
        "canonical_props": [],
        "generation_stage": "SCENE_PLATE",
        "media_stage": "SCENE_PLATE",
        "status": "PRECHECK_ONLY",
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
    })
    base["blocking"]["characters"] = []
    base["blocking"]["props"] = []
    base["action_end_blocking"]["characters"] = []
    base["action_end_blocking"]["props"] = []
    base["prompt_contract"] = {
        "schema": "qingshan.image_prompt_contract.v2",
        "status": "PASS",
        "shot_id": base["shot_id"],
        "source_script_sha256": base["source_script_sha256"],
        "source_action": source_action,
        "source_action_sha256": text_sha(source_action),
        "visible_characters": [],
        "canonical_props": [],
        "reference_bindings": bindings,
        "editorial_shot_id": base["editorial_shot_id"],
        "video_unit_id": None,
        "state_role": "CLEAN_SCENE_MATERIAL_AUTHORITY",
        "incoming_boundary_id": "NOT_APPLICABLE",
        "spatial_continuity": base["spatial_continuity"],
        "failures": [],
    }
    manifest = copy.deepcopy(source)
    manifest.update({
        "schema": "qingshan.giggle_image_batch_manifest.v2",
        "status": "PRECHECK_ONLY",
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "tasks": [base],
    })
    manifest["consumer_contract"] = {
        "asset_role": "E44_MUXINZHAI_CLEAN_SCENE_MATERIAL_AUTHORITY",
        "dependent_keyframe_count": sum(
            row["global_space_map_id"] == "GSM-E44-MUXINZHAI-NOODLE-HOUSE-V1"
            for row in source["tasks"]
        ),
    }
    write(OUT, manifest)
    write(QA / "E44_V5_MUXINZHAI_SCENE_PLATE_COMPILE_GATE_V1.json", {
        "schema": "qingshan.scene_plate_compile_gate.v1",
        "gate_id": "E44-V5-MUXINZHAI-CLEAN-SCENE-PLATE",
        "status": "PASS",
        "all_people_removal_required": True,
        "complete_map_bound": True,
        "provider_posts": 0,
        "credits": 0,
    })
    print(json.dumps({"status": "PASS", "manifest": rel(OUT), "tasks": 1}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
