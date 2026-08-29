#!/usr/bin/env python3
"""Precompile remaining Q1-admitted E40 I2V tasks without authorizing POST."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

try:
    from action_video_prompt_compiler import validate_action_contract
    from shot_media_admission_gate import compute_input_template_id
except ModuleNotFoundError:
    from tools.action_video_prompt_compiler import validate_action_contract
    from tools.shot_media_admission_gate import compute_input_template_id


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1"
SOURCE = BASE / "E40_FULL_PERFORMANCE_VIDEO_PREPRODUCTION_V1.json"
OUT = BASE / "E40_FULL_PERFORMANCE_VIDEO_I2V_WAITING_WAVE_V1.json"
PROMPT_DIR = BASE / "video_prompts_i2v_waiting_v1"
UNITS = ("R01", "R05", "R07", "R08")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prompt_for(task: dict) -> str:
    speaker = "、".join(task.get("visible_characters") or [])
    lines = "；停顿后说".join(f"“{line}”" for line in task["dialogue_lines"])
    return (
        "以输入图片作为不可改写的第一帧，保持其人物身份、年龄、服装、机位、轴线、景别、"
        "整集空间图到子空间的继承关系、人物与物品站位。"
        f"画面人物绑定为{speaker}。可见说话者用真实普通话依次只说一次：{lines}。"
        "声音、口型、下颌、呼吸、眼神、微表情、环境声和动作拟音必须由本次同一个 Seedance 任务生成并保留；"
        "表演克制、真实，不看镜头，不做静态念稿。"
        "禁止字幕、画面文字、旁白、后配音、换脸、年龄漂移、空间跳变、道具换位、慢动作、LOGO和水印。\n"
    )


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    tasks = []
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    for prior in source["tasks"]:
        if prior["unit_id"] not in UNITS:
            continue
        task = copy.deepcopy(prior)
        frame = ROOT / task["reference_images"][0]
        frame_sha = sha(frame)
        if frame_sha != task["start_frame_sha256"]:
            raise SystemExit(f"{task['unit_id']} admitted frame SHA mismatch")
        task.update({
            "task_key": task["task_key"].removesuffix("-VIDEO-V1") + "-VIDEO-V2-I2V-WAITING",
            "status": "WAITING_DEPENDENCY_PROVIDER_ROUTE_PROOF",
            "provider_post_allowed": False,
            "maximum_new_submissions": 0,
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
                "do_not_repeat": "Do not use omni-video or external audio references.",
            },
            "material_change_from_prior_attempt": "Precompiled image-to-video exact start frame with same-task native text dialogue and no external audio reference.",
            "prior_prompt_sha256": [prior["prompt_sha256"]],
            "native_audio_policy": "PRESERVE_THIS_SEEDANCE_TASK_NATIVE_DIALOGUE_AMBIENCE_FOLEY_AND_SFX_NO_POST_REDUB",
            "video_transport": {
                "mode": "image_to_video_start_frame",
                "endpoint": "/api/v1/generation/image-to-video",
                "start_frame_path": rel(frame),
                "start_frame_sha256": frame_sha,
                "ordinary_images": [],
            },
        })
        prompt = PROMPT_DIR / f"{task['task_key']}.txt"
        prompt.write_text(prompt_for(task), encoding="utf-8")
        task["prompt_file"] = rel(prompt)
        task["prompt_sha256"] = sha(prompt)
        task["input_template_id"] = compute_input_template_id(task)
        failures = validate_action_contract(task)
        if failures:
            raise SystemExit(f"{task['unit_id']} action contract failed: {failures}")
        tasks.append(task)

    manifest = {
        "schema": "qingshan.e40.full_performance_video_i2v_waiting_wave.v1",
        "episode": "E40",
        "status": "WAITING_DEPENDENCY_PROVIDER_ROUTE_PROOF",
        "dependency": "E40 recovery2 I2V tasks must complete and pass registered Q2 before paid expansion.",
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "model": "seedance-2.0-fast",
        "tasks": tasks,
    }
    write(OUT, manifest)
    print(json.dumps({
        "status": "PASS",
        "manifest": rel(OUT),
        "manifest_sha256": sha(OUT),
        "tasks": len(tasks),
        "provider_post_allowed": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
