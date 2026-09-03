#!/usr/bin/env python3
"""Bind and validate the project's cultural visual language before generation."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

SCHEMA = "qingshan.visual_culture_contract.v1"
PROFILE_ID = "QINGSHAN_NORTHERN_SONG_EASTERN_CINEMATIC"
ACTIVE_FROM_EPISODE = 54

DEFAULT_CONTRACT: dict[str, Any] = {
    "schema": SCHEMA,
    "status": "LOCKED",
    "profile_id": PROFILE_ID,
    "story_world": "北宋末年东方历史武侠世界",
    "production_design": "宋代中国木构、灰瓦、石砖、竹木器、宋制衣冠与东方兵甲；超现实梦境仍沿用同一东方造型体系",
    "armor_tradition": "宋代山文甲、札甲、鳞甲、兜鍪与东方护面结构；甲片以系带、皮革、织物和局部金属连接，不使用欧洲板甲轮廓",
    "palette_system": {
        "base": "低饱和黛青、月白、赭石、灰绿、烟墨",
        "accent": "暗朱、矿物青绿或旧金只作小面积叙事强调",
        "skin": "自然东方肤色，不用青灰尸色或橙青商业大片肤色",
    },
    "lighting_language": "宋画式含蓄层次、自然动机光、柔和高光滚降、保留暗部细节与适度留白；不用黑金海报硬光",
    "image_texture": "真人实拍历史短剧，丝绢、棉麻、木、石、陶瓷和旧金属的真实材料层次；不是游戏CG或概念海报",
    "forbidden_influences": [
        "欧洲中世纪骑士", "哥特式建筑", "西式板甲与尖面骑士盔", "十字军与纹章盾牌",
        "好莱坞黑金暗黑奇幻", "欧美史诗游戏海报", "蓝橙商业大片调色", "无来源神圣轮廓光",
    ],
}


def bind_visual_culture_contract(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    result.setdefault("visual_culture_contract", deepcopy(DEFAULT_CONTRACT))
    return result


def prompt_block_zh(contract: dict[str, Any] | None = None) -> str:
    c = contract or DEFAULT_CONTRACT
    return (
        f"【东方视觉文化硬合同】ID={c['profile_id']}；北宋东方武侠，宋制木构衣冠、札甲/山文甲/兜鍪；"
        "黛青月白赭石低饱和，自然柔光、真实材质。禁欧洲骑士/哥特/西式板甲尖面盔/纹章/黑金奇幻游戏海报/蓝橙调色。"
    )


def prompt_block_en(contract: dict[str, Any] | None = None) -> str:
    return (
        "EAST-ASIAN PERIOD VISUAL LOCK: Northern Song Chinese wuxia; Song timber/dress, lamellar or mountain-pattern armor, Chinese helmets; "
        "muted ink-blue/moon-white/ochre, soft motivated light, real materials. Never European medieval/Gothic, Western plate armor/pointed knight helmets, "
        "heraldry, black-gold Western fantasy/game-poster light, or teal-orange grade."
    )


def _episode_number(payload: dict[str, Any]) -> int | None:
    match = re.match(r"E(\d+)", str(payload.get("episode") or "").upper())
    return int(match.group(1)) if match else None


def validate_visual_culture_contract(payload: dict[str, Any], *, prompt_text: str | None = None) -> dict[str, Any]:
    episode = _episode_number(payload)
    required = episode is not None and episode >= ACTIVE_FROM_EPISODE
    contract = payload.get("visual_culture_contract")
    failures: list[str] = []
    if required and not isinstance(contract, dict):
        failures.append("VISUAL_CULTURE_CONTRACT_MISSING")
    if isinstance(contract, dict):
        if contract.get("schema") != SCHEMA:
            failures.append("VISUAL_CULTURE_CONTRACT_SCHEMA_INVALID")
        if contract.get("status") != "LOCKED":
            failures.append("VISUAL_CULTURE_CONTRACT_NOT_LOCKED")
        if contract.get("profile_id") != PROFILE_ID:
            failures.append("VISUAL_CULTURE_PROFILE_NOT_QINGSHAN_NORTHERN_SONG")
        if len(contract.get("forbidden_influences") or []) < 6:
            failures.append("VISUAL_CULTURE_FORBIDDEN_INFLUENCES_INCOMPLETE")
        if prompt_text is not None:
            required_tokens = (
                ("EAST-ASIAN PERIOD VISUAL LOCK", "Northern Song", "European medieval", "Western plate armor", "black-gold")
                if "EAST-ASIAN PERIOD VISUAL LOCK" in prompt_text else
                (PROFILE_ID, "宋", "东方", "欧洲", "板甲", "黑金")
            )
            failures.extend(
                f"VISUAL_CULTURE_PROMPT_TOKEN_MISSING:{token}"
                for token in required_tokens if token not in prompt_text
            )
    for row in payload.get("reference_bindings") or payload.get("reference_image_sequence") or []:
        if str(row.get("identity_visual_contract") or "").upper() != "FULLY_CONCEALED_IDENTITY":
            continue
        if row.get("cultural_style_profile_id") != PROFILE_ID:
            failures.append("FULL_APPEARANCE_IDENTITY_REFERENCE_CULTURE_UNADMITTED:" + str(row.get("entity_id") or "UNKNOWN"))
    return {
        "schema": "qingshan.visual_culture_contract_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "required": required,
        "profile_id": contract.get("profile_id") if isinstance(contract, dict) else None,
        "failures": failures,
    }
