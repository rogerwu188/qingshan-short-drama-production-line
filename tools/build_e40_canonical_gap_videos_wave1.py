#!/usr/bin/env python3
"""Compile exact-first-frame Seedance-fast videos for admitted E40 gap shots."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2

try:
    from action_video_prompt_compiler import (
        CONTRACT_VERSION as ACTION_VIDEO_CONTRACT_VERSION,
        compile_action_video_prompt,
        validate_action_contract,
    )
    from shot_media_admission_gate import compute_input_template_id
except ModuleNotFoundError:
    from tools.action_video_prompt_compiler import (
        CONTRACT_VERSION as ACTION_VIDEO_CONTRACT_VERSION,
        compile_action_video_prompt,
        validate_action_contract,
    )
    from tools.shot_media_admission_gate import compute_input_template_id


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/canonical_gap_videos_wave1_v1"
QA = ROOT / "qa/e40_remake_20260822/canonical_gap_videos_wave1_v1"
Q1_INDEX = ROOT / "qa/e40_remake_20260822/canonical_gap_keyframes_wave1_v1/q1_registered/E40_CANONICAL_GAP_KEYFRAMES_WAVE1_Q1_INDEX_V1.json"
AUTH = ROOT / "qa/e40_remake_20260821/human_rebuild_5000_v1/E40_HUMAN_REBUILD_BUDGET_5000_AUTHORIZATION_V1.json"
AUTH_REF = "ROGER-20260821-E40-REBUILD-BUDGET-5000"


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


def make_task(spec: dict, admitted: dict) -> dict:
    asset = ROOT / admitted["asset_path"]
    admission = ROOT / admitted["admission_result"]
    asset_sha = sha(asset)
    if asset_sha != admitted["asset_sha256"]:
        raise SystemExit(f"Q1-bound asset SHA drift: {spec['unit_id']}")
    prompt_path = BASE / "prompts" / f"{spec['task_key']}.txt"
    asset_rel = str(asset.relative_to(ROOT))
    task = {
        "episode": "E40",
        "task_key": spec["task_key"],
        "unit_id": spec["unit_id"],
        "canonical_unit_id": spec["scene_id"],
        "canonical_script_excerpt": spec["canonical_action"],
        "shot_type": "GENERAL",
        "shot_purpose": spec["shot_purpose"],
        "model": "seedance-2.0-fast",
        "duration_seconds": spec["duration_seconds"],
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "action_unit": True,
        "native_dialogue_required": False,
        "dialogue_transport": "PROVIDER_NATIVE_NON_DIALOGUE_SOUND",
        "dialogue_lines": [],
        "source_subtitle_policy": "FORBID",
        "reference_audio_asset_ids": [],
        "exact_dialogue_audio_asset_ids": [],
        "prompt_file": str(prompt_path.relative_to(ROOT)),
        "prompt_sha256": "PENDING",
        "reference_images": [asset_rel],
        "reference_sha256": [asset_sha],
        "reference_roles": ["EXACT_FIRST_FRAME"],
        "reference_image_sequence": [
            {
                "path": asset_rel,
                "sha256": asset_sha,
                "role": "CHARACTER_REFERENCE",
                "entity_id": entity,
                "transport_role": "EXACT_FIRST_FRAME",
            }
            for entity in spec["canonical_characters"]
        ],
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
        "subspace_id": spec["subspace_id"],
        "space_chain_id": f"EGSM-E40-WANGFU-SEQUENCE-001->GSM-WANGFU-HALL-001->{spec['subspace_id']}",
        "canonical_characters": spec["canonical_characters"],
        "visible_characters": spec["canonical_characters"],
        "canonical_props": [],
        "blocking": spec["blocking"],
        "action_end_blocking": spec["action_end_blocking"],
        "trajectory_overlays": spec["trajectory_overlays"],
        "camera_contract": spec["camera_contract"],
        "performance_tempo_contract": {
            **spec["performance_tempo_contract"],
            "primary_action_complete_by_seconds": 1.8,
            "result_hold_seconds": 0.5,
        },
        "forbidden_generation": spec["forbidden_generation"],
        "retry_attempt": 1,
        "retry_kind": "FIRST_VIDEO_ATTEMPT_FROM_Q1_ADMITTED_CANONICAL_GAP_KEYFRAME",
        "human_exception_ref": AUTH_REF,
        "maximum_new_submissions": 1,
        "provider_post_allowed": True,
        "q1_admission_result": str(admission.relative_to(ROOT)),
        "start_frame_admission_ref": str(admission.relative_to(ROOT)),
        "media_stage": "VIDEO",
        "require_semantic_anchor_evidence": True,
        "action_video_prompt_contract_version": ACTION_VIDEO_CONTRACT_VERSION,
        "same_task_native_audio_contract": {
            "required": True,
            "preserve_dialogue_environment_foley_action_audio": True,
            "external_tts_for_visible_lips_forbidden": True,
            "bgm_policy": "NONE_NO_NAMED_CUE",
        },
    }
    prompt = compile_action_video_prompt(task) + spec["native_audio_prompt"]
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    task["prompt_sha256"] = sha(prompt_path)
    task["input_template_id"] = compute_input_template_id(task)
    failures = validate_action_contract(task)
    if failures:
        raise SystemExit(f"{spec['task_key']} action contract invalid: {failures}")
    return task


def main() -> int:
    q1 = json.loads(Q1_INDEX.read_text(encoding="utf-8"))
    admitted = {
        row["task_key"].replace("-KEYFRAME-V1", ""): row
        for row in q1["results"]
        if row["downstream_status"] == "ADMITTED_FOR_VIDEO_SUBMIT"
    }
    specs = [
        {
            "task_key": "E40-13-1-S01-VIDEO-V1",
            "unit_id": "E40-13-1-S01",
            "scene_id": "13-1",
            "duration_seconds": 4,
            "canonical_action": "满堂灯烛，素纱长帘被穿堂风推起半寸又落下；帘后人影执扇缓摇，白鲤垂眼静立，陈迹踏进厅门且步子未停。",
            "shot_purpose": "冷开场恢弘定场：陈迹进厅、帘动、帘后扇影和白鲤静立同时建立空间关系",
            "subspace_id": "SUBSPACE-E40-13-1-S01-HALL-THRESHOLD",
            "canonical_characters": ["CHAR-陈迹-古装", "CHAR-白鲤-古装"],
            "blocking": {"characters": [{"character_id": "CHAR-陈迹-古装", "position": "厅门门槛内侧，迈步进行中"}, {"character_id": "CHAR-白鲤-古装", "position": "素纱帘侧静立垂眼"}], "props": []},
            "action_end_blocking": {"characters": [{"character_id": "CHAR-陈迹-古装", "position": "向厅内自然前进一步，仍未停步"}, {"character_id": "CHAR-白鲤-古装", "position": "原位静立，仅自然呼吸与一次轻微眨眼"}], "props": []},
            "trajectory_overlays": [
                {"entity_id": "CHAR-陈迹-古装", "from": "厅门门槛内侧", "to": "厅内前方一步", "action": "真实1倍速度继续迈步进入", "visible_consequence": "人物与厅门、长帘的前后空间关系不跳变"},
                {"entity_id": "CHAR-白鲤-古装", "from": "帘侧原位", "to": "帘侧原位", "action": "克制呼吸并保持垂眼", "visible_consequence": "不抢陈迹入厅主动作，不移动站位"},
            ],
            "camera_contract": "先保持首帧大远景空间轴线，极缓推至中景，不切镜、不越轴",
            "performance_tempo_contract": {"playback_speed": "REAL_TIME_1X", "atomic_action_windows": [{"start_seconds": 0.0, "end_seconds": 0.6, "action": "陈迹立即延续首帧步态迈入厅门"}, {"start_seconds": 0.6, "end_seconds": 1.2, "action": "长帘被风推起半寸后落下，帘后扇影缓摇"}, {"start_seconds": 1.2, "end_seconds": 1.8, "action": "陈迹继续前进一步，白鲤保持静立"}]},
            "forbidden_generation": ["人物身份漂移", "新增人物", "长帘大幅飘飞", "快动作", "慢动作", "越轴", "字幕", "文字", "LOGO", "水印"],
            "native_audio_prompt": "同一生成任务原生生成并保留灯烛毕剥、轻微帘幕浮动和远处更漏环境声；本镜无对白、无可见口型、无BGM，不得后配TTS或替换原生声场。",
        },
        {
            "task_key": "E40-13-2-S02-VIDEO-V1",
            "unit_id": "E40-13-2-S02",
            "scene_id": "13-2",
            "duration_seconds": 4,
            "canonical_action": "陈迹指尖停在案角空处，没有第五个印；帘侧白鲤垂着的睫毛极轻地动了一下。",
            "shot_purpose": "反常证据近景：四个霜印之外明确没有第五印，白鲤以极轻睫毛微动回应",
            "subspace_id": "SUBSPACE-E40-13-2-S02-TABLE-CURTAIN-SIGHTLINE",
            "canonical_characters": ["CHAR-陈迹-古装", "CHAR-白鲤-古装"],
            "blocking": {"characters": [{"character_id": "CHAR-陈迹-古装", "position": "案前，指尖正悬在四印之外的案角空处"}, {"character_id": "CHAR-白鲤-古装", "position": "帘侧背景垂眼静立"}], "props": []},
            "action_end_blocking": {"characters": [{"character_id": "CHAR-陈迹-古装", "position": "指尖仍停在同一空处，确认没有第五印"}, {"character_id": "CHAR-白鲤-古装", "position": "帘侧原位，完成一次极轻睫毛微动后恢复垂眼"}], "props": []},
            "trajectory_overlays": [
                {"entity_id": "CHAR-陈迹-古装", "from": "案角空处上方", "to": "同一空处上方", "action": "指尖立即停住并保持", "visible_consequence": "画面始终清楚可数只有四个霜印，空处不生成第五印"},
                {"entity_id": "CHAR-白鲤-古装", "from": "帘侧垂眼", "to": "帘侧垂眼", "action": "只做一次几乎不可察觉的睫毛微动", "visible_consequence": "不抬头、不转身、不改变站位"},
            ],
            "camera_contract": "保持首帧近景构图和案面至帘侧视线关系，固定机位，不切镜、不拉远",
            "performance_tempo_contract": {"playback_speed": "REAL_TIME_1X", "atomic_action_windows": [{"start_seconds": 0.0, "end_seconds": 0.6, "action": "陈迹指尖立即停在案角空处"}, {"start_seconds": 0.6, "end_seconds": 1.2, "action": "白鲤睫毛极轻微动一次"}, {"start_seconds": 1.2, "end_seconds": 1.8, "action": "两人保持克制静止，四印和空处持续可读"}]},
            "forbidden_generation": ["第五个霜印", "霜印数量变化", "人物身份漂移", "白鲤抬头", "夸张表情", "镜头切换", "字幕", "文字", "LOGO", "水印"],
            "native_audio_prompt": "同一生成任务原生生成并保留厅内低微环境声、衣料极轻摩擦与呼吸；本镜无对白、无可见口型、无BGM，不得后配TTS或替换原生声场。",
        },
    ]
    tasks = [make_task(spec, admitted[spec["unit_id"]]) for spec in specs]
    cost_path = QA / "E40_CANONICAL_GAP_VIDEOS_WAVE1_COST_GATE_V1.json"
    video_ready_path = QA / "E40_CANONICAL_GAP_KEYFRAMES_WAVE1_VIDEO_READY_GATE_V1.json"
    write(video_ready_path, {
        "schema": "qingshan.registered_gate_evidence.v1",
        "gate_id": "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
        "status": "PASS",
        "scope": "ONLY_THE_TWO_EXACT_SHA_Q1_ADMITTED_KEYFRAMES",
        "admission_results": [
            {"path": task["q1_admission_result"], "sha256": sha(ROOT / task["q1_admission_result"])}
            for task in tasks
        ],
        "excluded_failed_keyframe": "E40-13-1-S04-KEYFRAME-V1",
    })
    manifest_path = BASE / "E40_CANONICAL_GAP_VIDEOS_WAVE1_V1.json"
    manifest = {
        "schema": "qingshan.e40.canonical_gap_videos_wave1.v1",
        "episode": "E40",
        "provider": "giggle",
        "allowed_video_models": ["seedance-2.0-fast"],
        "status": "READY_TO_SUBMIT",
        "authorization_ref": AUTH_REF,
        "authorization_receipt": str(AUTH.relative_to(ROOT)),
        "authorization_receipt_sha256": sha(AUTH),
        "provider_post_allowed": True,
        "maximum_new_submissions": 2,
        "machine_gate_reports": [
            str(video_ready_path.relative_to(ROOT)),
            str(cost_path.relative_to(ROOT)),
        ],
        "retry_policy": {"maximum_additional_automatic_retries": 0, "unknown_or_timeout_requires_authoritative_cost_classification": True},
        "tasks": tasks,
    }
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
        "note": "Two first-attempt videos from exact-SHA Q1-admitted keyframes; failed S04 is isolated.",
    })
    print(json.dumps({"manifest": str(manifest_path.relative_to(ROOT)), "manifest_sha256": sha(manifest_path), "tasks": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
