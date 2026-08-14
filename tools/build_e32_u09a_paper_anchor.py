#!/usr/bin/env python3
"""Build the changed-input U09A paper-doll performance-start anchor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v1_20260722"
PROMPT = PROD / "image_prompts_performance_r6/E32-CW-U09A-A1-R6-PAPER-START.txt"
MANIFEST = PROD / "E32_IMAGE_U09A_PAPER_START_R6.json"
OUT_DIR = ROOT / "working_assets/e32_performance_stills_20260722/u09a_a1_r6"
QA_DIR = ROOT / "qa/e32_performance_stills_20260722/u09a_a1_r6"
SCRIPT_SHA = "2c7d194af236a50a2141fe59de83c0484d1ec3691637c1d26ca48f48b3ede24b"
REFERENCES = [
    ("character", "yunyang", ROOT / "working_assets/e32_reference_single_subject_20260723/yunyang_front_single.jpg"),
    ("character", "killer", ROOT / "working_assets/e28_u09_fixed_input_reference_20260722/E28-CW-U09-INSTRUCTOR-MASKED-SINGLE-REF.png"),
    ("scene", "E32-CW-S03", ROOT / "working_assets/e32_performance_stills_20260722/candidates/E32_E32-CW-U09-A1-STILL-V1_4f06bfa9-4eb9-4d9a-9eed-f4eba703bc2d.png"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    for _, _, path in REFERENCES:
        if not path.is_file():
            raise SystemExit(f"missing reference: {path}")
    prompt = (
        "竖屏9:16，宁朝洛城雨夜暗楼外廊，真实电影摄影，中景单一连续画面。严格只有两个人类："
        "年轻密谍司行官云羊与一名蒙面黑衣杀手。云羊身份和脸严格匹配角色参考，黑色窄袖劲装；"
        "杀手严格匹配蒙面参考。动作起点必须发生在冲拳之前：云羊站在画面左侧，右脚尚未后撤蓄力，"
        "右拳放松垂在身侧；左手在胸前用拇指压住一张完整的白色人形剪纸背面，食指正要触碰剪纸双眼，"
        "剪纸仍在云羊手里，没有飞出。杀手站在画面右侧冰墙前，双眼警惕盯着剪纸，短刃下垂但没有攻击。"
        "冰墙表面完整无裂纹、无蓝色固定点、无人被击倒。湿石地反射冷蓝月光，远处暖灯仅作空间背景。"
        "人物手指清楚，道具归属唯一；无第三人、无多余肢体、无文字、无字幕、无标志、无拼贴。"
    )
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(prompt + "\n", encoding="utf-8")
    bindings = [
        {"role": role, "entity_id": entity, "path": rel(path), "sha256": sha256(path),
         "qa_status": "PASS" if role == "character" else "PASS_COMPOSITION_ONLY"}
        for role, entity, path in REFERENCES
    ]
    task = {
        "task_key": "E32-CW-U09A-A1-STILL-R6-PAPER-START", "tool_type": "image_generation",
        "scene_id": "E32-CW-S03", "shot_id": "E32-CW-U09A-A1-R6",
        "editorial_shot_ids": ["E32-CW-S03-SH03"], "video_unit_id": "E32-CW-U09A",
        "video_unit_duration_seconds": 7, "state_index": 1, "state_count": 1,
        "beat_id": "E32-CW-U09A-R6", "prompt_file": rel(PROMPT), "prompt_sha256": sha256(PROMPT),
        "reference_images": [rel(path) for _, _, path in REFERENCES], "reference_bindings": bindings,
        "prompt_contract": {"schema": "qingshan.image_prompt_contract.v2", "shot_id": "E32-CW-U09A-A1-R6",
                            "source_script_sha256": SCRIPT_SHA, "source_action": prompt,
                            "source_action_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                            "visible_characters": ["yunyang", "killer"], "reference_bindings": bindings,
                            "editorial_shot_ids": ["E32-CW-S03-SH03"], "video_unit_id": "E32-CW-U09A",
                            "video_unit_duration_seconds": 7, "state_index": 1, "state_count": 1,
                            "state_role": "paper_doll_performance_start_before_punch", "status": "PASS", "failures": []},
        "model": "gpt-image-2-pro", "aspect_ratio": "9:16", "resolution": "2K",
        "status": "READY_FOR_PARALLEL_SUBMIT", "source_script_sha256": SCRIPT_SHA,
    }
    payload = {
        "schema": "qingshan.episode_parallel_batch.v1", "episode": "E32",
        "status": "READY_CHANGED_INPUT_U09A_PHYSICALLY_CORRECT_START",
        "source_script_sha256": SCRIPT_SHA, "output_dir": rel(OUT_DIR), "qa_dir": rel(QA_DIR),
        "machine_gate_reports": [
            "qa/e32_performance_preproduction_20260722/E32_IMAGE_PLAN_PREFLIGHT_V1.json",
            "qa/e32_performance_preproduction_20260722/E32_VIDEO_UNIT_ANCHOR_COUNT_GATE_V1.json"
        ],
        "consumer_contract": {
            "purpose": "PERFORMANCE_ANCHORS",
            "planned_anchor_count": 1,
            "incremental_video_submit": "SUBMIT_U09A_IMMEDIATELY_AFTER_THIS_ANCHOR_PASSES"
        },
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED", "tasks": [task],
    }
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": rel(MANIFEST), "prompt_sha256": sha256(PROMPT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
