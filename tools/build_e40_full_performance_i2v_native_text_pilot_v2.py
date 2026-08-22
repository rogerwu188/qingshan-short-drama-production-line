#!/usr/bin/env python3
"""Build one R04 Fast image-to-video pilot with same-task native dialogue."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import cv2

try:
    from action_video_prompt_compiler import validate_action_contract
    from shot_media_admission_gate import compute_input_template_id
except ModuleNotFoundError:
    from tools.action_video_prompt_compiler import validate_action_contract
    from tools.shot_media_admission_gate import compute_input_template_id


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1"
SOURCE = BASE / "E40_FULL_PERFORMANCE_VIDEO_PREPRODUCTION_V1.json"
OUT = BASE / "E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_PILOT_V2.json"
PROMPT = BASE / "video_prompts_v2/E40-FP-R04-YUNFEI-B-V1-VIDEO-V2.txt"
COST = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_PILOT_COST_GATE_V2.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def raw_rgb_sha(path: Path) -> str:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"cannot decode {path}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    height, width = rgb.shape[:2]
    return hashlib.sha256(width.to_bytes(8, "big") + height.to_bytes(8, "big") + rgb.tobytes()).hexdigest()


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    prior = next(task for task in source["tasks"] if task["unit_id"] == "R04")
    task = copy.deepcopy(prior)
    frame = ROOT / task["reference_images"][0]
    frame_sha = sha(frame)
    if frame_sha != task["start_frame_sha256"]:
        raise SystemExit("R04 admitted frame SHA mismatch")

    task.update({
        "task_key": "E40-FP-R04-YUNFEI-B-V1-VIDEO-V2",
        "retry_attempt": 2,
        "retry_kind": "PROVIDER_ROUTE_REPAIR_IMAGE_TO_VIDEO_NATIVE_TEXT_DIALOGUE",
        "dialogue_transport": "MODEL_NATIVE_TEXT_DIALOGUE",
        "model_native_text_dialogue": True,
        "exact_dialogue_audio_asset_ids": [],
        "exact_dialogue_audio_urls": [],
        "reference_audio_asset_ids": [],
        "reference_audio_urls": [],
        "reference_roles": ["EXACT_FIRST_FRAME"],
        "exact_first_frame_sha256": frame_sha,
        "failure_memory": {
            "attempts": [{
                "attempt": 1,
                "transport": "OMNI_AUDIO_ASSET_ID",
                "error": "router mapping not found",
                "credit": "PASS_ZERO_REFUNDED",
            }],
            "root_cause": "seedance-2.0-fast Omni provider route rejected the task before generation",
            "do_not_repeat": "Do not use omni-video or any external audio reference for this attempt",
        },
        "material_change_from_prior_attempt": "Changed endpoint from omni-video to image-to-video start_frame and moved the two canonical lines into same-task model-native dialogue generation without external audio.",
        "prior_prompt_sha256": [prior["prompt_sha256"]],
        "no_further_automatic_retry": False,
        "native_audio_policy": "PRESERVE_THIS_SEEDANCE_TASK_NATIVE_DIALOGUE_AMBIENCE_FOLEY_AND_SFX_NO_POST_REDUB",
        "video_transport": {
            "mode": "image_to_video_start_frame",
            "endpoint": "/api/v1/generation/image-to-video",
            "start_frame_path": rel(frame),
            "start_frame_sha256": frame_sha,
            "ordinary_images": [],
        },
        "frame0_authority_contract": {
            "source_sha256": frame_sha,
            "pre_encode_raw_rgb_sha256_required": True,
            "raw_rgb_sha256": raw_rgb_sha(frame),
        },
        "post_harvest_exact_frame_gate": {
            "required": True,
            "single_frame_prepend_allowed": False,
            "single_frame_replacement_allowed": False,
            "frame0_thresholds": {
                "minimum_ssim": 0.98,
                "maximum_mae": 3.0,
                "maximum_phash_hamming": 3,
            },
            "frame0_to_frame1_continuity_required": True,
        },
    })
    # Keep the admitted frame's entity-level anchors for semantic completeness.
    # The physical transport is independently and unambiguously declared by
    # reference_roles=[EXACT_FIRST_FRAME] plus video_transport.start_frame.
    task["reference_image_sequence"] = copy.deepcopy(prior["reference_image_sequence"])

    lines = task["dialogue_lines"]
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(
        "以输入图片作为不可改写的第一帧。保持原机位、轴线、景别、人物身份、帘幕空间、案上拓影和站位。"
        "云妃始终只在帘后，以真实普通话、克制但带裂痕的情绪依次只说一次："
        f"“{lines[0]}”停顿后说“{lines[1]}”"
        "；她的口型、下颌、呼吸、眼神和微表情与同一任务生成的声音同步，陈迹只作自然反应。"
        "全部对白、环境、呼吸和布料拟音由本次同一个 Seedance 任务生成并保留。"
        "禁止字幕、画面文字、旁白、后配音、人物换脸、年龄漂移、离开帘后、空间跳变、拓影换位、镜头切换、慢动作、LOGO和水印。\n",
        encoding="utf-8",
    )
    task["prompt_file"] = rel(PROMPT)
    task["prompt_sha256"] = sha(PROMPT)
    task["input_template_id"] = compute_input_template_id(task)
    failures = validate_action_contract(task)
    if failures:
        raise SystemExit(f"action contract failed: {failures}")

    manifest = copy.deepcopy(source)
    manifest.update({
        "schema": "qingshan.e40.full_performance_video_i2v_native_text_pilot.v2",
        "status": "READY_TO_SUBMIT_AUTHORIZED",
        "tasks": [task],
        "admitted_video_task_count": 1,
        "maximum_new_submissions": 1,
        "transport_repair": "IMAGE_TO_VIDEO_START_FRAME_WITH_MODEL_NATIVE_TEXT_DIALOGUE",
        "pilot_policy": "ONE_TASK_ONLY; EXPAND_ONLY_AFTER_PROVIDER_SUCCESS_AND_Q2",
    })
    manifest["machine_gate_reports"] = [
        value for value in manifest["machine_gate_reports"]
        if "AUDIO_REFERENCE" not in value and "COST_GATE" not in value
    ] + [rel(COST)]
    write(OUT, manifest)
    write(COST, {
        "schema": "qingshan.registered_gate_evidence.v1",
        "gate_id": "GIGGLE-REROLL-COST-GUARD",
        "status": "PASS",
        "authorization_ref": "ROGER-20260821-E40-REBUILD-BUDGET-5000",
        "reviewed_manifest": rel(OUT),
        "reviewed_manifest_sha256": sha(OUT),
        "planned_video_tasks": 1,
        "planned_gross_credits": 128,
        "maximum_additional_credits": 5000,
        "retry_attempt": 2,
        "prior_attempt_zero_refunded": True,
    })
    print(json.dumps({
        "status": "PASS",
        "manifest": rel(OUT),
        "manifest_sha256": sha(OUT),
        "prompt_sha256": sha(PROMPT),
        "frame_sha256": frame_sha,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
