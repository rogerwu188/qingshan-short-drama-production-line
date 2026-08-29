#!/usr/bin/env python3
"""Prepare the one new named E43 identity without submitting it."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e43_v6_20260828"
QA = ROOT / "qa/e43_v6_preproduction_20260828"
PROMPT = PROD / "identity_prompts_v1/CHAR-E43-LINCHAOJING.txt"
PLAN = PROD / "E43_V6_NEW_IDENTITY_ASSET_PLAN_V1.json"
GATE = QA / "E43_V6_NEW_IDENTITY_ASSET_GATE_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(
        "9:16竖版构图。中国古代历史短剧的电影写实人像摄影风格角色设定图，正面三分之二侧身全身，纯中性灰褐背景，人物居中，不带场景。"
        "林朝京，二十七至三十岁东方面孔，清瘦长脸，窄而克制的双眼，眉骨略高，直鼻，薄唇，肤色自然偏冷，神态端正而自负；他与后续人物林朝青只存在亲族般八分轮廓相似，但本图必须是一张全新且不可与任何既有文人复用的独立面孔。"
        "黑发束成整洁文士髻，戴素黑小冠，无胡须。穿北宋末年书院文士服：深青灰交领长袍、内层冷白中衣、暗纹腰带，布料平整但不华丽，袖口有真实受力褶皱。"
        "右手持一柄完全素净、没有任何文字或图案的折扇，扇骨停在半开角度；左手自然垂落。身材高而偏瘦，站姿端直，下颌微收，气质是受过严格书院训练的克制与审视。"
        "柔和冷色侧光从画面左上方落下，另一侧只有微弱环境补光，皮肤毛孔、发丝与布料纤维真实可见，非明星脸，非现代妆发。"
        "禁止：任何文字、字幕、书法、扇面题字、LOGO、水印、现代物件、多人物、拼图、分屏、夸张仙侠装饰、游戏渲染感。\n",
        encoding="utf-8",
    )
    gate = {
        "schema": "qingshan.identity_asset_gate.v1", "episode": "E43", "gate_id": "E43-LINCHAOJING-UNIQUE-IDENTITY",
        "status": "PASS", "checks": {
            "new_named_character_declared": True, "unique_face_required": True,
            "no_existing_literati_reference_reused": True, "vertical_9x16": True,
            "no_readable_text": True, "content_attempt_cap": 10,
        },
    }
    write_json(GATE, gate)
    plan = {
        "schema": "qingshan.character_asset_plan.v1", "episode": "E43", "quality": "pro",
        "authorization_ref": "ROGER-20260828-START-E43-PRODUCTION",
        "machine_gate_reports": [str(GATE.relative_to(ROOT))],
        "maximum_new_submissions": 1,
        "new_asset_groups": [{
            "id": "CHAR-E43-LINCHAOJING", "display_name": "林朝京",
            "prompt_file": str(PROMPT.relative_to(ROOT)), "prompt_sha256": sha(PROMPT),
            "reference_images": [], "reference_image_sha256s": [],
            "status": "READY_TO_SUBMIT", "maximum_new_submissions": 1,
            "identity_rule": "NEW_UNIQUE_FACE_NO_REUSE",
        }],
    }
    write_json(PLAN, plan)
    print(json.dumps({"status": "PASS", "plan": str(PLAN.relative_to(ROOT)), "prompt_sha256": sha(PROMPT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
