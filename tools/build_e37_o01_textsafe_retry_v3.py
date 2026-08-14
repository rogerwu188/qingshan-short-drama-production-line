#!/usr/bin/env python3
"""Build the materially changed, text-safe E37 opening O01 retry."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/opening_replacement_v1"
OUT = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/opening_replacement_v3"
ASSET = Path("working_assets/e37_opening_replacement_v3_20260803/anchors/E37_R_O01_TEXTSAFE_FROST_LEDGER_ANCHOR_V3.png")
PROMPT = Path("working_assets/e37_opening_replacement_v3_20260803/compiled_prompts/E37-R-O01_V3.txt")


def sha(path: str | Path) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    base_config = json.loads((BASE / "E37_OPENING_REPLACEMENT_BATCH_V1.json").read_text(encoding="utf-8"))
    task = deepcopy(next(row for row in base_config["tasks"] if row["unit_id"] == "E37-R-O01"))
    prompt = """[ACTION_SHOT_CONTRACT_V1:4d1132b9ca7e47bd11bec83701469c80fd898b2337e6aae0820b847bde9e3102]
【E37-R-O01｜看守账空白证据｜固定物件特写｜materially changed V3】
[[scene_liuzhai_opening]] [[prop_guard_ledger]]
【天气硬合同】weather=INTERIOR_CLEAR_NO_RAIN
镜头1【特写 固定俯视机位 locked_object_detail，全程锁死三脚架，禁止摇镜、横移、环绕、推拉、变焦】中国古代架空洛城刘家旧宅正屋，夜，干燥无雨。@图片1是唯一首帧与空间权威：一只年轻男子右手正在翻开唯一一本完全空白的旧布面账册，指尖已经接触纸面，霜纹刚开始生长。
动作因果链只执行一次：0.0-1.2秒，右手食指压住空白页，霜纹从接触点向左下生长；1.2-2.8秒，拇指和食指把右页向左翻过，霜纹沿折页边缘断开；2.8-4.2秒，手掌离开，唯一账册保持新页摊平，霜纹停止扩展；4.2-5.0秒，纸角受窗缝夜风轻颤一次后静止。{无对白} <翻页、霜裂、衣袖摩擦和远处夜风同期声>。力量作用环境：指腹压力使纸页弯曲，翻页带动纸角和布袖，霜裂只从接触点扩展，窗缝夜风只让纸角轻颤一次。
色彩与动机光：墨蓝夜影、旧纸冷灰、深棕木桌，画外冷月为主光，画外陶制油碟的极弱暖光只勾勒手背，画面内不出现灯具或火焰。
画面只含单手、灰色古代布袖、空白旧纸、深棕布面账册、粗木桌与冷月窗影；可见光源全部在画外。所有纸页彻底空白，不得出现任何墨点、横线、竖线、表格、格网、文字、伪文字、数字、印章、标签或书名。
NEGATIVE_PROMPT: readable text, pseudo-text, calligraphy, number, grid, ruled page, seal, label, glass lamp, kerosene lamp, visible flame, subtitle, watermark, logo, modern object, second hand, extra finger, duplicate ledger, camera sway, handheld, pan, orbit, zoom, dolly, reset, replay, loop, slow motion, frozen pose.
"""
    prompt_path = ROOT / PROMPT
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")

    task.update({
        "task_key": "E37-R-O01-OPENING-TEXTSAFE-RETRY-V3",
        "batch_id": "E37-OPENING-O01-TEXTSAFE-RETRY-V3-20260803",
        "prompt_file": str(PROMPT),
        "prompt_path": str(PROMPT),
        "prompt_sha256": sha(PROMPT),
        "reference_images": [str(ASSET)],
        "reference_image_sequence": [{
            "asset_label": "@图片1",
            "role": "TEXTSAFE_BLANK_LEDGER_START_ANCHOR_V3",
            "path": str(ASSET),
            "sha256": sha(ASSET),
            "identity_reference": False,
        }],
        "planned_reference_image_count": 1,
        "state_reference_minimum": 1,
        "keyframe_interpolation_gate": {
            "status": "PASS",
            "checked_adjacent_pairs": 0,
            "adjacent_pairs_checked": 0,
            "reason": "One text-safe locked start anchor drives one continuous object action."
        },
        "changed_input_repair": True,
        "unchanged_retry": False,
        "replaces_parent_task_id": "db3b5057-f910-4e19-9681-885ed014469d",
        "output_dir": "working_assets/e37_opening_replacement_v3_20260803/outputs",
        "qa_dir": "qa/e37_opening_replacement_v3_20260803",
    })
    task["performance_spec"]["motion_beats"][0].update({
        "action": "食指压住空白页触发霜纹，翻过唯一一页后手掌离开",
        "contact_point": "右手食指与完全空白纸面",
        "direction": "霜纹由接触点向左下扩展，书页由右向左翻过",
        "end_state": "新空白页摊平、霜纹停止、手掌离开且纸角只轻颤一次",
    })

    anchor_plan = json.loads((BASE / "E37_OPENING_ANCHOR_PLAN_V1.json").read_text(encoding="utf-8"))
    for unit in anchor_plan["units"]:
        if unit["unit_id"] != "E37-R-O01":
            continue
        unit.update({
            "planned_reference_image_count": 1,
            "reference_image_task_keys": ["E37-R-O01-TEXTSAFE-START-V3"],
            "keyframe_interpolation_gate": {"status": "PASS", "adjacent_pairs_checked": 0},
        })
        unit["anchor_count_decision"].update({
            "planned_reference_image_count": 1,
            "reason": "One locked text-safe start anchor contains the only contact and the continuous page-turn end state.",
            "criteria": {
                "continuous_motion_from_single_start": True,
                "identity_or_space_reanchor": False,
                "prop_ownership_transition": False,
                "non_interpolable_terminal_state": False,
            },
            "anchor_roles": ["TEXTSAFE_START_STATE"],
        })
    anchor_plan["planned_reference_image_count"] = sum(row["planned_reference_image_count"] for row in anchor_plan["units"])
    anchor_target = OUT / "E37_OPENING_ANCHOR_PLAN_V3.json"
    write_json(anchor_target, anchor_plan)

    prompt_manifest = json.loads((BASE / "E37_OPENING_COMPLETE_PROMPT_MANIFEST_V1.json").read_text(encoding="utf-8"))
    for row in prompt_manifest["rows"]:
        if row["unit_id"] == "E37-R-O01":
            row.update({"prompt_path": str(PROMPT), "prompt_sha256": sha(PROMPT)})
    complete = OUT / "E37_OPENING_COMPLETE_PROMPT_MANIFEST_V3.json"
    write_json(complete, prompt_manifest)

    config = deepcopy(base_config)
    config.update({
        "status": "READY_O01_TEXTSAFE_FAILED_ONLY_RETRY_V3",
        "concurrency": 1,
        "max_retries": 0,
        "output_dir": "working_assets/e37_opening_replacement_v3_20260803/outputs",
        "qa_dir": "qa/e37_opening_replacement_v3_20260803",
        "anchor_count_plan_ref": str(anchor_target.relative_to(ROOT)),
        "complete_video_prompt_manifest_ref": str(complete.relative_to(ROOT)),
        "tasks": [task],
    })
    target = OUT / "E37_OPENING_O01_TEXTSAFE_RETRY_BATCH_V3.json"
    write_json(target, config)
    print(json.dumps({"status": "BUILT", "config": str(target.relative_to(ROOT)), "tasks": 1}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
