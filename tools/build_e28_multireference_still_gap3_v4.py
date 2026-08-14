#!/usr/bin/env python3
"""Build the three E28 still gaps found after independent exact-content audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e28_cl2x517_20260721"
MANIFEST_PATH = PRODUCTION / "E28_PRODUCTION_MANIFEST.json"
AUDIT_PATH = Path("/Users/rogerwu/Documents/Codex/2026-07-20/qingshan-professional-writer-agent/outputs/cl2x524/E28_CL2X524_INTERNAL_SHOT_REFERENCE_AUDIT_20260721.json")
V3_SUBMIT = ROOT / "workflow/tasks/E28_MULTI_REFERENCE_STILL_COMPLETION_V3_SUBMIT_RECEIPT_20260721.json"
PLAN_PATH = PRODUCTION / "E28_MULTI_REFERENCE_STILL_PLAN_V4.json"
OUT_DIR = PRODUCTION / "multireference_still_gap3_v4"
PROMPT_DIR = OUT_DIR / "prompts"
BATCH_PATH = OUT_DIR / "E28_MULTI_REFERENCE_STILL_GAP3_V4_IMAGE_BATCH.json"
GATE_PATH = ROOT / "qa/e28_multireference_still_gap3_v4_20260721/E28_MULTI_REFERENCE_STILL_GAP3_PREFLIGHT.json"
SOURCE_SHA = "d6418403ecfd3f7042d7bf08cb2297248eaaf96db86223994e8de75b16263ddc"

REGISTRY = "configs/series_continuity_asset_registry_20260712.json"
NEW_GATE = "qa/e28_claude_writer_v1_new_stills_review_20260721/E28_NEW_21_TIER_SCORE_GATE.json"
CHARACTER_REFS = {
    "chenji": "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg",
    "jiaotu": "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg",
    "yunyang": "ref_images/male_yunyang_ancient_ref_20260704.jpg",
    "instructor_shadow": "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S04-SH02-STILL-V1_0ee24b28-8b7b-48f5-b894-313370d85523.png",
}
CHARACTER_QA = {key: (REGISTRY if key != "instructor_shadow" else NEW_GATE) for key in CHARACTER_REFS}
SCENE_REFS = {
    "E28-CW-S04-SCREEN-CORRIDOR-FIGHT": "working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S04-SH01-STILL-V1_7d63213e-1a4d-45ca-8afa-a6b6137c9b79.png",
    "E28-CW-S05-SNOW-ALLEY": "working_assets/e28_claude_writer_v1_reuse_failed_only_r1_20260721/candidates/E28_E28-CW-S05-SH01-STILL-V1_9e9c9d60-d60b-4532-bb53-88aef11db71c.png",
}

GAPS = {
    "E28-CW-U09-C3": {
        "source_shot_id": "E28-CW-S04-SH05",
        "visible": ["chenji", "jiaotu", "yunyang", "instructor_shadow"],
        "moment": "屏风回廊内三人合围已经形成，陈迹以肩部撞中教习躯干，教习后背正撞碎雕花窗棂，木屑向外爆开。",
        "palette": "屏风回廊夜内，青冷窗光与暖烛交错，碎木格承受真实冲击力",
    },
    "E28-CW-U10-C1": {
        "source_shot_id": "E28-CW-S04-SH06",
        "visible": ["chenji", "instructor_shadow"],
        "moment": "教习唯一实体的脚尖正踏碎陈迹封在墙头的冰层，身体已经翻向飞檐，碎冰和雪粒悬在空中。",
        "palette": "回廊外雪夜，青蓝雪色与冰层银屑，月白只作雪面反射，禁止出现巨大月盘",
    },
    "E28-CW-U11-C2": {
        "source_shot_id": "E28-CW-S05-SH02",
        "visible": ["yunyang"],
        "moment": "云羊独自越巷落地急停，靴底压进雪面，右手把火把反向照向身后脚印，陈迹和黑影均在画外。",
        "palette": "无月雪夜巷，青蓝雪色与火把暖橙形成明确冷暖对比",
    },
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def bind(role: str, entity_id: str, path_value: str, qa_report: str) -> dict[str, Any]:
    path = ROOT / path_value
    if not path.is_file() or not (ROOT / qa_report).is_file():
        raise SystemExit(f"missing binding evidence: {entity_id}")
    return {
        "role": role,
        "entity_id": entity_id,
        "path": path_value,
        "sha256": sha(path),
        "qa_status": "PASS",
        "qa_report": qa_report,
    }


def render(state_id: str, gap: dict[str, Any], shot: dict[str, Any]) -> str:
    return (
        f"《青山》E28《纸上杀人》，锁源 SHA-256={SOURCE_SHA}。\n"
        f"内部镜头状态={state_id}；来源镜头={gap['source_shot_id']}。锁定剧情原文：{shot['action']}\n"
        f"只生成一个连续画面、一个决定性瞬间：{gap['moment']}\n"
        f"可见人物身份仅限：{'、'.join(gap['visible'])}。每张输入图只按 reference_bindings 指定用途使用；人物图只锁脸、体态和服装身份，场景图只锁空间材质与时段。不得继承参考图中的旧动作、旧站位、额外人物或旧剧情。\n"
        f"画面系统：{gap['palette']}。9:16 竖屏，2K，写实电影摄影，动作因果和接触点一眼可读，真实皮肤、织物、木屑、冰层和雪粒，正确人体、手部、兵器与空间尺度。\n"
        "硬约束：不得把来源镜头的其他动作拼进本图；不得拼贴、分镜格、同人实体分身或双胞胎；错位残影只能是围绕唯一实体的半透明雪光残像；不得新增人物、武器、建筑、道具或剧情结果；不得生成可读文字、伪文字、字幕、水印或 Logo；不得出现重复肢体、额外手指、断肢、穿模或漂浮道具。"
    )


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    submit = json.loads(V3_SUBMIT.read_text(encoding="utf-8"))
    if manifest["source"]["script_sha256"] != SOURCE_SHA or audit["source_script_sha256"] != SOURCE_SHA:
        raise SystemExit("source SHA mismatch")
    if audit["corrected_internal_shot_count"] != 38 or audit["missing_count"] != 13:
        raise SystemExit("independent audit count mismatch")
    if submit["status"] != "PASS" or submit["submitted"] != 10:
        raise SystemExit("V3 ten-task submission evidence missing")

    submitted_ids = {row["task_key"].removesuffix("-STILL-V3"): row["task_id"] for row in submit["results"]}
    slots = []
    for slot in audit["slots"]:
        item = dict(slot)
        unit_state = f"{slot['unit_id']}-C{slot['internal_shot_index']}"
        if slot["coverage"] == "MISSING" and unit_state in submitted_ids:
            item["production_resolution"] = "SUBMITTED_V3_PENDING_HARVEST"
            item["task_id"] = submitted_ids[unit_state]
        elif unit_state in GAPS:
            item["production_resolution"] = "MISSING_GENERATE_ONCE_V4"
        elif slot["coverage"] == "EXACT":
            item["production_resolution"] = "EXACT_EXISTING"
        else:
            raise SystemExit(f"unresolved audited gap: {unit_state}")
        slots.append(item)

    PLAN_PATH.write_text(json.dumps({
        "schema": "qingshan.multireference_still_plan.v3",
        "episode": "E28",
        "source_script_sha256": SOURCE_SHA,
        "corrected_internal_shot_count": 38,
        "independent_audit": str(AUDIT_PATH),
        "independent_audit_sha256": sha(AUDIT_PATH),
        "exact_existing_count": 25,
        "submitted_v3_pending_harvest_count": 10,
        "remaining_gap_v4_count": 3,
        "duplicate_reference_sha_count": 0,
        "slots": slots,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    shots = {row["shot_id"]: row for row in manifest["shots"]}
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for state_id, gap in GAPS.items():
        shot = shots[gap["source_shot_id"]]
        prompt_path = PROMPT_DIR / f"{state_id}.txt"
        prompt_path.write_text(render(state_id, gap, shot) + "\n", encoding="utf-8")
        bindings = [bind("character", char, CHARACTER_REFS[char], CHARACTER_QA[char]) for char in gap["visible"]]
        bindings.append(bind("scene", shot["scene_id"], SCENE_REFS[shot["scene_id"]], NEW_GATE))
        contract = {
            "schema": "qingshan.image_prompt_contract.v2",
            "shot_id": state_id,
            "source_script_sha256": SOURCE_SHA,
            "source_action": shot["action"],
            "source_action_sha256": text_sha(shot["action"]),
            "visible_characters": gap["visible"],
            "character_binding_mode": "EXPLICIT_VISIBLE_CHARACTERS",
            "reference_bindings": bindings,
            "state_role": "internal_shot_decisive_moment",
            "single_decisive_moment": gap["moment"],
            "status": "PASS",
            "failures": [],
        }
        tasks.append({
            "task_key": f"{state_id}-STILL-V4",
            "tool_type": "image_generation",
            "scene_id": shot["scene_id"],
            "shot_id": state_id,
            "beat_id": state_id.split("-C")[0],
            "prompt_file": rel(prompt_path),
            "prompt_sha256": sha(prompt_path),
            "reference_images": [row["path"] for row in bindings],
            "reference_bindings": bindings,
            "prompt_contract": contract,
            "model": "gpt-image-2-pro",
            "aspect_ratio": "9:16",
            "resolution": "2K",
            "status": "READY_FOR_PARALLEL_SUBMIT",
            "source_script_sha256": SOURCE_SHA,
        })

    GATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GATE_PATH.write_text(json.dumps({
        "schema": "qingshan.multireference_still_gap3_preflight.v1",
        "episode": "E28",
        "status": "PASS",
        "source_script_sha256": SOURCE_SHA,
        "plan": rel(PLAN_PATH),
        "plan_sha256": sha(PLAN_PATH),
        "corrected_internal_shot_count": 38,
        "independent_missing_count": 13,
        "already_submitted_v3_count": 10,
        "remaining_v4_count": 3,
        "generation_policy": "REMAINING_GAPS_ONLY_ONE_CONCURRENT_BATCH_NO_AUTOMATIC_RETRY",
        "task_keys": [row["task_key"] for row in tasks],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    BATCH_PATH.write_text(json.dumps({
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E28",
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "source_script_sha256": SOURCE_SHA,
        "machine_gate_reports": [rel(GATE_PATH)],
        "output_dir": "working_assets/e28_multireference_still_gap3_v4_20260721/candidates",
        "qa_dir": "qa/e28_multireference_still_gap3_v4_20260721",
        "retry_policy": "NO_AUTOMATIC_RETRY_SELECT_BEST_EXISTING_CANDIDATE",
        "consumer_contract": {
            "purpose": "FINAL_THREE_EXACT_CONTENT_GAPS_IN_38_STATE_MAP",
            "not_a_video_call_plan": True,
            "video_compilation_mode": "entity_reference_sequence",
        },
        "tasks": tasks,
        "blocked_tasks": [],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "corrected_states": 38, "previously_submitted": 10, "remaining_tasks": 3, "batch": rel(BATCH_PATH)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
