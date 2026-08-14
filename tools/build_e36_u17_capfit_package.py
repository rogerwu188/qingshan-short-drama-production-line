#!/usr/bin/env python3
"""Build the E36 U17 cap-fit package from the accepted U16B terminal."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
QA = ROOT / "qa/e36_v2_stills_repair_20260729/u17_video_runtime"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


prompt = PROD / "video_prompts_repair_v10/E36-CW-U17-V1.txt"
terminal = ROOT / "working_assets/e36_v2_stills_20260728/terminal_anchors/E36-CW-U16B-TICKET-TEXT-TRIM4P7-V2-TERMINAL-4P58.png"
terminal_qa = ROOT / "qa/e36_v2_stills_repair_20260729/u16_video_runtime/E36_U16B_TERMINAL_ANCHOR_IMAGE_QA_V1.json"
messenger = ROOT / "assets/reference/e25_20260719/E25-FAKE-MESSENGER-IDENTITY-LOCK.png"
chenji = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"

prompt_manifest = read(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V17.json")
for row in prompt_manifest["rows"]:
    if row["unit_id"] == "U17":
        row["prompt_path"] = rel(prompt)
        row["prompt_sha256"] = sha(prompt)
write(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V18.json", prompt_manifest)

anchor_plan = {
    "schema": "qingshan.video_unit_anchor_count_plan.v1",
    "episode": "E36",
    "planned_reference_image_count": 1,
    "units": [{
        "unit_id": "U17",
        "planned_reference_image_count": 1,
        "reference_image_task_keys": ["E36-CW-U16B-TICKET-TEXT-TRIM4P7-V2-TERMINAL-4P58"],
        "keyframe_interpolation_gate": {
            "status": "PASS",
            "anchor_count": 1,
            "checked_adjacent_pairs": 0,
            "candidate_recheck_required": True,
            "physical_interpolation_or_declared_cut": "PASS_SINGLE_CONTINUOUS_HANDOVER_AND_REVEAL",
            "reason": "The accepted U16B terminal fixes both identities, ticket support, visible hand gap, axis and dusk light; one continuous take closes the gap, transfers support and reveals the stamp.",
        },
        "anchor_count_decision": {
            "planned_reference_image_count": 1,
            "reason": "A new paid still would duplicate accepted predecessor authority; the U16B terminal is the exact causal start state.",
            "criteria": {
                "continuous_motion_from_single_start": True,
                "identity_or_space_reanchor": False,
                "prop_ownership_transition": False,
                "non_interpolable_terminal_state": False,
            },
            "anchor_roles": ["accepted_predecessor_terminal_and_start_motion"],
            "action_design_class": "continuous_ticket_handover_then_frost_stamp_reveal_without_reanchor",
        },
    }],
}
write(QA / "E36_U17_ANCHOR_COUNT_PLAN_V2.json", anchor_plan)

causality = {
    "schema": "qingshan.common_sense_causality_plan.v1",
    "episode": "E36",
    "units": [{
        "unit_id": "U17",
        "causality": {
            "applicable": True,
            "purpose": "陈迹接过唯一票根，以冰流显出刘家支银戳记与日期行物证。",
            "intended_effect": "票根先完成有支撑的交接，再由陈迹指腹接触纸边触发霜纹，刘家二字由半显到完整落定。",
            "visible_causality": "陈迹先接触并承重，递信人后松手；陈迹压住纸边后，霜纹才从接触点沿戳记由左向右推进。",
            "viewer_read": "观众能清楚读出交接、触发、半显、完整物证四个连续因果。",
            "preconditions": ["U16B终帧已通过QA", "递信人双手仍支撑票根", "陈迹指尖与票边有可见间隙", "票面尚无可读文字"],
            "mechanism_chain": ["陈迹缩短间隙并夹住纸边", "递信人确认陈迹承重后松手", "陈迹双手稳住票根", "左手指腹触发干燥霜纹", "霜纹由左向右先半显再完整显出刘家"],
            "counterfactual_test": {
                "opponent_can_bypass": False,
                "reasoning": "若递信人先松手、票根悬空、陈迹未接触即生霜或文字一开始已完整，交接与显证因果均失效。",
            },
            "prop_function_status": "PASS",
            "evidence_refs": [rel(terminal_qa), rel(prompt)],
        },
    }],
}
write(QA / "E36_U17_COMMON_SENSE_CAUSALITY_PLAN_V1.json", causality)

period = {
    "schema": "qingshan.anachronism_lock_plan.v1",
    "episode": "E36",
    "period_contract": {
        "status": "PASS",
        "era": "中国古代架空洛城",
        "source_refs": [
            "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md",
            "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S04",
        ],
    },
    "units": [{
        "unit_id": "U17",
        "period_lock": {
            "status": "PASS",
            "reviewed_visible_elements": ["交领古装", "灰旧布衣", "无字木案", "无字药柜", "直棂木窗", "将尽古式烛台", "皱旧钱票根", "朱红古式支银戳记"],
            "detected_anachronisms": [],
            "forbidden_elements": ["现代物件", "现代纸张", "现代文字", "官服", "民国妆发", "背景牌匾", "可读字幕", "水印"],
            "exception_approvals": {"刘家": "canonical evidence text explicitly authorized by E36 script scene 9-4"},
            "evidence_refs": [rel(terminal), rel(prompt)],
        },
    }],
}
write(QA / "E36_U17_PERIOD_LOCK_PLAN_V1.json", period)

config = read(PROD / "E36_U07_EPISODE_SINGLE_UNIT_RETRY_R2.json")
config.update({
    "status": "READY_FOR_SUPERVISOR_PRECHECK",
    "episode_paid_credits_before": 5487,
    "qa_dir": rel(QA),
    "anchor_count_plan_ref": rel(QA / "E36_U17_ANCHOR_COUNT_PLAN_V2.json"),
    "common_sense_causality_plan_ref": rel(QA / "E36_U17_COMMON_SENSE_CAUSALITY_PLAN_V1.json"),
    "period_lock_plan_ref": rel(QA / "E36_U17_PERIOD_LOCK_PLAN_V1.json"),
    "complete_video_prompt_manifest_ref": rel(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V18.json"),
    "base_batch_note": "U17 cap-fit continuation: accepted U16B terminal replaces the failed old U17 still; no new image or audio credits; one continuous supported handover and canonical frost evidence reveal.",
})

task = copy.deepcopy(config["tasks"][0])
task.update({
    "task_key": "E36-CW-U17-VIDEO-V1",
    "source_id": "E36-CW-U17",
    "batch_id": "E36-U17-VIDEO-V1",
    "unit_id": "U17",
    "scene_id": "E36-CW-S04",
    "visual_zone": "E36-U17-TAIPING-CLINIC-TICKET-STAMP-REVEAL",
    "duration_seconds": 5,
    "duration": 5,
    "edit_target_duration_seconds": 5,
    "prompt_path": rel(prompt),
    "prompt_file": rel(prompt),
    "prompt_sha256": sha(prompt),
    "anchor_image_qa_ref": rel(terminal_qa),
    "reference_images": [rel(messenger), rel(chenji), rel(terminal)],
    "reference_image_transport": "inline_base64",
    "reference_image_sequence": [
        {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "messenger", "path": rel(messenger), "sha256": sha(messenger), "identity_reference": True},
        {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(chenji), "sha256": sha(chenji), "identity_reference": True},
        {"asset_label": "@图片3", "role": "ACCEPTED_PREDECESSOR_TERMINAL_AND_START_MOTION_AUTHORITY", "state_id": "E36-CW-U16B-TICKET-TEXT-TRIM4P7-V2-TERMINAL-4P58", "path": rel(terminal), "sha256": sha(terminal), "identity_reference": False},
    ],
    "planned_reference_image_count": 1,
    "state_reference_minimum": 1,
    "still_sequence_only_allowed": True,
    "dialogue": [],
    "dialogue_audio_assets": [],
    "reference_audios": [],
    "reference_audio_asset_ids": [],
    "audio_reference_optional": True,
    "native_dialogue_required": False,
    "visible_speaker_required": False,
    "temporal_visual_qa_required": True,
    "visual_entity_ids": ["messenger", "chenji"],
    "split_gate_ref": None,
    "status": "READY",
    "max_retries": 0,
})
task["duration_plan"] = {
    "policy": "qingshan.shot_generation_duration.v5",
    "duration_seconds": 5,
    "rationale": "Five seconds preserve the complete canonical handover, contact-triggered frost progression and evidence terminal under the 5987 cap-fit plan.",
    "edit_policy": "Preserve the single continuous action and native environmental sound; no dialogue replacement.",
}
task["performance_spec"] = {
    "schema": "qingshan.performance_generation_spec.v2",
    "episode": "E36",
    "unit_id": "U17",
    "duration_seconds": 5,
    "prop_ownership": {"皱旧票根": "0.00秒递信人双手支撑；0.00-1.10秒双人有支撑交接；1.10秒后仅陈迹双手支撑"},
    "motion_beats": [
        {"start_seconds": 0.0, "end_seconds": 1.1, "subject": "陈迹、递信人、皱旧票根", "action": "陈迹右手闭合与票边的间隙并夹住纸边，递信人确认承重后双手退开", "contact_point": "陈迹拇指接触左下纸边、食指接触背面；递信人右手托右上缘、左手托下缘后松开", "direction": "陈迹手由左下向右前方，票根随后向左后方", "end_state": "票根只由陈迹右手稳持，递信人双手退开，票面无可读字", "intent": "完成不掉落的证据交接", "visible_causality": "陈迹先接触承重，递信人后松手", "expression": "陈迹专注，递信人紧张", "viewer_read": "票根归属转移清楚"},
        {"start_seconds": 1.1, "end_seconds": 2.0, "subject": "陈迹、皱旧票根", "action": "陈迹收回票根并以左手指腹压住左边缘，右手托背面", "contact_point": "左手指腹接触纸边，右手掌指接触票背", "direction": "向左下收回半掌并保持票面朝镜头", "end_state": "单张票根稳定，戳记区居中，递信人在后景发抖", "intent": "建立冰流显证的物理触发点", "visible_causality": "先稳定纸张再触发能力", "expression": "陈迹冷静审验", "viewer_read": "接触点和物证区域清楚"},
        {"start_seconds": 2.0, "end_seconds": 4.2, "subject": "陈迹冰流、皱旧票根支银戳记", "action": "干燥霜纹从陈迹左手指腹处沿戳记由左向右爬行，刘家二字先各显左半再完整显形", "contact_point": "霜纹只接触票根戳记区，陈迹指腹持续压住纸边", "direction": "从左向右沿朱红戳记轮廓", "end_state": "刘家二字完整显形，支银日期行墨迹轮廓同时出现", "intent": "把隐藏旧账转成可见物证", "visible_causality": "接触触发后，半显状态先于完整状态", "expression": "陈迹目光收紧", "viewer_read": "刘家旧账证据被揭示"},
        {"start_seconds": 4.2, "end_seconds": 5.0, "subject": "陈迹、票根物证、递信人", "action": "陈迹保持压纸，霜纹停止扩张并凝成薄霜，递信人在后景继续发抖", "contact_point": "陈迹左手指腹持续接触纸边，右手托住票背", "direction": "票面保持朝镜头，暮色沿墙向右缓移", "end_state": "刘家戳记与日期行成为可见物证，票根仍由陈迹双手稳持", "intent": "让证据终态清晰落定", "visible_causality": "能力停止后物证保持可见", "expression": "陈迹冷厉，递信人惊惧", "viewer_read": "证据完整且环境仍有生命"},
    ],
}
task["multimodal_entity_bindings"] = [
    {"entity_id": "messenger", "character_name": "递信人", "registry_id": "CHAR-递信人-E36-古装", "visual_reference": rel(messenger), "visual_reference_sha256": sha(messenger), "identity_image_slot": "@图片1", "voice_reference_asset_id": "3llwjcbwf3w", "dialogue_audio_slots": [], "visible_speaker": False, "lip_sync": False, "prop_owners": {"皱旧票根": "起手双手支撑，确认陈迹承重后松手"}, "ability_owners": []},
    {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(chenji), "visual_reference_sha256": sha(chenji), "identity_image_slot": "@图片2", "dialogue_audio_slots": [], "visible_speaker": False, "lip_sync": False, "prop_owners": {"皱旧票根": "先右手接边，后左手压边、右手托背并持续稳持"}, "ability_owners": ["冰流霜纹显痕辨物"]},
]
task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
task["keyframe_interpolation_gate"] = anchor_plan["units"][0]["keyframe_interpolation_gate"]
task["effect_provenance"] = [{"effect": "冰流霜纹显钱票戳记", "source_type": "CLAUDE_SCRIPT", "source_ref": "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md#9-4"}]
config["tasks"] = [task]
write(PROD / "E36_U17_EPISODE_SINGLE_UNIT_V3.json", config)
print(PROD / "E36_U17_EPISODE_SINGLE_UNIT_V3.json")
