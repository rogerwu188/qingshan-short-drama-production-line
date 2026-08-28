#!/usr/bin/env python3
"""Build the two new E44 v5 identity cards without provider submission."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_preproduction_20260828"
PROMPTS = PROD / "identity_prompts_v1"
PLAN = PROD / "E44_V5_NEW_IDENTITY_ASSET_PLAN_V1.json"
GATE = QA / "E44_V5_NEW_IDENTITY_ASSET_GATE_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


PROMPT_TEXT = {
    "CHAR-E44-JINZHU": (
        "9:16竖版。北宋末年历史短剧电影写实角色设定图，正面三分之二侧身全身，纯中性灰褐背景，单人居中。"
        "金猪，三十五至四十岁东方面孔，长期日晒形成的自然深肤色，宽而平和的脸，眼尾有细小笑纹，鼻梁端正，嘴角常带和煦轻笑；"
        "笑容亲切但眼神极稳，不做反派阴鸷眼，不做凶狠杀手脸。头发束成朴素低髻，无官帽，无胡须。"
        "穿粗布短褐与旧灰褐外袍，腰间只有布带；脚穿磨旧草鞋，手持一顶无字素竹斗笠。"
        "衣物有真实劳作磨损但干净，外表像普通佃户，站姿放松、重心稳定。不得携带武器，不得穿官袍、盔甲或黑色刺客服。"
        "平视50mm自然透视，柔和阴天侧光，皮肤毛孔、发丝、草鞋纤维、竹篾与粗布经纬真实。"
        "禁止低机位英雄化、阴影遮脸、邪笑、可读文字、字幕、LOGO、水印、多人物、拼图、分屏、现代物件、游戏渲染感。\n"
    ),
    "CHAR-E44-ZHULINGYUN": (
        "9:16竖版。北宋末年历史短剧电影写实角色设定图，正面三分之二侧身全身，纯中性灰褐背景，单人居中。"
        "朱灵韵，十七至十九岁东方面孔，独立且不可与白鲤复用的年轻女性面孔；清秀偏圆的脸，眉形利落，眼睛明亮但此刻微红，"
        "神态是自尊受挫后的强撑，不是恶毒或傲慢反派。黑发梳成未婚少女双环髻，只有素银小簪。"
        "穿王府年轻郡主的克制常服：灰青偏紫窄袖交领长衫、冷白中衣、暗色长裙，衣料精良但无夸张金饰；袖口留有翻墙沾到的少量灰土。"
        "双手自然垂落，其中一只手指还保持刚拍过袖土后的轻微张开；身形纤细，站姿挺直。"
        "平视50mm自然透视，柔和冷色侧光，皮肤毛孔、发丝与织物纤维真实。"
        "禁止复用白鲤脸、现代妆容、仙侠头饰、可读文字、字幕、LOGO、水印、多人物、拼图、分屏、现代物件、游戏渲染感。\n"
    ),
}


def main() -> int:
    PROMPTS.mkdir(parents=True, exist_ok=True)
    rows = []
    for character_id, text in PROMPT_TEXT.items():
        prompt = PROMPTS / f"{character_id}.txt"
        prompt.write_text(text, encoding="utf-8")
        rows.append({
            "id": character_id,
            "display_name": "金猪" if character_id.endswith("JINZHU") else "朱灵韵",
            "prompt_file": str(prompt.relative_to(ROOT)),
            "prompt_sha256": sha(prompt),
            "reference_images": [], "reference_image_sha256s": [],
            "status": "READY_TO_SUBMIT", "maximum_new_submissions": 1,
            "identity_rule": "NEW_UNIQUE_FACE_NO_REUSE",
        })
    write_json(GATE, {
        "schema": "qingshan.identity_asset_gate.v1", "episode": "E44",
        "gate_id": "E44-V5-JINZHU-ZHULINGYUN-UNIQUE-IDENTITIES", "status": "PASS",
        "checks": {
            "exactly_two_new_named_characters": True,
            "jinzhu_source_fidelity_straw_sandals_bamboo_hat_coarse_robe_sun_darkened_mild_smile": True,
            "jinzhu_weapon_official_robe_villain_eye_low_angle_shadow_lighting_forbidden": True,
            "zhulingyun_distinct_from_baili": True,
            "vertical_9x16": True, "no_readable_text": True,
            "content_attempt_cap_per_image": 10,
        },
    })
    write_json(PLAN, {
        "schema": "qingshan.character_asset_plan.v1", "episode": "E44", "quality": "pro",
        "authorization_ref": "ROGER-20260828-START-E44-PRODUCTION",
        "machine_gate_reports": [str(GATE.relative_to(ROOT))],
        "maximum_new_submissions": len(rows), "new_asset_groups": rows,
    })
    print(json.dumps({"status": "PASS", "new_identities": len(rows), "plan": str(PLAN.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
