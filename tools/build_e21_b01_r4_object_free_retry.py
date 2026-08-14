#!/usr/bin/env python3
"""Prepare the isolated E21 B01 retry after persistent generated-text QA."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/E21_standard_storyboard_rework_r3_visual_only_20260719.json"
OUT = ROOT / "configs/E21_standard_storyboard_rework_r4_b01_object_free_20260719.json"
PROMPT = ROOT / "workflow/prompts/e21_standard_storyboard_rework_r4_b01_object_free_20260719/E21-B01-STANDARD-STORYBOARD-V1-R4-OBJECT-FREE.txt"

PROMPT_TEXT = """这是《青山》E21《后宅传话》B01 的 Seedance 2.0 纯视觉动作母版。以参考图中的人物身份、脸、发型、服装、左右轴线和室内陈设为唯一视觉锚点。

场景严格为木构药房（medical hall）的室内会客区，夜间暖灯，雨已停止，只能听见极轻檐滴。镜头全程朝向人物和室内素面墙，不拍门口、不拍建筑外立面、不拍门楣、不拍牌匾、不拍招幌。禁止月亮、月光、雨幕、雾、雷电或新增地点。

本段只表现：一名王府传话人空手来到室内，向陈迹谎称失踪者已经找到，试图索回红线结；陈迹保持距离、追问来源；白鲤从侧后方观察来人的袖口压痕。不要出现官文、书信、书页、账册、腰牌、印章、木牌、纸张、屏风纹样、墙面装饰或任何容易生成字形的道具。人物手中始终没有文字载体。

这是 12 秒同一时空内的六镜头动作母版，无对白、无人声、无口型台词，只保留脚步、衣料和室内环境声：
镜头1：室内双人中景，传话人停在安全距离外，陈迹挡住去路。
镜头2：陈迹近景，抬眼追问，嘴唇闭合，仅用眼神和手势表达怀疑。
镜头3：传话人反打近景，神情闪躲，双手空着，身体重心后移。
镜头4：白鲤侧后方观察视角，聚焦传话人袖口新压痕，不出现任何符号。
镜头5：三人中景，陈迹向前半步形成压力，传话人退半步，权力关系发生变化。
镜头6：陈迹与白鲤交换视线，确认来人在说谎，以明确反应结束。

写实美剧式古装悬疑短剧，稳定构图，自然色彩，动作原生速度。六个机位和景别明确不同，切换只由动作、视线和新信息驱动。人物面部和身份稳定，动作连续，禁止慢动作、静止补时、循环动作、分身、额外肢体、穿模和身份漂移。

画面从上到下都必须完全无文字：禁止字幕、标题、气泡、书法、汉字、伪文字、数字、字母、水印、Logo、印章图案和背景音乐。所有背景必须是没有图案的素面材质。
"""


def main() -> int:
    config = json.loads(BASE.read_text(encoding="utf-8"))
    source = next(task for task in config["tasks"] if task.get("source_id") == "B01")
    task = dict(source)
    task.update({
        "task_key": "E21-B01-STANDARD-STORYBOARD-V1-R4-OBJECT-FREE",
        "prompt_file": str(PROMPT.relative_to(ROOT)),
        "metadata": dict(source.get("metadata") or {}, retry_reason="persistent_generated_text; remove every text-bearing object and exterior architectural surface"),
    })
    config.update({
        "max_retries": 0,
        "base_batch_note": "Failed-only R4 for B01. Preserve B02/B03/B04/B05/B06 passes; remove every text-bearing prop and facade.",
        "output_dir": "working_assets/e21_standard_storyboard_rework_r4_b01_object_free_20260719/candidates",
        "qa_dir": "qa/e21_standard_storyboard_rework_r4_b01_object_free_20260719",
        "tasks": [task],
    })
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(PROMPT_TEXT, encoding="utf-8")
    OUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "config": str(OUT), "prompt": str(PROMPT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
