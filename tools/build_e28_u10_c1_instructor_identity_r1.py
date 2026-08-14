#!/usr/bin/env python3
"""Build the one allowed changed-input U10-C1 identity repair task."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "d6418403ecfd3f7042d7bf08cb2297248eaaf96db86223994e8de75b16263ddc"
OUT = ROOT / "workflow/claude_writer_agent/production/e28_cl2x517_20260721/u10_c1_instructor_identity_r1"
PROMPT = OUT / "prompts/E28-CW-U10-C1-STILL-R1.txt"
BATCH = OUT / "E28_U10_C1_INSTRUCTOR_IDENTITY_R1_IMAGE_BATCH.json"
GATE = ROOT / "qa/e28_u10_c1_instructor_identity_r1_20260721/E28_U10_C1_INSTRUCTOR_IDENTITY_R1_PREFLIGHT.json"
IDENTITY = OUT / "E28_INSTRUCTOR_CANONICAL_IDENTITY_CONTRACT_V1.json"
MANIFEST = ROOT / "workflow/claude_writer_agent/production/e28_cl2x517_20260721/E28_PRODUCTION_MANIFEST.json"
INSTRUCTOR_REF = ROOT / "working_assets/e28_writer_agent_stills_v1/candidates/E28_E28-S03-SH03-WRITER-AGENT-STILL-V1_2c6a96bb-b4ea-4469-b9d5-195959d45f2e.png"
SCENE_REF = ROOT / "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S04-SH01-STILL-V1_7d63213e-1a4d-45ca-8afa-a6b6137c9b79.png"
SOURCE_ACTION = "教习借雪幕化出错位残影，踏碎陈迹封住墙头的冰层，翻檐没入风雪；碎冰漫空坠落。"
MOMENT = "教习唯一实体的右脚刚踏碎墙头冰层，身体正越过飞檐外沿没入风雪，碎冰向受力方向炸开。"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    production = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if production["source"]["script_sha256"] != SOURCE_SHA:
        raise RuntimeError("script SHA mismatch")
    if not INSTRUCTOR_REF.is_file() or not SCENE_REF.is_file():
        raise FileNotFoundError("identity or scene reference missing")

    OUT.mkdir(parents=True, exist_ok=True)
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    GATE.parent.mkdir(parents=True, exist_ok=True)

    identity = {
        "schema": "qingshan.character_identity_contract.v1",
        "episode": "E28",
        "character_id": "instructor_shadow",
        "canonical_slot": "[[char_instructor]]",
        "status": "PASS",
        "reference_image": rel(INSTRUCTOR_REF),
        "reference_image_sha256": digest(INSTRUCTOR_REF),
        "reference_subject": "right-foreground fully hooded black-clad adult male antagonist",
        "immutable_traits": [
            "adult male",
            "face fully concealed by black hood and mask",
            "ink-black fitted assassin robes without Chenji belt ornament",
            "no exposed topknot, no exposed protagonist face",
            "one physical body; any afterimage is translucent and attached to the same body",
        ],
        "forbidden_identity": [
            "陈迹 face",
            "陈迹 exposed topknot",
            "陈迹 costume",
            "unmasked handsome young protagonist",
        ],
        "selection_evidence": "Existing paid candidate contains a clearly isolated hooded antagonist at right foreground; only that subject is the identity authority.",
    }
    IDENTITY.write_text(json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    prompt = f"""《青山》E28《纸上杀人》，剧本硬锁 SHA-256={SOURCE_SHA}。
内部镜头状态=E28-CW-U10-C1；来源镜头=E28-CW-S04-SH06。锁定剧情原文：{SOURCE_ACTION}
只生成一个连续画面、一个决定性瞬间：{MOMENT}

人物身份锁[[char_instructor]]：画面唯一人物是成年男性密谍司教习。严格参考@图片1右前景那名全身黑衣、黑兜帽、黑蒙面的角色，只继承该角色的身形、兜帽、蒙面和服装；不得继承@图片1中的女性或远处人物。教习全程不露脸，禁止出现陈迹的脸、发髻、腰带纹样或服装。陈迹本人必须在画外，只允许他先前留下的冰层作为道具结果存在。
场景硬锁[[scene_corridor]]：参考@图片2的靖王府偏院屏风回廊与外檐空间，夜，室外连接回廊，无月暴雪；青蓝雪色与冰层银屑，暖光只从远处格窗溢出，禁止巨大月盘。
道具锁[[prop_ice_wall]]：墙头冰层是陈迹此前封路的物理结果，教习右脚与冰层必须有清晰接触点；冰块只能沿脚掌冲击方向向外、向下爆裂。

