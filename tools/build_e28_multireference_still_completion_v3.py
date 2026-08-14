#!/usr/bin/env python3
"""Build E28's audited per-internal-shot still map and missing-state batch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e28_cl2x517_20260721"
MANIFEST_PATH = PRODUCTION / "E28_PRODUCTION_MANIFEST.json"
PLAN_PATH = PRODUCTION / "E28_MULTI_REFERENCE_STILL_PLAN_V3.json"
COMPLETION_DIR = PRODUCTION / "multireference_still_completion_v3"
PROMPT_DIR = COMPLETION_DIR / "prompts"
BATCH_PATH = COMPLETION_DIR / "E28_MULTI_REFERENCE_STILL_COMPLETION_V3_IMAGE_BATCH.json"
GATE_PATH = ROOT / "qa/e28_multireference_still_completion_v3_20260721/E28_MULTI_REFERENCE_STILL_COMPLETION_PREFLIGHT.json"
SOURCE_SHA = "d6418403ecfd3f7042d7bf08cb2297248eaaf96db86223994e8de75b16263ddc"

REGISTRY = "configs/series_continuity_asset_registry_20260712.json"
NEW_GATE = "qa/e28_claude_writer_v1_new_stills_review_20260721/E28_NEW_21_TIER_SCORE_GATE.json"
R1_GATE = "qa/e28_claude_writer_v1_new_stills_failed_only_r1_20260721/E28_NEW_STILLS_FAILED_ONLY_R1_TIER_SCORE_GATE.json"
REUSE_ADMISSION = "workflow/tasks/E28_CLAUDE_WRITER_V1_REUSE_CONDITIONAL_ADMISSION_20260721.json"
SUPPLEMENT_GATE = "qa/e28_multireference_still_supplement_v2_20260721/E28_MULTI_REFERENCE_STILL_SUPPLEMENT_V2_TIER_SCORE_GATE.json"

CHARACTER_REFS = {
    "chenji": "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg",
    "jiaotu": "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg",
    "yunyang": "ref_images/male_yunyang_ancient_ref_20260704.jpg",
}

SCENE_REFS = {
    "E28-CW-S01-SEALED-CHAMBER": "working_assets/e28_writer_agent_stills_failed_only_r1/candidates/E28_E28-S02-SH01-WRITER-AGENT-STILL-R1_276169ef-7fc3-46cf-aae5-73929a4caaaf.png",
    "E28-CW-S02-CHAMBER-ASSAULT": "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S02-SH03-STILL-V1_780e5781-4ce2-4fb4-988d-e5dd6fe0a071.png",
    "E28-CW-S03-AUTOPSY-SIDE-ROOM": "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S03-SH03-STILL-V1_41e392fb-2f60-40dc-aa2d-ebf83ad1f248.png",
    "E28-CW-S04-SCREEN-CORRIDOR-FIGHT": "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S04-SH02-STILL-V1_0ee24b28-8b7b-48f5-b894-313370d85523.png",
    "E28-CW-S05-SNOW-ALLEY": "working_assets/e28_claude_writer_v1_reuse_failed_only_r1_20260721/candidates/E28_E28-CW-S05-SH01-STILL-V1_9e9c9d60-d60b-4532-bb53-88aef11db71c.png",
}

SCENE_QA = {
    "E28-CW-S01-SEALED-CHAMBER": REUSE_ADMISSION,
    "E28-CW-S02-CHAMBER-ASSAULT": NEW_GATE,
    "E28-CW-S03-AUTOPSY-SIDE-ROOM": NEW_GATE,
    "E28-CW-S04-SCREEN-CORRIDOR-FIGHT": NEW_GATE,
    "E28-CW-S05-SNOW-ALLEY": NEW_GATE,
}

PROTECTED_CLERK_REF = "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S01-SH01-STILL-V1_bf7104fc-f35a-4712-b1d1-32a233c92cab.png"
INSTRUCTOR_REF = "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S04-SH02-STILL-V1_0ee24b28-8b7b-48f5-b894-313370d85523.png"


def state(unit: str, index: int, source: str, seconds: int, moment: str, existing: str | None = None) -> dict[str, Any]:
    return {
        "unit_id": unit,
        "internal_shot_index": index,
        "state_id": f"{unit}-C{index}",
        "source_shot_id": source,
        "duration_seconds": seconds,
        "decisive_moment": moment,
        "existing_image": existing,
    }


UNITS = [
    ("E28-CW-U01", 15, [
        state("E28-CW-U01", 1, "E28-CW-S01-SH01", 2, "密室厚木门刚刚阖死，门闩正在落入槽内，烛焰被气流压低；画面无人。"),
        state("E28-CW-U01", 2, "E28-CW-S01-SH01", 3, "皎兔单手把面色惨白的活口稳稳按在墙角，控制姿态已经成立。", PROTECTED_CLERK_REF),
        state("E28-CW-U01", 3, "E28-CW-S01-SH01", 5, "云羊独自在密室高梁上低伏就位，俯视门窗与活口，身体保持轻捷警戒。"),
        state("E28-CW-U01", 4, "E28-CW-S01-SH02", 5, "陈迹双手发力把沉重木柜推抵门板，柜脚压紧地面，顶门动作完成前一瞬。"),
    ]),
    ("E28-CW-U02", 15, [
        state("E28-CW-U02", 1, "E28-CW-S01-SH02", 5, "门槛、窗缝、梁槽三道冰线已经闭合，陈迹在画面中确认布防。", "working_assets/e28_writer_agent_stills_failed_only_r1/candidates/E28_E28-S02-SH01-WRITER-AGENT-STILL-R1_276169ef-7fc3-46cf-aae5-73929a4caaaf.png"),
        state("E28-CW-U02", 2, "E28-CW-S01-SH03", 10, "薄霜反向爬上陈迹手背并钻向手腕，他正攥拳压下反噬。", "working_assets/e28_claude_writer_v1_new_stills_failed_only_r1_20260721/candidates/E28_E28-CW-S01-SH03-STILL-R1_2c0a401c-f6b3-45eb-a2a7-adc86e6738c6.png"),
    ]),
    ("E28-CW-U03", 11, [
        state("E28-CW-U03", 1, "E28-CW-S02-SH01", 4, "梁上霜丝骤然绷断，断口逆卷向屋脊。", "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S02-SH01-STILL-V1_ede8a971-69e6-4a50-af7c-fae3d8ad37b5.png"),
        state("E28-CW-U03", 2, "E28-CW-S02-SH02", 5, "黑影沿垂索坠入，刀锋已经直逼活口咽喉。", "working_assets/e28_writer_agent_stills_v1/candidates/E28_E28-S02-SH03-WRITER-AGENT-STILL-V1_843b6f57-5ca1-45d7-86b1-091487aace51.png"),
        state("E28-CW-U03", 3, "E28-CW-S02-SH03", 2, "皎兔横刀挡住教习刀锋，刃口接触点火星飞溅。", "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S02-SH03-STILL-V1_780e5781-4ce2-4fb4-988d-e5dd6fe0a071.png"),
    ]),
    ("E28-CW-U04", 11, [
        state("E28-CW-U04", 1, "E28-CW-S02-SH03", 3, "皎兔横刀护在身前，另一只手已把活口拨到自己身后，三人空间关系清晰。"),
        state("E28-CW-U04", 2, "E28-CW-S02-SH04", 5, "陈迹五指扣住教习持刀手腕，三枚暗器已经钉入旁侧柜面。", "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S02-SH04-STILL-V1_4221c7ab-cb13-4a6c-9a31-52489820e187.png"),
        state("E28-CW-U04", 3, "E28-CW-S02-SH05", 3, "远处文书房内，一只枯瘦手握朱红笔，笔尖悬停在完全无字的纸面上方，尚未接触。"),
    ]),
    ("E28-CW-U05", 12, [
        state("E28-CW-U05", 1, "E28-CW-S02-SH05", 1, "枯瘦手中的朱红笔尖刚刚触到完全无字的纸面。", "working_assets/e28_claude_writer_v1_new_stills_failed_only_r1_20260721/candidates/E28_E28-CW-S02-SH05-STILL-R1_da9c9ca2-fb2b-440f-82b6-8a0d1327226d.png"),
        state("E28-CW-U05", 2, "E28-CW-S02-SH06", 5, "活口喉间一线血花，身体软倒在皎兔臂弯。", "working_assets/e28_claude_writer_v1_new_stills_failed_only_r1_20260721/candidates/E28_E28-CW-S02-SH06-STILL-R1_e6f3ecc3-4246-4732-a4d9-1d132aef8db8.png"),
        state("E28-CW-U05", 3, "E28-CW-S02-SH07", 6, "逆升霜痕清晰指向檐上狭窄暗槽，陈迹抬眼锁定逃路。", "working_assets/e28_claude_writer_v1_reuse_failed_only_r1_20260721/candidates/E28_E28-CW-S02-SH07-STILL-V1_10501993-3da3-4547-9a6c-39b45513f146.png"),
    ]),
    ("E28-CW-U06", 15, [
        state("E28-CW-U06", 1, "E28-CW-S03-SH01", 9, "皎兔俯身观察尸身颈侧刀痕，陈迹与云羊在证据桌另一侧。", "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S03-SH01-STILL-V1_90177755-a63c-4bbd-b1b4-15b7392e18e3.png"),
        state("E28-CW-U06", 2, "E28-CW-S03-SH02", 6, "皎兔以悬挂布囊作假靶，刀锋刚劈开布面，裂口和刀路清晰。"),
    ]),
    ("E28-CW-U07", 15, [
        state("E28-CW-U07", 1, "E28-CW-S03-SH02", 4, "皎兔手腕内旋完成反向卸力，陈迹在同一证据台前贴近比对两道切口。"),
        state("E28-CW-U07", 2, "E28-CW-S03-SH03", 11, "薄冰封住两道切口边缘，一道霜裂朝外、一道朝内，受力证据清晰。", "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S03-SH03-STILL-V1_41e392fb-2f60-40dc-aa2d-ebf83ad1f248.png"),
    ]),
    ("E28-CW-U08", 13, [
        state("E28-CW-U08", 1, "E28-CW-S04-SH01", 4, "屏风后一线人形暗影拉长，皎兔已经转身蓄势。", "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S04-SH01-STILL-V1_7d63213e-1a4d-45ca-8afa-a6b6137c9b79.png"),
        state("E28-CW-U08", 2, "E28-CW-S04-SH02", 5, "教习拔刀破屏，撕裂屏帛间刀锋直劈皎兔面门。", "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S04-SH02-STILL-V1_0ee24b28-8b7b-48f5-b894-313370d85523.png"),
        state("E28-CW-U08", 3, "E28-CW-S04-SH03", 4, "皎兔贴身侧闪，刀锋刚划开她肩头外层衣料，身体轴线仍稳定。"),
    ]),
    ("E28-CW-U09", 13, [
        state("E28-CW-U09", 1, "E28-CW-S04-SH03", 1, "皎兔反手一刀完成反击，教习被迫后撤。", "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S04-SH03-STILL-V1_a7e55b85-4aab-4e85-9578-8277092726dd.png"),
        state("E28-CW-U09", 2, "E28-CW-S04-SH04", 5, "云羊指尖点地，数条皮影纸人沿地面和梁柱展开封路。", "working_assets/e28_claude_writer_v1_new_stills_failed_only_r1_20260721/candidates/E28_E28-CW-S04-SH04-STILL-R1_bbc909fe-e736-4ae6-9117-860e3389a57c.png"),
        state("E28-CW-U09", 3, "E28-CW-S04-SH05", 6, "三人合围中陈迹撞肩把教习掀向窗棂，雕花木格正在爆裂。", "working_assets/e28_writer_agent_stills_v1/candidates/E28_E28-S03-SH02-WRITER-AGENT-STILL-V1_39a8d4a6-b338-426d-afe8-10599856e5fc.png"),
        state("E28-CW-U09", 4, "E28-CW-S04-SH06", 1, "破窗边雪幕卷入，教习唯一实体轮廓外刚拖出数道半透明错位雪光残像，陈迹的冰层已封住墙头落点；残像不是独立人物。"),
    ]),
    ("E28-CW-U10", 14, [
        state("E28-CW-U10", 1, "E28-CW-S04-SH06", 7, "教习脚尖踏碎墙头冰层并翻上飞檐，碎冰悬在风雪中。", "working_assets/e28_writer_agent_stills_v1/candidates/E28_E28-S03-SH03-WRITER-AGENT-STILL-V1_2c6a96bb-b4ea-4469-b9d5-195959d45f2e.png"),
        state("E28-CW-U10", 2, "E28-CW-S04-SH07", 7, "陌生私记半陷雪中，陈迹拾起仍有余温的蜡面证物。", "working_assets/e28_claude_writer_v1_new_stills_failed_only_r1_20260721/candidates/E28_E28-CW-S04-SH07-STILL-R1_33e2e381-2f61-4867-89c8-7315cf3bc620.png"),
    ]),
    ("E28-CW-U11", 13, [
        state("E28-CW-U11", 1, "E28-CW-S05-SH01", 7, "风雪中的层叠飞檐如远山延伸，一道黑影在远处檐脊疾掠。", "working_assets/e28_claude_writer_v1_reuse_failed_only_r1_20260721/candidates/E28_E28-CW-S05-SH01-STILL-V1_9e9c9d60-d60b-4532-bb53-88aef11db71c.png"),
        state("E28-CW-U11", 2, "E28-CW-S05-SH02", 3, "云羊越巷落地急停，单手举火把回照雪面。", "working_assets/e28_claude_writer_v1_new_stills_failed_only_r1_20260721/candidates/E28_E28-CW-S05-SH02-STILL-R1_c2fe244e-762a-43c6-a1fb-1ece624e8da2.png"),
        state("E28-CW-U11", 3, "E28-CW-S05-SH02", 3, "陈迹滑跪在雪巷，以手掌把无字拓纸平压在脚印旁。", "working_assets/e28_multireference_still_supplement_v2_20260721/candidates/E28_E28-CW-S05-SH02-PRESS-STILL-V2_a1f27d30-bb33-4bb8-b9bb-a3e3d3c4c581.png"),
    ]),
    ("E28-CW-U12", 13, [
        state("E28-CW-U12", 1, "E28-CW-S05-SH03", 5, "陈迹指尖引出贴地冷雾，正在冻结将被新雪覆盖的脚印。", "working_assets/e28_writer_agent_stills_failed_only_r1/candidates/E28_E28-S03-SH04-WRITER-AGENT-STILL-R1_349fa889-29c2-4543-97bb-3fea3b762d1e.png"),
        state("E28-CW-U12", 2, "E28-CW-S05-SH04", 5, "火把照亮同一串脚印：前半深而短、后半长而轻浅。", "working_assets/e28_claude_writer_v1_reuse_failed_only_r1_20260721/candidates/E28_E28-CW-S05-SH04-STILL-V1_9c7a44b7-2f60-4ecf-b37d-3a9e787fb40f.png"),
        state("E28-CW-U12", 3, "E28-CW-S05-SH05", 3, "陈迹正要再引冰雾，失控冷雾已经从指尖逆冲手腕，手臂霜纹初现，他尚未跪倒。"),
    ]),
    ("E28-CW-U13", 12, [
        state("E28-CW-U13", 1, "E28-CW-S05-SH05", 3, "陈迹捂住心口单膝跪入雪中，冰流反噬达到峰值。", "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S05-SH05-STILL-V1_d5022832-1b6e-4507-8f0d-c373b366a82a.png"),
        state("E28-CW-U13", 2, "E28-CW-S05-SH06", 5, "黑毛灵猫乌云落在陈迹肩头，把透明珠抵进他掌心。", "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S05-SH06-STILL-V1_7d29a401-04b1-4ed2-89e4-85ba365da380.png"),
        state("E28-CW-U13", 3, "E28-CW-S05-SH07", 2, "陈迹手背霜纹正在褪去，他抬眼看向空檐并低头确认轻浅步幅。", "working_assets/e28_claude_writer_v1_new_stills_failed_only_r1_20260721/candidates/E28_E28-CW-S05-SH07-STILL-R1_3924a9c3-5383-4789-b842-9117114a4a5f.png"),
        state("E28-CW-U13", 4, "E28-CW-S05-SH07", 2, "无人空檐与雪巷形成纵深，轻浅脚印指向空檐并被风雪掩去。", "working_assets/e28_multireference_still_supplement_v2_20260721/candidates/E28_E28-CW-S05-SH07-EMPTY-EAVES-STILL-V2_7337187f-4ad3-4880-976f-7c71aa16d8b4.png"),
    ]),
]


MISSING = {
    "E28-CW-U01-C1": {"visible": [], "palette": "密室夜内，烛火暖红与深木暗色，门缝仅有极弱冷色环境光"},
    "E28-CW-U01-C3": {"visible": ["yunyang"], "palette": "密室夜内，烛火暖红照梁下，梁上保持冷暗层次"},
    "E28-CW-U01-C4": {"visible": ["chenji"], "palette": "密室夜内，烛火暖红与冰霜幽蓝初现，厚重木质真实"},
    "E28-CW-U04-C1": {"visible": ["jiaotu", "protected_clerk"], "palette": "密室袭击夜内，冷蓝主调，刀火余光为克制暖点"},
    "E28-CW-U04-C3": {"visible": [], "palette": "远处文书房夜内，压低暖烛光，朱红笔尖为唯一高饱和点"},
    "E28-CW-U06-C2": {"visible": ["jiaotu"], "palette": "停尸侧间夜内，烛火摇红为主，刀锋与布囊保持真实材质"},
    "E28-CW-U07-C1": {"visible": ["jiaotu", "chenji"], "palette": "停尸侧间夜内，暖烛底色，证据台局部幽蓝反光"},
    "E28-CW-U08-C3": {"visible": ["jiaotu", "instructor_shadow"], "palette": "屏风回廊夜内，青冷窗光与破屏后的暖烛光交错"},
    "E28-CW-U09-C4": {"visible": ["chenji", "instructor_shadow"], "palette": "破窗回廊连雪夜，青蓝雪色、月白反射与冰层银屑，禁止出现巨大月盘"},
    "E28-CW-U12-C3": {"visible": ["chenji"], "palette": "无月雪夜巷，青蓝雪色与火把暖橙，冰流幽蓝只集中在手腕"},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def binding(role: str, entity_id: str, path_value: str, qa_report: str) -> dict[str, Any]:
    path = ROOT / path_value
    if not path.is_file() or not (ROOT / qa_report).is_file():
        raise SystemExit(f"missing binding evidence: {entity_id} / {path_value} / {qa_report}")
    return {
        "role": role,
        "entity_id": entity_id,
        "path": path_value,
        "sha256": sha256(path),
        "qa_status": "PASS",
        "qa_report": qa_report,
    }


def task_bindings(row: dict[str, Any], scene_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for char_id in MISSING[row["state_id"]]["visible"]:
        if char_id in CHARACTER_REFS:
            result.append(binding("character", char_id, CHARACTER_REFS[char_id], REGISTRY))
        elif char_id == "protected_clerk":
            result.append(binding("character", char_id, PROTECTED_CLERK_REF, NEW_GATE))
        elif char_id == "instructor_shadow":
            result.append(binding("character", char_id, INSTRUCTOR_REF, NEW_GATE))
        else:
            raise SystemExit(f"unbound visible character: {char_id}")
    result.append(binding("scene", scene_id, SCENE_REFS[scene_id], SCENE_QA[scene_id]))
    return result


def prompt(row: dict[str, Any], shot: dict[str, Any]) -> str:
    visible = "、".join(MISSING[row["state_id"]]["visible"]) or "无可识别人物，仅环境或局部匿名手部"
    return (
        f"《青山》E28《纸上杀人》，锁源 SHA-256={SOURCE_SHA}。\n"
        f"内部镜头状态={row['state_id']}；来源镜头={row['source_shot_id']}。锁定剧情原文：{shot['action']}\n"
        f"只生成一个连续画面、一个决定性瞬间：{row['decisive_moment']}\n"
        f"可见人物身份仅限：{visible}。每张输入图只按 reference_bindings 指定用途使用；人物图只锁脸、体态和服装身份，场景图只锁空间材质与时段。不得继承参考图中的旧动作、旧站位、额外人物或旧剧情。\n"
        f"画面系统：{MISSING[row['state_id']]['palette']}。9:16 竖屏，2K，写实电影摄影，主体动作一眼可读，真实皮肤与织物，正确人体、手部、兵器接触和空间尺度，前中后景清楚。\n"
        "硬约束：不得把来源镜头中的其他动作拼进本图；不得拼贴、分镜格、同人实体分身或双胞胎；S04-SH06 授权的错位残影只能是围绕唯一实体的半透明雪光残像；不得新增人物、武器、建筑、道具或剧情结果；纸面、名册与印记不得出现可读文字或伪文字；不得生成字幕、水印或 Logo；不得出现重复肢体、额外手指、断肢、穿模或漂浮道具。"
    )


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest["source"]["script_sha256"] != SOURCE_SHA:
        raise SystemExit("source script SHA mismatch")
    shots = {item["shot_id"]: item for item in manifest["shots"]}

    flat = [row for _, _, rows in UNITS for row in rows]
    if len(UNITS) != 13 or len(flat) != 38:
        raise SystemExit("internal-shot count must be 38")
    if len({row["state_id"] for row in flat}) != len(flat):
        raise SystemExit("duplicate state id")
    if sum(duration for _, duration, _ in UNITS) != 172:
        raise SystemExit("unit runtime mismatch")
    for unit_id, duration, rows in UNITS:
        if not 8 <= duration <= 15 or sum(row["duration_seconds"] for row in rows) != duration:
            raise SystemExit(f"unit timing mismatch: {unit_id}")
        if not 2 <= len(rows) <= 4:
            raise SystemExit(f"internal-shot count outside 2-4: {unit_id}")

    existing_rows = []
    missing_rows = []
    used_existing_sha: dict[str, str] = {}
    for row in flat:
        if row["source_shot_id"] not in shots:
            raise SystemExit(f"unknown source shot: {row['source_shot_id']}")
        item = dict(row)
        if row["existing_image"]:
            image_path = ROOT / row["existing_image"]
            if not image_path.is_file():
                raise SystemExit(f"missing selected image: {row['existing_image']}")
            image_sha = sha256(image_path)
            if image_sha in used_existing_sha:
                raise SystemExit(f"one image reused across two states: {row['state_id']} and {used_existing_sha[image_sha]}")
            used_existing_sha[image_sha] = row["state_id"]
            item.update({"coverage": "EXACT_EXISTING", "image_path": row["existing_image"], "image_sha256": image_sha})
            existing_rows.append(item)
        else:
            if row["state_id"] not in MISSING:
                raise SystemExit(f"missing state has no generation contract: {row['state_id']}")
            item.update({"coverage": "MISSING_GENERATE_ONCE"})
            missing_rows.append(item)

    if len(existing_rows) != 28 or len(missing_rows) != 10:
        raise SystemExit(f"coverage count mismatch: {len(existing_rows)} existing / {len(missing_rows)} missing")

    unit_rows = []
    for unit_id, duration, rows in UNITS:
        unit_rows.append({
            "unit_id": unit_id,
            "duration_seconds": duration,
            "generation_mode": "entity_reference_sequence",
            "internal_shot_count": len(rows),
            "reference_state_count": len(rows),
            "internal_shots": [dict(row, coverage=("EXACT_EXISTING" if row["existing_image"] else "MISSING_GENERATE_ONCE")) for row in rows],
        })

    plan = {
        "schema": "qingshan.multireference_still_plan.v2",
        "episode": "E28",
        "source_script_sha256": SOURCE_SHA,
        "runtime_seconds": 172,
        "video_unit_count": 13,
        "internal_shot_state_count": 38,
        "existing_exact_state_count": 28,
        "missing_state_count": 10,
        "supersedes": rel(PRODUCTION / "E28_MULTI_REFERENCE_STILL_PLAN_V2.json"),
        "recalculation_reason": "V2 counted source segments rather than every internal shot and omitted the four-way S01 opening split.",
        "rules": [
            "ONE_INTERNAL_SHOT_EQUALS_ONE_ORDERED_REFERENCE_STATE",
            "ONE_REFERENCE_STATE_EQUALS_ONE_SINGLE_DECISIVE_MOMENT",
            "NO_IMAGE_SHA_MAY_COVER_TWO_DISTINCT_STATES",
            "VIDEO_UNIT_REFERENCE_COUNT_EQUALS_INTERNAL_SHOT_COUNT",
            "ONLY_MISSING_STATES_ARE_GENERATED",
        ],
        "video_units": unit_rows,
        "existing_states": existing_rows,
        "missing_states": missing_rows,
    }
    PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for row in missing_rows:
        shot = shots[row["source_shot_id"]]
        prompt_path = PROMPT_DIR / f"{row['state_id']}.txt"
        prompt_path.write_text(prompt(row, shot) + "\n", encoding="utf-8")
        refs = task_bindings(row, shot["scene_id"])
        contract = {
            "schema": "qingshan.image_prompt_contract.v2",
            "shot_id": row["state_id"],
            "source_script_sha256": SOURCE_SHA,
            "source_action": shot["action"],
            "source_action_sha256": text_sha(shot["action"]),
            "visible_characters": MISSING[row["state_id"]]["visible"],
            "character_binding_mode": "EXPLICIT_VISIBLE_CHARACTERS",
            "reference_bindings": refs,
            "state_role": "internal_shot_decisive_moment",
            "single_decisive_moment": row["decisive_moment"],
            "status": "PASS",
            "failures": [],
        }
        tasks.append({
            "task_key": f"{row['state_id']}-STILL-V3",
            "tool_type": "image_generation",
            "scene_id": shot["scene_id"],
            "shot_id": row["state_id"],
            "beat_id": row["unit_id"],
            "prompt_file": rel(prompt_path),
            "prompt_sha256": sha256(prompt_path),
            "reference_images": [item["path"] for item in refs],
            "reference_bindings": refs,
            "prompt_contract": contract,
            "model": "gpt-image-2-pro",
            "aspect_ratio": "9:16",
            "resolution": "2K",
            "status": "READY_FOR_PARALLEL_SUBMIT",
            "source_script_sha256": SOURCE_SHA,
        })

    GATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    gate = {
        "schema": "qingshan.multireference_still_completion_preflight.v1",
        "episode": "E28",
        "status": "PASS",
        "source_script_sha256": SOURCE_SHA,
        "plan": rel(PLAN_PATH),
        "plan_sha256": sha256(PLAN_PATH),
        "video_units": 13,
        "internal_shot_states": 38,
        "existing_exact_states": 28,
        "missing_states": 10,
        "duplicate_existing_image_sha_count": 0,
        "task_keys": [task["task_key"] for task in tasks],
        "generation_policy": "ONE_CONCURRENT_BATCH_MISSING_ONLY_NO_AUTOMATIC_RETRY",
    }
    GATE_PATH.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    batch = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E28",
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "source_script_sha256": SOURCE_SHA,
        "machine_gate_reports": [rel(GATE_PATH)],
        "output_dir": "working_assets/e28_multireference_still_completion_v3_20260721/candidates",
        "qa_dir": "qa/e28_multireference_still_completion_v3_20260721",
        "retry_policy": "NO_AUTOMATIC_RETRY_SELECT_BEST_EXISTING_CANDIDATE",
        "consumer_contract": {
            "purpose": "COMPLETE_PER_INTERNAL_SHOT_REFERENCE_STATES_FOR_13_VIDEO_UNITS",
            "not_a_video_call_plan": True,
            "video_compilation_mode": "entity_reference_sequence",
            "required_state_count": 38,
        },
        "tasks": tasks,
        "blocked_tasks": [],
    }
    BATCH_PATH.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "video_units": 13,
        "internal_shot_states": 38,
        "existing_exact_states": 28,
        "missing_tasks": 10,
        "plan": rel(PLAN_PATH),
        "batch": rel(BATCH_PATH),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
