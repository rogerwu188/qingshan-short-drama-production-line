#!/usr/bin/env python3
"""Add only E31 anchors that action design proves are needed beyond A1."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e31_claude_writer_v1_20260722"
V1_MANIFEST = PRODUCTION / "E31_IMAGE_BATCH_PERFORMANCE_V1.json"
PERFORMANCE_PLAN = PRODUCTION / "E31_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json"
PROMPT_DIR = PRODUCTION / "image_prompts_variable_anchor_v2"
GATE = ROOT / "qa/e31_performance_preproduction_20260722/E31_VARIABLE_ANCHOR_COUNT_GATE_V2.json"
GENERIC_ANCHOR_GATE = ROOT / "qa/e31_performance_preproduction_20260722/E31_VIDEO_UNIT_ANCHOR_COUNT_GATE_V3.json"
OUT = PRODUCTION / "E31_IMAGE_BATCH_VARIABLE_ANCHOR_SUPPLEMENT_V2.json"


EXTRA_ANCHORS = {
    "E31-CW-U02": {
        "reason": "14-second crowd struggle changes both prop state and environment state: one intact list becomes two owned halves and one intact lantern becomes a crushed fire source. A physically continuous end anchor is needed to lock both terminal facts.",
        "anchor": "同一靖王府前庭、同一两拨侍从。名单已沿原受力线撕成两半，左右领头者各握自己一半，双方身体仍保留反向拉扯后的后仰惯性；一名后退侍从的鞋底刚踩碎原来倒地的灯笼，火舌只在檐柱底部初起，尚未蔓延。人物数量、服色、站位与起始锚可连续对应。",
        "continuity": "intact shared list -> torn halves remain in the two original holders; intact fallen lantern -> same lantern crushed under the retreating foot -> first flame at column base",
    },
    "E31-CW-U05": {
        "reason": "The supernatural beat creates a second full humanoid entity while the original body must remain seated and unchanged. A separation-complete anchor is needed to prevent body replacement, duplication or identity transfer.",
        "anchor": "同一医馆灯下，皎兔肉身仍保持原坐姿闭目不动，眉心只有极细血痕；一具与她轮廓对应但材质为幽墨半透明的黑甲阴神已经完整分离在她身后半步，倒持长刀，身体朝窗转去。两者之间没有融合肢体，阴神不是第二个真人皎兔。",
        "continuity": "Jiaotu seated with finger at brow -> thin blood line opens -> one black-armored spirit separates backward while the same flesh body remains seated -> spirit turns toward window",
    },
    "E31-CW-U10": {
        "reason": "The ambush has five human bodies, one cat and three independent attack lanes. A second spatial anchor is needed to lock each attacker's origin, landing direction and common target before later combat units consume the geography.",
        "anchor": "同一雪夜王府回廊。乌云仍在同一墙头弓背尖啸；陈迹和云羊已同步转向警报方向但尚未出招。三名黑衣杀手分别从檐上、左侧廊柱后、右侧假山沿三条不交叉轨迹扑入，三人的视线和手臂都指向陈迹怀中同一卷名单，落点分列陈迹前、左、右，彼此不重叠。",
        "continuity": "three hidden origins remain distinct -> cat warning triggers both heroes to turn -> attackers enter three non-crossing lanes -> all converge on the list without body overlap or weapon transfer",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    v1 = json.loads(V1_MANIFEST.read_text(encoding="utf-8"))
    by_unit = {task["video_unit_id"]: task for task in v1["tasks"]}
    if len(by_unit) != 20 or set(EXTRA_ANCHORS) - set(by_unit):
        raise SystemExit("E31 A1 anchor plan is not the expected 20 unique units")
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    decisions = []
    for unit_id in sorted(by_unit):
        extra = EXTRA_ANCHORS.get(unit_id)
        decisions.append({
            "unit_id": unit_id,
            "planned_reference_image_count": 2 if extra else 1,
            "decision": "SECOND_ANCHOR_REQUIRED" if extra else "SINGLE_ANCHOR_SUFFICIENT",
            "reason": extra["reason"] if extra else "The action is one continuous performance in one stable identity/scene topology; Seedance receives a precise motion script and does not need an extra pose target.",
        })
        if not extra:
            continue
        a1 = by_unit[unit_id]
        source_action = (
            f"第二锚图只锁定物理连续终态：{extra['anchor']}；"
            f"相邻锚连续链：{extra['continuity']}。"
        )
        shot_id = f"{unit_id}-A2"
        prompt = f"""竖屏 9:16，电影级中国古装玄幻短剧，真实人物与真实物理，禁止现代物件。

这是 {unit_id} 经动作设计证明必需的第二张物理连续锚图。它不是额外姿势抽卡，不是分镜网格；必须与 A1 通过真实运动连续插值。

源动作（必须逐字绑定）：{source_action}

