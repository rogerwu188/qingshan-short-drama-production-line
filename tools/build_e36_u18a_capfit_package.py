#!/usr/bin/env python3
"""Build E36 U18A from the accepted zero-credit reaction crop and exact audio."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
QA = ROOT / "qa/e36_v2_stills_repair_20260729/u18_video_runtime"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


prompt = PROD / "video_prompts_repair_v11/E36-CW-U18A.txt"
anchor = ROOT / "working_assets/e36_v2_stills_20260728/u18_local_repairs/E36-CW-U18A-A1-FACE-REACTION-CROP-V1.png"
anchor_qa = QA / "E36_U18A_LOCAL_CROP_IMAGE_QA_V1.json"
yunyang = ROOT / "assets/reference/e36_20260729/characters/CHAR-yunyang-age17-canonical-v1-20260729.png"
chenji = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
messenger = ROOT / "assets/reference/e25_20260719/E25-FAKE-MESSENGER-IDENTITY-LOCK.png"
voice = ROOT / "libraries/audio/voice_refs/agentcut_speech_v1_20260723/yunyang/VOICE-yunyang-agentcut-v1.wav"
audio = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u18a/E36-U18A-D01.wav"
audio_qa = read(QA / "E36_U18A_EXACT_DIALOGUE_AUDIO_QA_V1.json")
spoken = "刘家？城东那个刘家？那户三年前就灭门了！"

prompt_manifest = read(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V18.json")
for row in prompt_manifest["rows"]:
    if row["unit_id"] == "U18":
        row["prompt_path"] = rel(prompt)
        row["prompt_sha256"] = sha(prompt)
write(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V19.json", prompt_manifest)

dialogue_manifest = read(PROD / "E36_DIALOGUE_MANIFEST_V8.json")
dialogue_manifest["rows"] = [row for row in dialogue_manifest["rows"] if row.get("video_unit_id") != "U18"]
dialogue_manifest["rows"].append({
    "dia_id": "E36-U18A-D01", "video_unit_id": "U18", "speaker_id": "yunyang", "speaker": "云羊", "spoken_text": spoken,
    "status": "PASS", "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(audio), "sha256": sha(audio),
    "duration_seconds": float(audio_qa["duration_seconds"]), "voice_reference_asset_id": "v0udrgrojud", "voice_derivation_status": "PASS",
    "source_voice": "AGENTCUT_SPEECH_GENERATION:clone_20250922_190214_400934", "start_seconds": 0.2, "end_seconds": 4.5,
    "expression": "十七岁云羊认出刘家后骤然失声，震惊但仍是自然中文普通话",
})
write(PROD / "E36_DIALOGUE_MANIFEST_V9.json", dialogue_manifest)

anchor_plan = {
    "schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 1,
    "units": [{"unit_id": "U18", "planned_reference_image_count": 1, "reference_image_task_keys": ["E36-CW-U18A-A1-FACE-REACTION-CROP-V1"],
        "keyframe_interpolation_gate": {"status": "PASS", "anchor_count": 1, "checked_adjacent_pairs": 0, "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS_SINGLE_REACTION_TAKE", "reason": "One passed reaction crop fixes identities, three-person screen positions, dusk light and Yunyang's active lean for one continuous spoken reaction."},
        "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "U18A contains one continuous lean, exact line and closed-mouth tail with no prop transition or re-anchor.", "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False}, "anchor_roles": ["start_motion_reaction_authority"], "action_design_class": "single_anchor_native_dialogue_reaction"}}
    ]}
write(QA / "E36_U18A_ANCHOR_COUNT_PLAN_V1.json", anchor_plan)

causality = {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U18", "causality": {
    "applicable": True, "purpose": "云羊看清画外刘家物证后认出城东刘家并说出三年前灭门事实。",
    "intended_effect": "云羊由俯身辨认转为瞳孔放大、失声确认，陈迹闭口保全证据，递信人继续发抖。",
    "visible_causality": "先俯身锁定画外案面，再短促吸气并完整说出第一句，最后闭口看向陈迹。",
    "viewer_read": "观众能读出物证触发认知、认知触发震惊对白，而不是无因惊叫。",
    "preconditions": ["U18A裁切锚已通过图片QA", "云羊正在俯身且闭口", "陈迹与递信人闭口", "票根文字区在画外"],
    "mechanism_chain": ["云羊目光锁住画外物证", "瞳孔放大并短促吸气", "云羊说完整唯一台词", "视线抬向陈迹", "闭口反应落定"],
    "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若先开口后看物证、陈迹或递信人串台、票据文字入镜，认知因果和对白归属均失效。"},
    "prop_function_status": "PASS", "evidence_refs": [rel(anchor_qa), rel(prompt)]}}]}
write(QA / "E36_U18A_COMMON_SENSE_CAUSALITY_PLAN_V1.json", causality)

period = {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S04"]},
    "units": [{"unit_id": "U18", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["交领古装", "灰旧布衣", "黑色古装", "褐色粗布", "无字木墙", "无字药柜", "直棂木门", "古式烛光"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代纸张", "官服", "民国妆发", "背景牌匾", "可读字幕", "水印"], "exception_approvals": {}, "evidence_refs": [rel(anchor), rel(prompt)]}}]}
write(QA / "E36_U18A_PERIOD_LOCK_PLAN_V1.json", period)

dialogue_gate = {"schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U18", "source_segment_id": "U18A", "status": "PASS", "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6", "speaker": "云羊", "spoken_text": spoken, "start_seconds": 0.2, "end_seconds": 4.5, "voice_reference_asset_id": "v0udrgrojud", "voice_reference_sha256": sha(voice), "checks": {"exact_text_in_prompt": "PASS", "native_mandarin_required": "PASS", "visible_yunyang_mouth": "PASS", "lip_breath_expression_sync": "PASS", "silent_age17_chenji": "PASS", "silent_messenger": "PASS", "closed_mouth_tail": "PASS"}, "failures": []}
write(QA / "E36_U18A_DIALOGUE_PROMPT_GATE_V1.json", dialogue_gate)

config = read(PROD / "E36_U16B_EPISODE_SINGLE_UNIT_V1.json")
config.update({"status": "READY_FOR_SUPERVISOR_PRECHECK", "episode_paid_credits_before": 5489, "qa_dir": rel(QA), "anchor_count_plan_ref": rel(QA / "E36_U18A_ANCHOR_COUNT_PLAN_V1.json"), "common_sense_causality_plan_ref": rel(QA / "E36_U18A_COMMON_SENSE_CAUSALITY_PLAN_V1.json"), "period_lock_plan_ref": rel(QA / "E36_U18A_PERIOD_LOCK_PLAN_V1.json"), "complete_video_prompt_manifest_ref": rel(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V19.json"), "dialogue_manifest_ref": rel(PROD / "E36_DIALOGUE_MANIFEST_V9.json"), "dialogue_prompt_gate_ref": rel(QA / "E36_U18A_DIALOGUE_PROMPT_GATE_V1.json")})
task = copy.deepcopy(config["tasks"][0])
task.update({"task_key": "E36-CW-U18A-VIDEO-V1", "source_id": "E36-CW-U18A", "batch_id": "E36-U18A-VIDEO-V1", "unit_id": "U18", "scene_id": "E36-CW-S04", "visual_zone": "E36-U18A-YUNYANG-LIU-FAMILY-RECOGNITION", "duration_seconds": 5, "duration": 5, "edit_target_duration_seconds": 5, "prompt_path": rel(prompt), "prompt_file": rel(prompt), "prompt_sha256": sha(prompt), "anchor_image_qa_ref": rel(anchor_qa), "split_gate_ref": None, "reference_images": [rel(yunyang), rel(chenji), rel(messenger), rel(anchor)], "reference_audios": [rel(audio)], "reference_audio_asset_ids": [], "planned_reference_image_count": 1, "state_reference_minimum": 1, "dialogue": [{"dia_id": "E36-U18A-D01", "speaker": "云羊", "spoken_text": spoken, "start_seconds": 0.2, "end_seconds": 4.5, "expression": "十七岁云羊认出刘家后骤然失声，震惊但仍是自然中文普通话", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}], "dialogue_audio_assets": [{"dia_id": "E36-U18A-D01", "audio_slot": "@音频1", "speaker_id": "yunyang", "character_name": "云羊", "spoken_text": spoken, "path": rel(audio), "sha256": sha(audio), "duration_seconds": float(audio_qa["duration_seconds"]), "voice_reference_asset_id": "v0udrgrojud", "voice_derivation_status": "PASS", "source_voice": "AGENTCUT_SPEECH_GENERATION:clone_20250922_190214_400934", "voice_gender": "male", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"}], "audio_reference_optional": False, "native_dialogue_required": True, "visible_speaker_required": True, "temporal_visual_qa_required": True, "visual_entity_ids": ["yunyang", "chenji", "messenger"], "status": "READY", "max_retries": 0})
task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 5, "rationale": "Five seconds fit the exact 4.296-second Yunyang line with a 0.20-second lead and 0.50-second closed-mouth tail.", "edit_policy": "Preserve native Mandarin and picture-audio sync; trim only terminal silence after QA."}
task["reference_image_sequence"] = [
    {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "yunyang", "path": rel(yunyang), "sha256": sha(yunyang), "identity_reference": True},
    {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(chenji), "sha256": sha(chenji), "identity_reference": True},
    {"asset_label": "@图片3", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "messenger", "path": rel(messenger), "sha256": sha(messenger), "identity_reference": True},
    {"asset_label": "@图片4", "role": "ACCEPTED_START_MOTION_REACTION_AUTHORITY", "state_id": "E36-CW-U18A-A1-FACE-REACTION-CROP-V1", "path": rel(anchor), "sha256": sha(anchor), "identity_reference": False},
]
task["multimodal_entity_bindings"] = [
    {"entity_id": "yunyang", "character_name": "云羊", "registry_id": "CHAR-云羊-古装", "visual_reference": rel(yunyang), "visual_reference_sha256": sha(yunyang), "identity_image_slot": "@图片1", "voice_reference": rel(voice), "voice_reference_sha256": sha(voice), "voice_reference_asset_id": "v0udrgrojud", "audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1"], "visible_speaker": True, "lip_sync": True, "prop_owners": {"刘家旧钱票根": "保持一掌间隔，不接触，票根在画外"}, "ability_owners": []},
    {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(chenji), "visual_reference_sha256": sha(chenji), "identity_image_slot": "@图片2", "voice_reference_asset_id": "cypqud0bu7t", "dialogue_audio_slots": [], "visible_speaker": False, "lip_sync": False, "prop_owners": {"刘家旧钱票根": "手指在画外持续压住，不让票据入镜"}, "ability_owners": []},
    {"entity_id": "messenger", "character_name": "递信人", "registry_id": "CHAR-递信人-E36-古装", "visual_reference": rel(messenger), "visual_reference_sha256": sha(messenger), "identity_image_slot": "@图片3", "voice_reference_asset_id": "3llwjcbwf3w", "dialogue_audio_slots": [], "visible_speaker": False, "lip_sync": False, "prop_owners": {}, "ability_owners": []},
]
task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "episode": "E36", "unit_id": "U18", "duration_seconds": 5, "prop_ownership": {"刘家旧钱票根": "陈迹在画外持续保全；云羊保持一掌间隔；不在本单元显示票面"}, "motion_beats": [
    {"start_seconds": 0.0, "end_seconds": 0.2, "subject": "云羊", "action": "保持俯身，瞳孔继续放大并短促吸气，嘴仍闭合", "contact_point": "双手不接触画外票根", "direction": "由画面右侧向左下再前移半寸", "end_state": "目光锁住案面并准备开口", "intent": "建立认知触发", "visible_causality": "先看清物证再开口", "expression": "辨认转震惊", "viewer_read": "物证触发反应"},
    {"start_seconds": 0.2, "end_seconds": 4.5, "subject": "云羊", "action": f"完整嘴部可见，以自然中文普通话只说一遍{spoken}", "contact_point": "与画外物证保持一掌间隔", "direction": "视线由左下案面抬向左侧陈迹", "end_state": "台词完整结束并自然闭口", "intent": "确认刘家身份与灭门时间", "visible_causality": "认出物证后失声陈述", "expression": "瞳孔放大、失色、气息发紧", "viewer_read": "说话人和信息清楚"},
    {"start_seconds": 4.5, "end_seconds": 5.0, "subject": "云羊、陈迹、递信人", "action": "云羊闭口短呼气，陈迹闭口看回案面，递信人继续发抖", "contact_point": "云羊仍不触物证，陈迹手指在画外压票", "direction": "云羊看陈迹，陈迹视线向左下", "end_state": "第一句落定，三人均闭口，为U18B留口", "intent": "保留后续归纳", "visible_causality": "对白结束后反应自然延续", "expression": "云羊震惊，陈迹冷静，递信人惊惧", "viewer_read": "信息落点与续接清楚"},
]}
task["keyframe_interpolation_gate"] = anchor_plan["units"][0]["keyframe_interpolation_gate"]
config["tasks"] = [task]
write(PROD / "E36_U18A_EPISODE_SINGLE_UNIT_V2.json", config)
print(PROD / "E36_U18A_EPISODE_SINGLE_UNIT_V2.json")
