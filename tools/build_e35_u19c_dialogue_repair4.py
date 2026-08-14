#!/usr/bin/env python3
"""Reduce E35 U19C to two images and one voice reference after refunded failure."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e35_claude_writer_v1_416d09e2_20260723"
VIDEO_DIR = PROD / "video_performance_v1"
PROMPT_DIR = PROD / "video_prompts_performance_v1"
BASE_CONFIG = VIDEO_DIR / "E35_VIDEO_DIALOGUE_FAILED_ONLY_REPAIR3.json"
BASE_PROMPTS = PROD / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1_DIALOGUE_REPAIR3.json"
BASE_DIALOGUE = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1_DIALOGUE_REPAIR3.json"
OUT_CONFIG = VIDEO_DIR / "E35_VIDEO_U19C_DIALOGUE_REPAIR4.json"
OUT_PROMPTS = PROD / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1_U19C_REPAIR4.json"
OUT_DIALOGUE = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1_U19C_REPAIR4.json"
OUT_PROMPT = PROMPT_DIR / "E35-CW-U19C-DIALOGUE-REPAIR4.txt"
EVIDENCE = ROOT / "qa/e35_v1_release_20260723/E35_U19C_REMOTE_FAILURE_REPAIR4.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    config = load(BASE_CONFIG)
    task = copy.deepcopy(next(row for row in config["tasks"] if row["unit_id"] == "E35-CW-U19C"))
    state = copy.deepcopy(next(row for row in task["reference_image_sequence"] if not row.get("identity_reference")))
    chenji_image = copy.deepcopy(next(row for row in task["reference_image_sequence"] if row.get("entity_id") == "chenji"))
    state["asset_label"] = "@图片1"
    chenji_image["asset_label"] = "@图片2"
    task["reference_image_sequence"] = [state, chenji_image]
    task["reference_images"] = [state["path"], chenji_image["path"]]
    task.pop("resolved_reference_image_asset_ids", None)
    binding = copy.deepcopy(next(row for row in task["multimodal_entity_bindings"] if row["entity_id"] == "chenji"))
    binding["identity_image_slot"] = "@图片2"
    binding["dialogue_audio_slots"] = ["@音频1", "@音频1", "@音频1"]
    binding["visible_speaker"] = True
    binding["lip_sync"] = True
    task["multimodal_entity_bindings"] = [binding]
    task["visual_entity_ids"] = ["chenji"]
    task["nonvisual_entity_mentions"] = ["jiaotu_off_camera", "yunyang_off_camera", "yanjing"]
    task["task_key"] = "E35-CW-U19C-PERFORMANCE-V1-DIALOGUE-REPAIR4"
    task["batch_id"] = "E35-V1-U19C-DIALOGUE-REPAIR4-20260724"
    task["visual_zone"] = "E35-CW-U19C-V1-TWO-IMAGE-DIALOGUE-REPAIR4"
    task["performance_spec"]["motion_beats"][0]["subject"] = "陈迹"
    task["performance_spec"]["motion_beats"][0]["action"] = (
        "陈迹独自在中近景说明直接抓捕会触发景朝灭口，合起账底并握住旧钱，"
        "逐字落定唯一活线必须先保护、再审问；皎兔和云羊位于镜头外。"
    )
    task["performance_spec"]["motion_beats"][0]["expression"] = "陈迹克制决断，由警惕转为行动确认。"
    task["prompt_contract"]["source_action"] = task["performance_spec"]["motion_beats"][0]["action"]
    task["multimodal_binding_sha256"] = hashlib.sha256(
        json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    original_prompt = (ROOT / task["prompt_file"]).read_text(encoding="utf-8")
    prompt = re.sub(
        r"实体绑定：[^\n]+",
        "实体绑定：[[char_chenji]] [[scene_e35_s04]]。画面只出现陈迹；皎兔和云羊位于镜头外，不出现身体、脸、倒影或复制人。",
        original_prompt,
    )
    prompt = re.sub(r"表情表演：[^\n]+", "表情表演：陈迹克制决断，由警惕转为行动确认。", prompt)
    prompt = prompt.replace("本单元是原视频漏句后的定向修复", "本单元是原视频远端失败后的降载定向修复")
    prompt = prompt.replace("中景连续拍摄", "大远景建立方位后连续推近至中景")
    prompt = prompt.replace("说话人与同场角色", "陈迹")
    prompt = prompt.replace("同场角色", "陈迹")
    prompt = prompt.replace("听者反应", "镜头外审讯同伴的压力方向")
    prompt = prompt.replace("说话人始终可见口型，非说话人物闭口", "陈迹始终可见口型；镜头外人物不发声")
    OUT_PROMPT.write_text(prompt, encoding="utf-8")
    task["prompt_file"] = rel(OUT_PROMPT)
    task["prompt_path"] = rel(OUT_PROMPT)
    task["prompt_sha256"] = sha(OUT_PROMPT)
    task["repair_evidence"] = rel(EVIDENCE)
    task.pop("generation_fingerprint", None)
    task["generation_fingerprint"] = generation_fingerprint(task)

    prompt_manifest = load(BASE_PROMPTS)
    row = copy.deepcopy(next(item for item in prompt_manifest["rows"] if item["unit_id"] == "E35-CW-U19C"))
    row.update({"prompt_path": rel(OUT_PROMPT), "prompt_sha256": sha(OUT_PROMPT),
                "status": "PASS_COMPLETE_CHANGED_INPUT_U19C_REPAIR4"})
    prompt_manifest["rows"] = [
        row if item["unit_id"] == "E35-CW-U19C" else item
        for item in prompt_manifest["rows"]
    ]
    prompt_manifest["unit_count"] = len(prompt_manifest["rows"])
    prompt_manifest["scope"] = "FAILED_ONLY_U19C_TWO_IMAGE_ONE_AUDIO_REPAIR4"
    write(OUT_PROMPTS, prompt_manifest)

    dialogue = load(BASE_DIALOGUE)
    dialogue["rows"] = [row for row in dialogue["rows"] if row["video_unit_id"] == "E35-CW-U19C"]
    dialogue["line_count"] = len(dialogue["rows"])
    dialogue["status"] = "PASS"
    dialogue["scope"] = "FAILED_ONLY_U19C_TWO_IMAGE_ONE_AUDIO_REPAIR4"
    write(OUT_DIALOGUE, dialogue)

    config["tasks"] = [task]
    config["complete_video_prompt_manifest_ref"] = rel(OUT_PROMPTS)
    config["dialogue_manifest_ref"] = rel(OUT_DIALOGUE)
    config["runtime_seconds"] = 6
    config["recorded_at"] = datetime.now(timezone.utc).isoformat()
    config["preserved_prompt_professionalism_evidence"] = [{
        "task_key": "E35-CW-U19C-COMPLETE-PROMPT-V1-REPAIR4", "scene_id": task["scene_id"],
        "prompt_file": task["prompt_file"], "prompt_sha256": task["prompt_sha256"],
    }]
    write(OUT_CONFIG, config)
    write(EVIDENCE, {
        "schema": "qingshan.e35.u19c.remote_failure_repair.v1", "episode": "E35",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "REPAIR4_CHANGED_INPUT_READY", "failed_task_id": "12659a6b-4dab-4dba-aaaa-a1ee1cef115c",
        "failed_net_credits": 0, "root_cause": "High-density four-image plus one-audio multimodal request repeated the refunded U01 failure pattern.",
        "changed_input": "Reduced to one scene-state image, one Chenji identity image and one Chenji voice reference; non-speaking roles moved off camera.",
        "rollback": "Use repair3 failure receipt and original prompt SHA.",
    })
    print(json.dumps({"status": "PASS", "task_key": task["task_key"], "fingerprint": task["generation_fingerprint"],
                      "reference_images": len(task["reference_images"]), "reference_audio_asset_ids": len(task["reference_audio_asset_ids"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
