#!/usr/bin/env python3
"""Build U06 from the accepted A1 start-motion anchor and exclude the bad A2 state."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
QA = ROOT / "qa/e36_v2_stills_repair_20260729/u06_video_runtime"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


prompt = PROD / "video_prompts_repair_v6/E36-CW-U06.txt"
anchor = ROOT / "working_assets/e36_v2_stills_20260728/repair_v2_candidates/E36_E36-CW-U06-A1-STILL-V2_08e2197e-46e5-4861-b358-b17da87cd630.png"
canonical_jiaotu = ROOT / "working_assets/e32_reference_single_subject_20260723/jiaotu_front_single.jpg"
anchor_qa = QA / "E36_U06_A1_V2_SINGLE_ANCHOR_IMAGE_QA_V1.json"

prompt_manifest = read(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V12.json")
for row in prompt_manifest["rows"]:
    if row["unit_id"] == "U06":
        row["prompt_path"] = rel(prompt)
        row["prompt_sha256"] = sha(prompt)
write(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V13.json", prompt_manifest)

anchor_plan = {
    "schema": "qingshan.video_unit_anchor_count_plan.v1",
    "episode": "E36",
    "planned_reference_image_count": 1,
    "units": [{
        "unit_id": "U06",
        "planned_reference_image_count": 1,
        "reference_image_task_keys": ["E36-CW-U06-A1-STILL-V2"],
        "excluded_reference_image_task_keys": ["E36-CW-U06-A2-STILL-V2"],
        "keyframe_interpolation_gate": {
            "status": "PASS",
            "anchor_count": 1,
            "checked_adjacent_pairs": 0,
            "candidate_recheck_required": True,
            "physical_interpolation_or_declared_cut": "PASS_SINGLE_CONTINUOUS_ACTION",
            "reason": "A1 reliably fixes the blade-at-garment start state; A2 is excluded because its role/contact geometry is contradictory."
        },
        "anchor_count_decision": {
            "planned_reference_image_count": 1,
            "reason": "The remaining interception, rebound and uninjured terminal state are one continuous causal action and are explicitly authored in the video prompt.",
            "criteria": {
                "continuous_motion_from_single_start": True,
                "identity_or_space_reanchor": False,
                "prop_ownership_transition": False,
                "non_interpolable_terminal_state": False
            },
            "anchor_roles": ["accepted_start_motion_only"],
            "action_design_class": "single_anchor_weapon_interception"
        }
    }]
}
write(QA / "E36_U06_ANCHOR_COUNT_PLAN_V1.json", anchor_plan)

causality = {
    "schema": "qingshan.common_sense_causality_plan.v1",
    "episode": "E36",
    "units": [{
        "unit_id": "U06",
        "causality": {
            "applicable": True,
            "purpose": "暗桩劈向真棋，阴神以寒铁完成可见拦截，证明偷换行动进入险败态。",
            "intended_effect": "暗桩刀被反向弹开，真棋仅衣角裂开且身体无伤。",
            "visible_causality": "刀尖先擦破外袍，阴神寒铁随后与刀刃正面交叉碰撞并持续施力，刀才反向弹离。",
            "viewer_read": "观众能辨明攻击者、被保护者、拦截者、接触点、反作用方向和无伤终态。",
            "preconditions": ["A1首帧通过QA", "暗桩刀尖接触真棋外袍边缘", "阴神只入画半身"],
            "mechanism_chain": ["刀尖擦裂衣角", "阴神沿反方向切入", "寒铁与刀刃金属接触", "暗桩刀反弹", "真棋退半步且无伤"],
            "counterfactual_test": {
                "opponent_can_bypass": False,
                "reasoning": "若没有清楚的兵器接触和反向施力，刀的弹离与真棋无伤便无可见因果。"
            },
            "prop_function_status": "PASS",
            "evidence_refs": [rel(anchor_qa), rel(prompt)]
        }
    }]
}
write(QA / "E36_U06_COMMON_SENSE_CAUSALITY_PLAN_V1.json", causality)

period = {
    "schema": "qingshan.anachronism_lock_plan.v1",
    "episode": "E36",
    "period_contract": {
        "status": "PASS",
        "era": "中国古代架空洛城",
        "source_refs": [
            "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md",
            "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S01"
        ]
    },
    "units": [{
        "unit_id": "U06",
        "period_lock": {
            "status": "PASS",
            "reviewed_visible_elements": ["古式法场", "交领布衣", "黑甲", "冷兵器", "铜锣", "挑担货郎", "斩字旗"],
            "detected_anachronisms": [],
            "forbidden_elements": ["现代物件", "现代文字", "民国灯具", "枪械", "字幕", "水印", "新增可读文字"],
            "exception_approvals": {"斩字旗": "canonical_scene_authorized"},
            "evidence_refs": [rel(anchor), rel(prompt)]
        }
    }]
}
write(QA / "E36_U06_PERIOD_LOCK_PLAN_V1.json", period)

config = read(PROD / "E36_U16B_EPISODE_SINGLE_UNIT_V1.json")
config.update({
    "status": "READY_FOR_SUPERVISOR_PRECHECK",
    "episode_paid_credits_before": 5465,
    "qa_dir": "qa/e36_v2_stills_repair_20260729/u06_video_runtime",
    "anchor_count_plan_ref": rel(QA / "E36_U06_ANCHOR_COUNT_PLAN_V1.json"),
    "common_sense_causality_plan_ref": rel(QA / "E36_U06_COMMON_SENSE_CAUSALITY_PLAN_V1.json"),
    "period_lock_plan_ref": rel(QA / "E36_U06_PERIOD_LOCK_PLAN_V1.json"),
    "complete_video_prompt_manifest_ref": rel(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V13.json")
})
config.pop("dialogue_prompt_gate_ref", None)

task = copy.deepcopy(config["tasks"][0])
task.update({
    "status": "READY",
    "task_key": "E36-CW-U06-VIDEO-V1",
    "source_id": "E36-CW-U06",
    "batch_id": "E36-U06-VIDEO-V1",
    "unit_id": "U06",
    "scene_id": "E36-CW-S01",
    "visual_zone": "E36-U06-WEST-MARKET-EXECUTION-GROUND",
    "duration": 5,
    "duration_seconds": 5,
    "edit_target_duration_seconds": 5,
    "prompt_path": rel(prompt),
    "prompt_file": rel(prompt),
    "prompt_sha256": sha(prompt),
    "anchor_image_qa_ref": rel(anchor_qa),
    "split_gate_ref": None,
    "reference_images": [rel(canonical_jiaotu), rel(anchor)],
    "reference_image_sequence": [{
        "asset_label": "@图片1",
        "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE",
        "entity_id": "jiaotu",
        "path": rel(canonical_jiaotu),
        "sha256": sha(canonical_jiaotu),
        "identity_reference": True
    }, {
        "asset_label": "@图片2",
        "role": "ACCEPTED_START_MOTION_AND_LAYOUT_AUTHORITY",
        "state_id": "E36-CW-U06-A1-STILL-V2",
        "path": rel(anchor),
        "sha256": sha(anchor),
        "identity_reference": False
    }],
    "planned_reference_image_count": 1,
    "state_reference_minimum": 1,
    "dialogue": [],
    "dialogue_audio_assets": [],
    "reference_audios": [],
    "reference_audio_asset_ids": [],
    "native_dialogue_required": False,
    "visible_speaker_required": False,
    "audio_reference_optional": True,
    "visual_entity_ids": ["jiaotu"],
    "multimodal_entity_bindings": [{
        "entity_id": "jiaotu",
        "character_name": "皎兔",
        "registry_id": "CHAR-皎兔-古装",
        "visual_reference": rel(canonical_jiaotu),
        "visual_reference_sha256": sha(canonical_jiaotu),
        "identity_image_slot": "@图片1",
        "voice_reference_asset_id": "x2ucerh9xoo",
        "dialogue_audio_slots": [],
        "visible_speaker": False,
        "lip_sync": False,
        "prop_owners": {"被保护对象": "真棋"},
        "ability_owners": ["阴神拦刀"]
    }],
    "max_retries": 0
})
task["duration_plan"] = {
    "policy": "qingshan.shot_generation_duration.v5",
    "duration_seconds": 5,
    "rationale": "Five seconds cover garment graze, visible weapon interception, reverse rebound and uninjured terminal state at natural speed.",
    "edit_policy": "Preserve causal action and native environmental audio; no dialogue replacement."
}
task["performance_spec"] = {
    "schema": "qingshan.performance_generation_spec.v2",
    "episode": "E36",
    "unit_id": "U06",
    "duration_seconds": 5,
    "prop_ownership": {"暗桩刀": "暗桩双手持有", "阴神寒铁": "阴神右手持有", "裂口": "仅在真棋外袍衣角"},
    "motion_beats": [{
        "start_seconds": 0.0,
        "end_seconds": 5.0,
        "subject": "暗桩、阴神、真棋、皎兔",
        "action": "暗桩刀尖擦裂真棋衣角，阴神从左后方切入以寒铁正面拦刀并反向推开，皎兔带真棋退半步",
        "contact_point": "先为暗桩刀尖与真棋外袍边缘，再为暗桩刀刃与阴神寒铁的清楚金属交叉点",
        "direction": "攻击由左向右下，拦击由左下向右上并把刀反推回左后方",
        "end_state": "暗桩刀远离真棋，阴神横挡其间，真棋只有衣角裂开且身体无伤",
        "intent": "在不伤真棋的前提下阻断暗桩袭击",
        "visible_causality": "先接触再反弹，寒铁持续施力后暗桩刀才离开",
        "expression": "真棋惊而未伤，皎兔警觉护人，暗桩受震失衡",
        "viewer_read": "偷换行动受阻并进入险败态"
    }]
}
task["keyframe_interpolation_gate"] = anchor_plan["units"][0]["keyframe_interpolation_gate"]
task["effect_provenance"] = [{
    "effect": "阴神",
    "source_type": "CLAUDE_SCRIPT",
    "source_ref": "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md#9-1"
}]
task["multimodal_binding_sha256"] = hashlib.sha256(
    json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()
config["tasks"] = [task]
write(PROD / "E36_U06_EPISODE_SINGLE_UNIT_V1.json", config)
print(PROD / "E36_U06_EPISODE_SINGLE_UNIT_V1.json")
