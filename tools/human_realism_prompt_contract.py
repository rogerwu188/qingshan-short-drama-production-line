#!/usr/bin/env python3
"""Reusable prompt clauses for grounded faces and human performance."""

from __future__ import annotations

import re
from typing import Any


CONTRACT_VERSION = "1.0.0"


def _lens_for(scale: str) -> tuple[str, str, str]:
    value = scale.lower()
    if re.search(r"特写|近景|close|portrait", value):
        return "85mm", "f/2", "浅景深只分离人物，不抹平皮肤"
    if re.search(r"中景|medium", value):
        return "50mm", "f/2.8", "中浅景深保留人物与空间关系"
    return "35mm", "f/4", "较深景深保留真实环境尺度"


def _identity_age_text(character_ids: list[str], locks: dict[str, dict[str, Any]]) -> str:
    rows = []
    for character_id in character_ids:
        lock = locks.get(character_id) or {}
        immutable = lock.get("immutable") or {}
        age = immutable.get("age") or immutable.get("年龄") or immutable.get("age_range")
        gender = immutable.get("gender") or immutable.get("性别")
        label = lock.get("name") or character_id
        facts = "、".join(str(value) for value in (age, gender) if value)
        rows.append(f"{label}按身份锁保持{facts or '既定年龄、性别与骨相'}")
    return "；".join(rows)


def build_keyframe_realism_block(
    *,
    character_ids: list[str],
    character_locks: dict[str, dict[str, Any]],
    shot_scale: str,
    lens_intent: str,
    action: str,
    expression_arc: str | None = None,
    eyeline_target: str | None = None,
) -> str:
    """Compile one narrative-first anti-plastic character keyframe clause."""
    if not character_ids:
        return (
            "【真人质感合同 v1】本镜无人脸特写；仍保持真实镜头曝光、材料粗糙度、空气透视与自然动态范围，"
            "禁止CG塑料材质、过度HDR、锐化光晕和游戏渲染感。"
        )
    lens, aperture, depth = _lens_for(f"{shot_scale} {lens_intent}")
    identity = _identity_age_text(character_ids, character_locks)
    motivation = expression_arc or f"由当前动作“{action}”触发的克制即时反应"
    target = eyeline_target or "当前剧本动作对象或对手的准确空间位置"
    return (
        "【真人面孔与表演合同 v1】"
        f"{identity}，身份与年龄优先于漂亮；不把年轻角色做成熟，不把年长角色磨成年轻。"
        "皮肤保留真实毛孔、细小汗毛、轻微色差、淡斑或生活痕迹，以及符合年龄的肌理；"
        "左右脸和眉眼允许自然轻微不对称，鼻翼、法令区、眼下与唇纹不被磨平。"
        "眼球有受现场光驱动的湿润反射，睫毛根和眉毛单根可见，拒绝玻璃眼、蜡像皮、瓷娃娃脸。"
        f"表情动机={motivation}；视线落点={target}；眉间、下眼睑、鼻翼、嘴角与下颌不要同时同幅度变化，"
        "保留真实反应的时间差；呼吸、喉结、肩颈和手指张力支持同一情绪，禁止只换一张表情贴纸。"
        "关键帧停在反应发生的中间态，能读出上一秒刺激和下一秒动作，不摆广告笑、不直视镜头求漂亮。"
        f"摄影={lens}真实电影镜头、{aperture}、{depth}，RAW式宽容度、自然肤色、克制颗粒与锐度；"
        "只用场景内动机光形成柔和轮廓和渐变阴影，不用影楼环形灯或无来源轮廓光。"
        "禁止美颜、磨皮、液化、左右镜像脸、网红妆、假睫毛滤镜、过度祛斑、塑料皮、蜡像感、"
        "虚假HDR、过锐、过饱和、CG渲染、游戏角色、广告棚拍和博物馆假人质感。"
    )


def build_expression_realism_block(*, expression_arc: str, action: str, framing: str) -> str:
    """Turn an emotion label into a physically supported performance chain."""
    lens, aperture, depth = _lens_for(framing)
    return (
        "【真人微表演】"
        f"情绪不是标签：由动作“{action}”触发，内部变化按“{expression_arc}”发生。"
        "先让视线准确落到事件对象，再由下眼睑或眉间产生极轻变化，随后鼻翼、嘴角、下颌只选择一至两处跟进；"
        "眨眼、吸气、吞咽、肩颈松紧、身体重心或手指张力至少有一项与情绪同步，变化存在自然先后和微小迟疑。"
        "说话时嘴角、呼吸和目光不机械循环；不说话的人保持活的呼吸与倾听反应，不做僵硬背景板。"
        "情绪结束后留有未完全归零的残余，不突然换脸，不全程保持同一张夸张表情。"
        f"近脸画面遵守{lens}、{aperture}、{depth}的真实光学逻辑；保留毛孔、细汗毛、唇纹、眼球湿润反光和轻微面部不对称。"
        "禁止AI式标准微笑、同时挑眉瞪眼张嘴、左右完全对称、橡胶嘴、玻璃眼、蜡像皮、磨皮美颜、网红摆拍和过度表演。"
    )


def validate_human_realism_prompt(text: str) -> list[dict[str, str]]:
    """Validate only the explicitly adopted realism contract vocabulary."""
    checks = {
        "skin_microtexture": r"毛孔.*汗毛|汗毛.*毛孔",
        "facial_asymmetry": r"不对称|非对称",
        "eye_wet_reflection": r"湿润反射|湿润反光|泪膜",
        "motivated_expression": r"表情动机|情绪不是标签|视线落点",
        "body_supported_expression": r"肩颈|手指张力|身体重心|吞咽",
        "real_optics": r"(?:35|50|85)mm.*f/[0-9]",
        "anti_plastic_negative": r"塑料皮|蜡像皮|蜡像感",
        "anti_beauty_filter": r"磨皮|美颜",
    }
    return [
        {"check": code, "detail": f"missing adopted human-realism prompt clause: {pattern}"}
        for code, pattern in checks.items()
        if not re.search(pattern, text, re.I | re.S)
    ]
