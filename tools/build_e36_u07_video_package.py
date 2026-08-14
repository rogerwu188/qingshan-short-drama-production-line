#!/usr/bin/env python3
"""Build U07 video package from the accepted V4 action anchor."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
QA = ROOT / "qa/e36_v2_stills_repair_20260729/u07_video_runtime"

def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))

prompt = PROD / "video_prompts_repair_v8/E36-CW-U07.txt"
anchor = ROOT / "working_assets/e36_v2_stills_20260728/u07_candidates_v4/E36-CW-U07-A4-STILL-V4_2047b9ac-5635-410a-b5c3-b29a196eaf67.png"
messenger = ROOT / "assets/reference/e25_20260719/E25-FAKE-MESSENGER-IDENTITY-LOCK.png"
jiaotu = ROOT / "working_assets/e32_reference_single_subject_20260723/jiaotu_front_single.jpg"

image_qa = {
    "schema": "qingshan.video_unit_image_qa.v1", "episode": "E36", "video_unit_id": "E36-CW-U07", "task_key": "E36-CW-U07-A4-STILL-V4", "source_cl2x": "CL2X-772", "source_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6", "result": "PASS", "hard_blocked": False, "video_submission": "RELEASED_FOR_U07", "image": {"path": str(anchor), "sha256": sha(anchor)}, "gate_results": {"media_integrity": "PASS", "aspect_ratio": "PASS", "period_continuity": "PASS", "first_frame_motion_state": "PASS", "ambient_life": "PASS", "role_separation": "PASS", "adult_male_hidden_stake": "PASS", "paper_decoy_no_text": "PASS", "collar_contact_clarity": "PASS", "effect_semantics_dry_rime_not_water": "PASS", "background_text_safety": "PASS"}, "notes": ["暗桩明确为成年男性，双足由贴地粉白冷青霜壳固定；无悬空水滴或液态水面。", "纸替保持倾斜进行态且无字，皎兔五指与递信人后领接触清楚，三人身份与空间分离。"], "blocked_by": "NONE"
}
write(QA / "E36_U07_A4_IMAGE_QA_PASS_V4.json", image_qa)

manifest = read(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V14.json")
for row in manifest["rows"]:
    if row["unit_id"] == "U07":
        row["prompt_path"] = rel(prompt)
        row["prompt_sha256"] = sha(prompt)
write(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V15.json", manifest)

anchor_plan = {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 1, "units": [{"unit_id": "U07", "planned_reference_image_count": 1, "reference_image_task_keys": ["E36-CW-U07-A4-STILL-V4"], "excluded_reference_image_task_keys": ["E36-CW-U07-A1-STILL-V2", "E36-CW-U07-A2-STILL-V2", "E36-CW-U07-A3-STILL-V3"], "keyframe_interpolation_gate": {"status": "PASS", "anchor_count": 1, "checked_adjacent_pairs": 0, "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS_SINGLE_CONTINUOUS_ACTION", "reason": "Accepted V4 fixes the start geometry; all subsequent beats form one continuous five-second extraction."}, "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "No identity, prop ownership or space reanchor occurs after the accepted start state.", "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False}, "anchor_roles": ["accepted_start_motion_only"], "action_design_class": "single_anchor_causal_extraction"}}]}
write(QA / "E36_U07_ANCHOR_COUNT_PLAN_V1.json", anchor_plan)

causality = {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U07", "causality": {"applicable": True, "purpose": "固定暗桩、以纸替占据刀线并把真棋带离。", "intended_effect": "暗桩无法追击，纸替占位，真棋安全脱离刀线。", "visible_causality": "暗桩抬脚先受霜壳阻断；纸替再落入刀线；皎兔持续扣住后领把递信人带出。", "viewer_read": "观众能辨明被固定者、替位物、救人者、接触点、移动方向和终态。", "preconditions": ["V4首帧通过QA", "暗桩双足霜壳接触清楚", "皎兔五指扣住真棋后领"], "mechanism_chain": ["霜壳收紧", "暗桩抬脚失败", "纸替落位", "皎兔抓领外掠", "真棋脱离刀线"], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若霜壳未阻脚或后领接触中断，暗桩可追击且真棋位移无可见因果。"}, "prop_function_status": "PASS", "evidence_refs": [rel(QA / "E36_U07_A4_IMAGE_QA_PASS_V4.json"), rel(prompt)]}}]}
write(QA / "E36_U07_COMMON_SENSE_CAUSALITY_PLAN_V1.json", causality)

period = {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S01"]}, "units": [{"unit_id": "U07", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["古式法场", "交领布衣", "黑色古装", "纸扎与竹篾", "木刑台", "古式人群"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代文字", "民国灯具", "枪械", "字幕", "水印", "新增可读文字"], "exception_approvals": {}, "evidence_refs": [rel(anchor), rel(prompt)]}}]}
write(QA / "E36_U07_PERIOD_LOCK_PLAN_V1.json", period)

config = read(PROD / "E36_U16B_EPISODE_SINGLE_UNIT_V1.json")
config.update({"status": "READY_FOR_SUPERVISOR_PRECHECK", "episode_paid_credits_before": 5487, "qa_dir": rel(QA), "anchor_count_plan_ref": rel(QA / "E36_U07_ANCHOR_COUNT_PLAN_V1.json"), "common_sense_causality_plan_ref": rel(QA / "E36_U07_COMMON_SENSE_CAUSALITY_PLAN_V1.json"), "period_lock_plan_ref": rel(QA / "E36_U07_PERIOD_LOCK_PLAN_V1.json"), "complete_video_prompt_manifest_ref": rel(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V15.json")})
config.pop("dialogue_prompt_gate_ref", None)
task = copy.deepcopy(config["tasks"][0])
task.update({"status": "READY", "task_key": "E36-CW-U07-VIDEO-V1", "source_id": "E36-CW-U07", "batch_id": "E36-U07-VIDEO-V1", "unit_id": "U07", "scene_id": "E36-CW-S01", "visual_zone": "E36-U07-WEST-MARKET-EXECUTION-GROUND", "duration": 5, "duration_seconds": 5, "edit_target_duration_seconds": 5, "prompt_path": rel(prompt), "prompt_file": rel(prompt), "prompt_sha256": sha(prompt), "anchor_image_qa_ref": rel(QA / "E36_U07_A4_IMAGE_QA_PASS_V4.json"), "split_gate_ref": None, "reference_images": [rel(messenger), rel(jiaotu), rel(anchor)], "reference_image_sequence": [{"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "messenger", "path": rel(messenger), "sha256": sha(messenger), "identity_reference": True}, {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "jiaotu", "path": rel(jiaotu), "sha256": sha(jiaotu), "identity_reference": True}, {"asset_label": "@图片3", "role": "ACCEPTED_START_MOTION_AND_LAYOUT_AUTHORITY", "state_id": "E36-CW-U07-A4-STILL-V4", "path": rel(anchor), "sha256": sha(anchor), "identity_reference": False}], "planned_reference_image_count": 1, "state_reference_minimum": 1, "dialogue": [], "dialogue_audio_assets": [], "reference_audios": [], "reference_audio_asset_ids": [], "native_dialogue_required": False, "visible_speaker_required": False, "audio_reference_optional": True, "visual_entity_ids": ["messenger", "jiaotu"], "multimodal_entity_bindings": [{"entity_id": "messenger", "character_name": "递信人", "registry_id": "CHAR-递信人-E36-古装", "visual_reference": rel(messenger), "visual_reference_sha256": sha(messenger), "identity_image_slot": "@图片1", "voice_reference_asset_id": "3llwjcbwf3w", "dialogue_audio_slots": [], "visible_speaker": False, "lip_sync": False, "prop_owners": {"后领": "皎兔右手持续扣住"}, "ability_owners": []}, {"entity_id": "jiaotu", "character_name": "皎兔", "registry_id": "CHAR-皎兔-古装", "visual_reference": rel(jiaotu), "visual_reference_sha256": sha(jiaotu), "identity_image_slot": "@图片2", "voice_reference_asset_id": "x2ucerh9xoo", "dialogue_audio_slots": [], "visible_speaker": False, "lip_sync": False, "prop_owners": {"递信人后领": "右手五指持续扣住并牵引"}, "ability_owners": ["阴神偷梁换柱"]}], "max_retries": 0})
task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 5, "rationale": "Five seconds cover frost lock, decoy placement and collar-led extraction at natural speed.", "edit_policy": "Preserve causal action and native environmental audio; no dialogue replacement."}
task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "episode": "E36", "unit_id": "U07", "duration_seconds": 5, "prop_ownership": {"云羊纸替": "中央刀线占位且全程无字", "递信人后领": "皎兔右手五指持续接触", "暗桩脚下霜壳": "只锁住暗桩双足与木台"}, "motion_beats": [{"start_seconds": 0.0, "end_seconds": 1.4, "subject": "景朝暗桩、陈迹冰流", "action": "暗桩抬左脚受阻，霜壳收紧迫使左脚落回", "contact_point": "干燥霜壳贴住暗桩双鞋、脚踝与木台", "direction": "沿木台向暗桩双足内收", "end_state": "暗桩双足固定且上身前倾", "intent": "阻断追击", "visible_causality": "先抬脚再受阻", "expression": "暗桩惊怒", "viewer_read": "追兵被固定"}, {"start_seconds": 1.4, "end_seconds": 3.1, "subject": "纸替、皎兔、递信人", "action": "无字纸替倾斜落入刀线，皎兔扣领把递信人向右后方带离", "contact_point": "纸替下缘擦木台；皎兔五指捏住后领", "direction": "纸替向中央下落，皎兔与递信人向右后方", "end_state": "纸替占位，递信人越过纸替右缘一半", "intent": "完成替位并开始撤离", "visible_causality": "纸替落位与抓领牵引同步", "expression": "皎兔专注，递信人惊慌", "viewer_read": "真假位置开始交换"}, {"start_seconds": 3.1, "end_seconds": 5.0, "subject": "皎兔、递信人、纸替、暗桩", "action": "皎兔持续抓领把递信人带入纸影死角", "contact_point": "皎兔手指持续接触后领；暗桩双足持续接触霜壳", "direction": "向右后方并略向台下", "end_state": "暗桩固定、纸替占刀线、递信人脱离刀线并被纸影遮去大半", "intent": "完成偷梁换柱", "visible_causality": "抓领牵引不中断", "expression": "皎兔警觉，递信人恢复重心", "viewer_read": "换人成功"}]}
task["keyframe_interpolation_gate"] = anchor_plan["units"][0]["keyframe_interpolation_gate"]
task["effect_provenance"] = [{"effect": "冰流锁足", "source_type": "CLAUDE_SCRIPT", "source_ref": "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md#9-1"}, {"effect": "云羊纸替", "source_type": "CLAUDE_SCRIPT", "source_ref": "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md#9-1"}, {"effect": "皎兔阴神偷梁换柱", "source_type": "CLAUDE_SCRIPT", "source_ref": "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md#9-1"}]
task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
config["tasks"] = [task]
write(PROD / "E36_U07_EPISODE_SINGLE_UNIT_V1.json", config)
print(PROD / "E36_U07_EPISODE_SINGLE_UNIT_V1.json")
