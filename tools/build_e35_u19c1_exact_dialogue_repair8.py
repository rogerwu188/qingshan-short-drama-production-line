#!/usr/bin/env python3
"""Give E35 U19C1 a physically viable speech window after gibberish ASR failure."""

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
BASE_CONFIG = VIDEO_DIR / "E35_VIDEO_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6.json"
BASE_PROMPTS = PROD / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6.json"
BASE_DIALOGUE = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6.json"
OUT_CONFIG = VIDEO_DIR / "E35_VIDEO_U19C1_EXACT_DIALOGUE_REPAIR8.json"
OUT_PROMPTS = PROD / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1_U19C1_EXACT_DIALOGUE_REPAIR8.json"
OUT_DIALOGUE = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1_U19C1_EXACT_DIALOGUE_REPAIR8.json"
EVIDENCE = ROOT / "qa/e35_v1_release_20260723/E35_U19C1_REPAIR6_GIBBERISH_FAILURE_REPAIR8.json"


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
    task = copy.deepcopy(next(row for row in config["tasks"] if row["unit_id"] == "E35-CW-U19C1"))
    task["task_key"] = "E35-CW-U19C1-PERFORMANCE-V1-EXACT-DIALOGUE-REPAIR8"
    task["batch_id"] = "E35-V1-U19C1-EXACT-DIALOGUE-REPAIR8-20260724"
    task["visual_zone"] = "E35-CW-U19C1-V1-EXACT-DIALOGUE-REPAIR8"
    task["duration"] = 7
    task["duration_seconds"] = 7
    task["edit_target_duration_seconds"] = 7
    task["duration_plan"] = {
        "policy": "qingshan.shot_generation_duration.v5",
        "duration_seconds": 7,
        "rationale": "The locked 20-character sentence produced gibberish when compressed into four seconds; seven seconds is required for natural Mandarin articulation and reaction.",
        "edit_policy": "Use the full seven-second native performance; never truncate, loop, freeze or stretch dialogue.",
    }
    task["performance_spec"]["duration_seconds"] = 7
    task["performance_spec"]["motion_beats"][0]["end_seconds"] = 7.0
    task["performance_spec"]["motion_beats"][0]["action"] = (
        "陈迹看向镜头外同伴，以正常语速完整说出抓捕会让景朝像抹掉严敬一样立刻抹掉这个活口；说完合起账底并闭口。"
    )
    task["prompt_contract"]["source_action"] = task["performance_spec"]["motion_beats"][0]["action"]
    prompt = (ROOT / task["prompt_file"]).read_text(encoding="utf-8")
    prompt = re.sub(r"时长4秒。", "时长7秒。", prompt, count=1)
    prompt = prompt.replace("必须从本单元第0.2秒开始", "必须从本单元第0.2秒开始，以自然普通话速度在第6.2秒前完整说完")
    prompt = re.sub(r"0\.000-2\.880秒", "0.000-6.200秒", prompt)
    prompt = re.sub(r"2\.880-4\.000秒", "6.200-7.000秒", prompt)
    prompt += (
        "\n长句时长硬门：锁定台词共约20个汉字，已给足7秒；必须逐字说‘抓了，景朝立刻就会像抹严敬一样抹了他。’，"
        "禁止同义改写、乱码、外语、旁白、字幕腔或添加‘字幕by’。\n"
    )
    out_prompt = PROMPT_DIR / "E35-CW-U19C1-EXACT-DIALOGUE-REPAIR8.txt"
    out_prompt.write_text(prompt, encoding="utf-8")
    task["prompt_file"] = rel(out_prompt)
    task["prompt_path"] = rel(out_prompt)
    task["prompt_sha256"] = sha(out_prompt)
    task["repair_evidence"] = rel(EVIDENCE)
    task["multimodal_binding_sha256"] = hashlib.sha256(
        json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    task.pop("generation_fingerprint", None)
    task["generation_fingerprint"] = generation_fingerprint(task)

    prompt_manifest = load(BASE_PROMPTS)
    for row in prompt_manifest["rows"]:
        if row["unit_id"] == "E35-CW-U19C1":
            row.update({
                "duration_seconds": 7,
                "prompt_path": rel(out_prompt),
                "prompt_sha256": task["prompt_sha256"],
                "status": "PASS_COMPLETE_CHANGED_INPUT_U19C1_EXACT_DIALOGUE_REPAIR8",
            })
    prompt_manifest["scope"] = "FAILED_ONLY_U19C1_EXACT_DIALOGUE_REPAIR8"
    write(OUT_PROMPTS, prompt_manifest)

    dialogue = load(BASE_DIALOGUE)
    dialogue["rows"] = [row for row in dialogue["rows"] if row["video_unit_id"] == "E35-CW-U19C1"]
    dialogue["line_count"] = 1
    dialogue["status"] = "PASS"
    dialogue["scope"] = "FAILED_ONLY_U19C1_EXACT_DIALOGUE_REPAIR8"
    write(OUT_DIALOGUE, dialogue)

    config["tasks"] = [task]
    config["complete_video_prompt_manifest_ref"] = rel(OUT_PROMPTS)
    config["dialogue_manifest_ref"] = rel(OUT_DIALOGUE)
    config["runtime_seconds"] = 7
    config["recorded_at"] = datetime.now(timezone.utc).isoformat()
    config["preserved_prompt_professionalism_evidence"] = [{
        "task_key": task["task_key"],
        "scene_id": task["scene_id"],
        "prompt_file": task["prompt_file"],
        "prompt_sha256": task["prompt_sha256"],
    }]
    write(OUT_CONFIG, config)
    write(EVIDENCE, {
        "schema": "qingshan.e35.u19c1.gibberish_failure_repair8.v1",
        "episode": "E35",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "REPAIR8_CHANGED_INPUT_READY",
        "source_asr_report": "qa/e35_v1_release_20260723/E35_U19C_REPAIR6_TARGETED_ASR_V1.json",
        "failure": "The 20-character locked sentence was compressed into four seconds and generated unrelated gibberish.",
        "changed_input": "Duration increased to seven seconds and exact full sentence plus forbidden-gibberish contract added.",
        "planned_additional_video_seconds": 7,
        "planned_additional_video_credits": 140,
        "projected_episode_video_credit_total": 5700,
        "credit_limit": 6000,
        "rollback": "Preserve repair6 output and ASR failure; use repair8 only after exact native-dialogue PASS.",
    })
    print(json.dumps({"status": "PASS", "task": task["task_key"], "projected_episode_video_credits": 5700}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