画面设计：9:16竖屏，2K，写实电影摄影。以大远景定场的王府飞檐空间作纵深基准，但本张单一画面采用低机位中景主体构图，脚掌与冰层接触点达到近景可读精度；教习蒙面侧后脸不可见。右脚接触冰层的瞬间位于视觉中心，身体重心已越过檐外，衣摆、雪粒和碎冰方向共同表现向外逃逸的惯性。一个单一决定性瞬间，不拼入起跳、落地或第二动作。
palette与动机光：无月雪夜青蓝、冰层银白、远窗极少暖橙；黑衣暗部保留织物层次，禁止月光主导或把夜景改成白昼。
动作物理：wind-up已由前态完成；本图只呈现contact=右脚踏中冰层、force_transfer=冰层沿受力点开裂、result=唯一蒙面教习越过飞檐且碎冰漫空坠落。错位残影如出现，只能是紧贴同一蒙面实体的半透明雪光拖影，不能有第二张实体脸或第二具身体。
NEGATIVE_PROMPT：陈迹本人、陈迹脸、陈迹发髻、露脸教习、第二个人、女性、群像、实体分身、双胞胎、两张脸、两具身体、正面英雄肖像、拼贴、分屏、故事板、多个时间状态、月亮、白昼、可读文字、伪文字、字幕、水印、Logo、额外肢体、重复手脚、穿模、悬空冰块。
"""
    PROMPT.write_text(prompt, encoding="utf-8")

    bindings = [
        {
            "role": "character",
            "entity_id": "instructor_shadow",
            "path": rel(INSTRUCTOR_REF),
            "sha256": digest(INSTRUCTOR_REF),
            "qa_status": "PASS",
            "qa_report": rel(IDENTITY),
        },
        {
            "role": "scene",
            "entity_id": "E28-CW-S04-SCREEN-CORRIDOR-FIGHT",
            "path": rel(SCENE_REF),
            "sha256": digest(SCENE_REF),
            "qa_status": "PASS",
            "qa_report": "qa/e28_claude_writer_v1_new_stills_review_20260721/E28_NEW_21_TIER_SCORE_GATE.json",
        },
    ]
    contract = {
        "schema": "qingshan.image_prompt_contract.v2",
        "shot_id": "E28-CW-U10-C1",
        "source_script_sha256": SOURCE_SHA,
        "source_action": SOURCE_ACTION,
        "source_action_sha256": text_digest(SOURCE_ACTION),
        "visible_characters": ["instructor_shadow"],
        "character_binding_mode": "EXPLICIT_VISIBLE_CHARACTERS",
        "reference_bindings": bindings,
        "state_role": "internal_shot_decisive_moment",
        "single_decisive_moment": MOMENT,
        "status": "PASS",
        "failures": [],
    }
    task = {
        "task_key": "E28-CW-U10-C1-STILL-IDENTITY-R1",
        "tool_type": "image_generation",
        "scene_id": "E28-CW-S04-SCREEN-CORRIDOR-FIGHT",
        "shot_id": "E28-CW-U10-C1",
        "beat_id": "E28-CW-U10",
        "prompt_file": rel(PROMPT),
        "prompt_sha256": digest(PROMPT),
        "reference_images": [row["path"] for row in bindings],
        "reference_bindings": bindings,
        "prompt_contract": contract,
        "model": "gpt-image-2-pro",
        "aspect_ratio": "9:16",
        "resolution": "2K",
        "status": "READY_FOR_CHANGED_INPUT_FAILED_ONLY_SUBMIT",
        "source_script_sha256": SOURCE_SHA,
        "supersedes_failed_candidate_sha256": "abf5a6a63e8137f737bc701aed912988d04f73671457a848a3347de5bb158af6",
        "changed_input": [
            "removed Chenji identity reference",
            "replaced contaminated instructor reference with fully hooded antagonist reference",
            "required Chenji offscreen and instructor face concealed",
        ],
    }
    GATE.write_text(json.dumps({
        "schema": "qingshan.e28_u10_c1_identity_repair_preflight.v1",
        "episode": "E28",
        "status": "PASS",
        "source_script_sha256": SOURCE_SHA,
        "failed_only_count": 1,
        "untouched_existing_state_count": 37,
        "original_identity_score": 74.8,
        "original_hard_failure": "canonical_identity_continuity",
        "changed_input_verified": True,
        "identity_contract": rel(IDENTITY),
        "identity_contract_sha256": digest(IDENTITY),
        "policy": "ONE_CHANGED_INPUT_REPAIR_NO_AUTOMATIC_RETRY",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    BATCH.write_text(json.dumps({
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E28",
        "status": "READY_TO_SUBMIT_CHANGED_INPUT_FAILED_ONLY",
        "source_script_sha256": SOURCE_SHA,
        "machine_gate_reports": [rel(GATE)],
        "output_dir": "working_assets/e28_u10_c1_instructor_identity_r1_20260721/candidates",
        "qa_dir": "qa/e28_u10_c1_instructor_identity_r1_20260721",
        "retry_policy": "NO_AUTOMATIC_RETRY_SELECT_BEST_EXISTING_CANDIDATE",
        "tasks": [task],
        "blocked_tasks": [],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "tasks": 1, "batch": rel(BATCH)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
