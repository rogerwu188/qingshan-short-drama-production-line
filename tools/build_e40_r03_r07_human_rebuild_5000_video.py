#!/usr/bin/env python3
"""Compile exact-first-frame Seedance-fast video tasks for corrected E40 R03/R07."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2

try:
    from action_video_prompt_compiler import (
        CONTRACT_VERSION as ACTION_VIDEO_CONTRACT_VERSION,
        compile_action_video_prompt,
    )
    from shot_media_admission_gate import compute_input_template_id
except ModuleNotFoundError:  # package import in unit tests
    from tools.action_video_prompt_compiler import (
        CONTRACT_VERSION as ACTION_VIDEO_CONTRACT_VERSION,
        compile_action_video_prompt,
    )
    from tools.shot_media_admission_gate import compute_input_template_id


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/human_rebuild_5000_v1"
QA = ROOT / "qa/e40_remake_20260821/human_rebuild_5000_v1"
AUTH = QA / "E40_HUMAN_REBUILD_BUDGET_5000_AUTHORIZATION_V1.json"
Q1 = QA / "q1_registered/E40_R03_R07_HUMAN_REBUILD_5000_Q1_INDEX_V1.json"
AUTH_REF = "ROGER-20260821-E40-REBUILD-BUDGET-5000"
ASSETS = {
    "R03": ROOT / "working_assets/e40_remake_20260821/human_rebuild_5000_v1/keyframes/E40_E40-R03-KEYFRAME-HUMAN-REBUILD-5000-V1_79d15635-4158-430f-8d72-daccf8d22f7f.png",
    "R07": ROOT / "working_assets/e40_remake_20260821/human_rebuild_5000_v1/keyframes/E40_E40-R07-KEYFRAME-HUMAN-REBUILD-5000-V1_77386649-8c5c-43f5-9b35-126e2dc4bfe6.png",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw_rgb_sha(path: Path) -> str:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"Cannot decode {path}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    height, width = rgb.shape[:2]
    return hashlib.sha256(width.to_bytes(8, "big") + height.to_bytes(8, "big") + rgb.tobytes()).hexdigest()


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def task(unit: str, prompt_path: Path, q1_path: Path) -> dict:
    asset = ASSETS[unit]
    asset_rel = str(asset.relative_to(ROOT))
    asset_sha = sha(asset)
    common = {
        "task_key": f"E40-{unit}-VIDEO-HUMAN-REBUILD-5000-V1",
        "unit_id": unit,
        "model": "seedance-2.0-fast",
        "duration_seconds": 4,
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "action_unit": True,
        "native_dialogue_required": False,
        "dialogue_transport": "SILENT_VISUAL_POST_DUB",
        "dialogue_lines": [],
        "source_subtitle_policy": "FORBID",
        "reference_audio_asset_ids": [],
        "exact_dialogue_audio_asset_ids": [],
        "prompt_file": str(prompt_path.relative_to(ROOT)),
        "prompt_sha256": sha(prompt_path),
        "reference_images": [asset_rel],
        "reference_sha256": [asset_sha],
        "reference_roles": ["EXACT_FIRST_FRAME"],
        "exact_first_frame_sha256": asset_sha,
        "video_transport": {
            "mode": "image_to_video_start_frame",
            "endpoint": "/api/v1/generation/image-to-video",
            "start_frame_path": asset_rel,
            "start_frame_sha256": asset_sha,
            "ordinary_images": [],
        },
        "frame0_authority_contract": {
            "source_sha256": asset_sha,
            "pre_encode_raw_rgb_sha256_required": True,
            "raw_rgb_sha256": raw_rgb_sha(asset),
        },
        "post_harvest_exact_frame_gate": {
            "required": True,
            "single_frame_prepend_allowed": False,
            "single_frame_replacement_allowed": False,
            "frame0_thresholds": {"minimum_ssim": 0.98, "maximum_mae": 3.0, "maximum_phash_hamming": 3},
            "frame0_to_frame1_continuity_required": True,
        },
        "episode_global_space_map_id": "EGSM-E40-WANGFU-SEQUENCE-001",
        "global_space_map_id": "GSM-WANGFU-HALL-001",
        "subspace_id": f"SUBSPACE-E40-{unit}",
        "retry_attempt": 1,
        "retry_kind": "ROGER_AUTHORIZED_5000_CREDIT_CORRECTIVE_REBUILD",
        "human_exception_ref": AUTH_REF,
        "maximum_new_submissions": 1,
        "provider_post_allowed": True,
        "no_further_automatic_retry": True,
        "q1_admission_result": str(q1_path.relative_to(ROOT)),
        "start_frame_admission_ref": str(q1_path.relative_to(ROOT)),
        "media_stage": "VIDEO",
        "require_semantic_anchor_evidence": True,
        "action_video_prompt_contract_version": ACTION_VIDEO_CONTRACT_VERSION,
        "performance_tempo_contract": {
            "playback_speed": "REAL_TIME_1X",
            "entry_action_already_in_progress": True,
            "primary_action_complete_by_seconds": 1.8,
            "result_hold_seconds": 0.5,
            "atomic_action_windows": [
                {"start_seconds": 0.0, "end_seconds": 0.9, "action": "完成起始接触和主要动作"},
                {"start_seconds": 0.9, "end_seconds": 1.8, "action": "到达清晰可读的结果状态"},
            ],
        },
        "reference_image_sequence": [],
        "space_chain_id": f"EGSM-E40-WANGFU-SEQUENCE-001->GSM-WANGFU-HALL-001->SUBSPACE-E40-{unit}",
    }
    if unit == "R03":
        common.update({
            "shot_purpose": "动作证据插入镜头：四处霜痕被一次横抹成霜粉",
            "canonical_characters": ["CHAR-陈迹-古装"],
            "visible_characters": ["CHAR-陈迹-古装"],
            "canonical_props": ["PROP-E40-FOUR-FROST-MARKS", "PROP-E40-FROST-POWDER"],
        })
        common["reference_image_sequence"] = [
            {"path": asset_rel, "sha256": asset_sha, "role": "CHARACTER_REFERENCE", "entity_id": "CHAR-陈迹-古装", "transport_role": "EXACT_FIRST_FRAME"},
            {"path": asset_rel, "sha256": asset_sha, "role": "PROP_REFERENCE", "entity_id": "PROP-E40-FOUR-FROST-MARKS", "transport_role": "EXACT_FIRST_FRAME"},
            {"path": asset_rel, "sha256": asset_sha, "role": "PROP_REFERENCE", "entity_id": "PROP-E40-FROST-POWDER", "transport_role": "EXACT_FIRST_FRAME"},
        ]
        common["blocking"] = {
            "characters": [{"character_id": "CHAR-陈迹-古装", "position": "画外，仅两指从左侧入画"}],
            "props": [
                {"prop_id": "PROP-E40-FOUR-FROST-MARKS", "position": "木桌中央，四块扁平霜痕"},
                {"prop_id": "PROP-E40-FROST-POWDER", "position": "尚未形成，附着于四块霜痕"},
            ],
        }
        common["action_end_blocking"] = {
            "characters": [{"character_id": "CHAR-陈迹-古装", "position": "两指位于木桌右侧并轻微抬起"}],
            "props": [
                {"prop_id": "PROP-E40-FOUR-FROST-MARKS", "position": "原四块位置已清空"},
                {"prop_id": "PROP-E40-FROST-POWDER", "position": "沿左至右路径形成一条低矮粉痕"},
            ],
        }
        common["trajectory_overlays"] = [
            {
                "entity_id": "PROP-E40-FOUR-FROST-MARKS", "from": "木桌中央四个分离位置",
                "to": "同一条左至右擦拭路径", "action": "被两指一次连续横抹并松散",
                "visible_consequence": "四块扁平霜痕全部消失且不得出现第五块或立体物件",
            },
            {
                "entity_id": "PROP-E40-FROST-POWDER", "from": "四块霜痕表面",
                "to": "一条连续低矮粉痕", "action": "随手指接触自然沉降",
                "visible_consequence": "只留下细白霜粉，不重新长回霜痕",
            },
        ]
        common["camera_contract"] = "固定70度俯拍微距，不切镜、不拉远"
        common["forbidden_generation"] = [
            "建筑构件", "雕花", "牌匾", "第五块霜痕", "慢动作", "反向擦拭", "字幕", "文字", "LOGO", "水印",
        ]
    else:
        common.update({
            "shot_purpose": "combat interception insert：皎兔用一支反击箭同时截住两支攻击箭",
            "canonical_characters": ["CHAR-皎兔-古装"],
            "visible_characters": ["CHAR-皎兔-古装"],
            "canonical_props": ["PROP-E40-COLD-ARROW-1", "PROP-E40-COLD-ARROW-3", "PROP-E40-COUNTER-ARROW"],
            "combat_choreography_contract": {
                "initiator": "两支深色攻击箭从左上与左下同时袭入",
                "objective": "攻击箭试图穿过中央通道，皎兔以浅色反击箭阻断",
                "spatial_axis": "两支深色箭从左侧两方向汇聚；唯一浅色箭从右向左，三者只在中央交汇",
                "causal_beats": [{
                    "attack_intent": "两支攻击箭沿独立轨迹逼近中央",
                    "defense_response": "浅色反击箭从右侧切入唯一交点",
                    "visible_consequence": "两支攻击箭同时被撞偏，三根箭杆始终可数且不复制",
                    "end_state": "两支攻击箭向上下两侧偏离，反击箭完成穿越，危险解除",
                }],
                "terminal_state": {"winner": "皎兔", "loser": "两支攻击箭", "physical_result": "两支攻击箭被同时截偏，未命中目标"},
            },
        })
        common["reference_image_sequence"] = [
            {"path": asset_rel, "sha256": asset_sha, "role": "CHARACTER_REFERENCE", "entity_id": "CHAR-皎兔-古装", "transport_role": "EXACT_FIRST_FRAME"},
            {"path": asset_rel, "sha256": asset_sha, "role": "PROP_REFERENCE", "entity_id": "PROP-E40-COLD-ARROW-1", "transport_role": "EXACT_FIRST_FRAME"},
            {"path": asset_rel, "sha256": asset_sha, "role": "PROP_REFERENCE", "entity_id": "PROP-E40-COLD-ARROW-3", "transport_role": "EXACT_FIRST_FRAME"},
            {"path": asset_rel, "sha256": asset_sha, "role": "PROP_REFERENCE", "entity_id": "PROP-E40-COUNTER-ARROW", "transport_role": "EXACT_FIRST_FRAME"},
        ]
        common["blocking"] = {
            "characters": [{"character_id": "CHAR-皎兔-古装", "position": "右下角仅手指克制入画"}],
            "props": [
                {"prop_id": "PROP-E40-COLD-ARROW-1", "position": "左上向中央"},
                {"prop_id": "PROP-E40-COLD-ARROW-3", "position": "左下向中央"},
                {"prop_id": "PROP-E40-COUNTER-ARROW", "position": "右侧向中央"},
            ],
        }
        common["action_end_blocking"] = {
            "characters": [{"character_id": "CHAR-皎兔-古装", "position": "右下角手指完成轻微跟随"}],
            "props": [
                {"prop_id": "PROP-E40-COLD-ARROW-1", "position": "向上偏转退出"},
                {"prop_id": "PROP-E40-COLD-ARROW-3", "position": "向下偏转退出"},
                {"prop_id": "PROP-E40-COUNTER-ARROW", "position": "穿过中央交点后向左退出"},
            ],
        }
        common["trajectory_overlays"] = [
            {"entity_id": "PROP-E40-COLD-ARROW-1", "from": "左上", "to": "中央后向上退出", "action": "被反击箭撞偏", "visible_consequence": "攻击箭未命中"},
            {"entity_id": "PROP-E40-COLD-ARROW-3", "from": "左下", "to": "中央后向下退出", "action": "被反击箭撞偏", "visible_consequence": "攻击箭未命中"},
            {"entity_id": "PROP-E40-COUNTER-ARROW", "from": "右侧", "to": "穿过中央交点后向左退出", "action": "一次同时截住两箭", "visible_consequence": "全程严格只有三根完整箭杆"},
        ]
        common["camera_contract"] = "固定首帧空间轴线的极近动作插入镜头，不切镜、不拉远"
        common["forbidden_generation"] = [
            "第四支箭", "额外箭头", "第二支浅色箭", "断裂成长段的箭杆", "慢动作", "魔法光束", "字幕", "文字", "LOGO", "水印",
        ]
    common["input_template_id"] = compute_input_template_id(common)
    return common


def main() -> int:
    bound_transactions = [
        ROOT / "workflow/tasks/giggle_video_submit_transactions/E40/E40-R03-VIDEO-HUMAN-REBUILD-5000-V1__35e0ffae95cc1bf4.json",
        ROOT / "workflow/tasks/giggle_video_submit_transactions/E40/E40-R07-VIDEO-HUMAN-REBUILD-5000-V1__5d7645870edbf1c8.json",
    ]
    if any(path.is_file() for path in bound_transactions):
        raise SystemExit(
            "R03/R07 task IDs are already durably bound; this historical builder is immutable. "
            "Compile future corrected units under new task keys."
        )
    q1 = json.loads(Q1.read_text(encoding="utf-8"))
    if q1.get("status") != "PASS" or q1.get("admitted_count") != 2:
        raise SystemExit("Corrected R03/R07 Q1 is not fully admitted")
    prompts = {
        "R03": """以输入图片作为不可改写的第一帧。9:16真人古装电影微距插入镜头，固定70度俯拍，不切镜，不拉远，不出现人物脸或身体。0.0—0.9秒：图中两根手指立即贴住最左侧扁平霜痕，以真实1倍速度连续向右横抹，一次不间断经过四块霜痕。四块霜痕是贴在木纹表面的薄霜残留，不是实体物件；接触后只沿手指路径松散成细白霜粉。0.9—1.8秒：手指完成右移并轻微抬起，四块原霜痕全部消失，只留下同一条连续、低矮、自然不均匀的霜粉痕。1.8—4.0秒：结果短暂停留，只有手部呼吸式微动和少量霜粉自然沉降。严格保持木桌、灰袖、手指数量和光线连续。禁止生成建筑构件、雕花、牌匾、第五块霜痕、整个人、慢动作、反向擦拭、重新长出霜痕、漂浮大颗粒、字幕、文字、LOGO或水印。""",
        "R07": """以输入图片作为不可改写的第一帧。9:16真人古装电影极近动作插入镜头，固定空间轴线，不切镜，不拉远。全程严格只有三根完整箭杆：左上深色攻击箭A、左下深色攻击箭B、右侧浅色反击箭C；任何时刻都不得新增、复制、分裂或补出第四根箭。0.0—0.8秒：第一帧中央碰撞立即继续，唯一浅色反击箭C从右向左穿过共同交点，同时把A向上方偏转、把B向下方偏转；三根箭的因果和方向清晰可读。0.8—1.6秒：A和B分别沿上下方向退出画面，C保持单一路径向左完成穿越，右下角皎兔手指只做克制的跟随微动。1.6—4.0秒：危险解除，残余木屑在交点附近短暂落下，镜头保持。箭杆不能断裂成类似额外箭杆的长段；禁止第四支箭、额外箭头、第二支浅色箭、弓、箭袋、人物脸或身体、慢动作、魔法光束、字幕、文字、LOGO或水印。""",
    }
    prompt_dir = BASE / "video_prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for unit in ("R03", "R07"):
        path = prompt_dir / f"E40-{unit}-VIDEO-HUMAN-REBUILD-5000-V1.txt"
        path.write_text(prompts[unit], encoding="utf-8")
        q1_path = QA / f"q1_registered/E40-{unit}-KEYFRAME-HUMAN-REBUILD-5000-V1/admission_result.json"
        compiled = task(unit, path, q1_path)
        compiled_prompt = compile_action_video_prompt(compiled)
        path.write_text(compiled_prompt, encoding="utf-8")
        compiled["prompt_sha256"] = sha(path)
        tasks.append(compiled)

    cost_path = QA / "E40_R03_R07_HUMAN_REBUILD_5000_VIDEO_COST_GATE_V1.json"
    manifest = {
        "schema": "qingshan.e40.r03_r07_human_rebuild_5000_video_manifest.v1",
        "episode": "E40",
        "provider": "giggle",
        "allowed_video_models": ["seedance-2.0-fast"],
        "status": "READY_TO_SUBMIT_HUMAN_AUTHORIZED",
        "authorization_ref": AUTH_REF,
        "authorization_receipt": str(AUTH.relative_to(ROOT)),
        "authorization_receipt_sha256": sha(AUTH),
        "provider_post_allowed": True,
        "maximum_new_submissions": 2,
        "machine_gate_reports": [
            str(Q1.relative_to(ROOT)),
            "qa/e40_remake_20260818/global_space_maps_v1/E40_GLOBAL_SPACE_LAYOUT_GATE_V1.json",
            str(cost_path.relative_to(ROOT)),
        ],
        "retry_policy": {
            "maximum_additional_automatic_retries": 0,
            "unknown_or_timeout_requires_authoritative_cost_classification": True,
            "human_budget_authorization_ref": AUTH_REF,
        },
        "tasks": tasks,
    }
    manifest_path = BASE / "E40_R03_R07_HUMAN_REBUILD_5000_VIDEO_MANIFEST_V1.json"
    write(manifest_path, manifest)
    write(cost_path, {
        "schema": "qingshan.registered_gate_evidence.v1",
        "gate_id": "GIGGLE-REROLL-COST-GUARD",
        "status": "PASS",
        "authorization_ref": AUTH_REF,
        "reviewed_manifest": str(manifest_path.relative_to(ROOT)),
        "reviewed_manifest_sha256": sha(manifest_path),
        "maximum_additional_credits": 5000,
        "planned_video_tasks": 2,
    })
    print(json.dumps({
        "manifest": str(manifest_path.relative_to(ROOT)), "manifest_sha256": sha(manifest_path),
        "cost_gate": str(cost_path.relative_to(ROOT)), "cost_gate_sha256": sha(cost_path),
        "tasks": [row["task_key"] for row in tasks],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