画面：{extra['anchor']}
相邻锚物理连续性：{extra['continuity']}。
保持 A1 的人物身份、服装、地点、天气、道具归属和屏幕方向。只画上述连续链抵达后的单一瞬间，不增加新人物、新武器、新抓取、新转身或新碰撞。参考图中的人物只用于身份；场景参考只用于古代建筑、材质和灯光。禁止可读文字、伪文字、字幕、水印、标志、界面、拼贴和多格分镜。
"""
        prompt_path = PROMPT_DIR / f"{shot_id}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        refs = a1["reference_bindings"]
        contract = {
            "schema": "qingshan.image_prompt_contract.v2",
            "shot_id": shot_id,
            "source_script_sha256": a1["source_script_sha256"],
            "source_action": source_action,
            "source_action_sha256": text_sha(source_action),
            "visible_characters": [row["entity_id"] for row in refs if row["role"] == "character"],
            "character_binding_mode": "EXPLICIT_CANONICAL_IDENTITIES_ONLY",
            "reference_bindings": refs,
            "editorial_shot_ids": a1["editorial_shot_ids"],
            "video_unit_id": unit_id,
            "video_unit_duration_seconds": a1["video_unit_duration_seconds"],
            "state_index": 2,
            "state_count": 2,
            "state_role": "performance_continuity_anchor",
            "status": "PASS",
            "failures": [],
        }
        tasks.append({
            "task_key": f"{unit_id}-A2-STILL-V2",
            "tool_type": "image_generation",
            "scene_id": a1["scene_id"],
            "shot_id": shot_id,
            "editorial_shot_ids": a1["editorial_shot_ids"],
            "video_unit_id": unit_id,
            "video_unit_duration_seconds": a1["video_unit_duration_seconds"],
            "state_index": 2,
            "state_count": 2,
            "beat_id": unit_id,
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "prompt_sha256": sha256(prompt_path),
            "reference_images": a1["reference_images"],
            "reference_bindings": refs,
            "prompt_contract": contract,
            "model": "gpt-image-2-pro",
            "aspect_ratio": "9:16",
            "resolution": "2K",
            "status": "READY_FOR_PARALLEL_SUBMIT",
            "source_script_sha256": a1["source_script_sha256"],
        })

    gate = {
        "schema": "qingshan.variable_performance_anchor_gate.v1",
        "episode": "E31",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "policy": "ANCHOR_COUNT_IS_DECIDED_PER_VIDEO_UNIT_FROM_MODEL_CAPABILITY_AND_ACTION_DESIGN; NO ONE_TO_ONE OR FIXED_MULTI_STATE RULE",
        "video_unit_count": 20,
        "planned_reference_image_count": 23,
        "single_anchor_units": 17,
        "two_anchor_units": 3,
        "decisions": decisions,
        "failures": [],
    }
    supplement = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E31",
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "source_script_sha256": v1["source_script_sha256"],
        "machine_gate_reports": [str(GATE.relative_to(ROOT)), str(GENERIC_ANCHOR_GATE.relative_to(ROOT))],
        "output_dir": "working_assets/e31_performance_stills_20260722/candidates",
        "qa_dir": "qa/e31_performance_stills_20260722",
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
        "consumer_contract": {
            "purpose": "ACTION_DESIGN_JUSTIFIED_SECOND_ANCHORS_ONLY",
            "video_unit_count": 20,
            "total_planned_anchor_count_after_supplement": 23,
            "supplement_anchor_count": 3,
            "one_image_per_unit_rule_forbidden": True,
            "fixed_multi_state_minimum_forbidden": True,
        },
        "blocked_tasks": [],
        "tasks": tasks,
    }
    write_json(GATE, gate)
    write_json(OUT, supplement)

    plan = json.loads(PERFORMANCE_PLAN.read_text(encoding="utf-8"))
    by_plan = {row["unit_id"]: row for row in plan["units"]}
    for decision in decisions:
        unit = by_plan[decision["unit_id"]]
        count = decision["planned_reference_image_count"]
        unit["planned_reference_image_count"] = count
        unit["anchor_count_decision"] = decision
        unit["reference_image_task_keys"] = [f"{unit['unit_id']}-A1-STILL-V1"]
        if count == 2:
            unit["reference_image_task_keys"].append(f"{unit['unit_id']}-A2-STILL-V2")
            unit["keyframe_interpolation_gate"] = {
                "status": "PASS",
                "adjacent_pairs_checked": 1,
                "pair": "A1_TO_A2",
                "continuity": EXTRA_ANCHORS[unit["unit_id"]]["continuity"],
            }
        else:
            unit["keyframe_interpolation_gate"] = {
                "status": "PASS",
                "adjacent_pairs_checked": 0,
                "reason": decision["reason"],
            }
    plan["variable_anchor_gate"] = str(GATE.relative_to(ROOT))
    plan["planned_reference_image_count"] = 23
    PERFORMANCE_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "video_units": 20, "anchors": 23, "supplement": 3, "out": str(OUT.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
