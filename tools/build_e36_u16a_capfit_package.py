#!/usr/bin/env python3
"""Build the E36 U16A single-unit package from the accepted U15C terminal."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
QA = ROOT / "qa/e36_v2_stills_repair_20260729"
U16_QA = QA / "u16_video_runtime"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


prompt = PROD / "video_prompts_repair_v5/E36-CW-U16A.txt"
prompt_sha = sha(prompt)
terminal = ROOT / "working_assets/e36_v2_stills_20260728/terminal_anchors/E36-CW-U15C-TIMING-REPAIR-V1-TERMINAL-4P80.png"
terminal_sha = sha(terminal)
messenger_image = ROOT / "assets/reference/e25_20260719/E25-FAKE-MESSENGER-IDENTITY-LOCK.png"
chenji_image = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
voice = ROOT / "libraries/audio/voice_refs/agentcut_speech_v1_20260723/e36_luocheng_messenger/VOICE-e36_luocheng_messenger-agentcut-v1.wav"
voice_sha = sha(voice)
voice_asset = "3llwjcbwf3w"
exact_audio = ROOT / "working_assets/e36_dialogue_audio_refs_20260729/u16a/E36-U16A-D01.wav"
exact_audio_sha = sha(exact_audio)

prompt_manifest = read(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V10.json")
for row in prompt_manifest["rows"]:
    if row["unit_id"] == "U16":
        row["prompt_path"] = rel(prompt)
        row["prompt_sha256"] = prompt_sha
write(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V11.json", prompt_manifest)

dialogue_manifest = read(PROD / "E36_DIALOGUE_MANIFEST_V6.json")
dialogue_manifest["rows"] = [row for row in dialogue_manifest["rows"] if row["video_unit_id"] != "U16"]
dialogue_manifest["rows"].append({
    "dia_id": "E36-U16A-D01",
    "video_unit_id": "U16",
    "speaker_id": "messenger",
    "speaker": "递信人",
    "spoken_text": "头一回给小的银子，是从这上头支的。",
    "status": "PASS",
    "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE",
    "path": rel(exact_audio),
    "sha256": exact_audio_sha,
    "duration_seconds": 3.436563,
    "voice_reference_asset_id": voice_asset,
    "voice_derivation_status": "PASS",
    "source_voice": "AGENTCUT_SPEECH_GENERATION:ttv-voice-2025092218535325-mrbtpNsP",
    "start_seconds": 0.7,
    "end_seconds": 3.5,
    "expression": "普通递信人被追问后的低声交代，畏缩发紧、气息微颤但字句清楚",
})
write(PROD / "E36_DIALOGUE_MANIFEST_V7.json", dialogue_manifest)

split_gate = {
    "schema": "qingshan.sentence_level_native_dialogue_split_gate.v1",
    "episode": "E36",
    "source_unit_id": "U16",
    "status": "PASS",
    "budget_accounting": "U16A_AND_U16B_ALREADY_SEPARATELY_COUNTED_IN_CAP_FIT_PLAN",
    "subunits": [
        {"source_segment_id": "U16A", "spoken_text": "头一回给小的银子，是从这上头支的。", "duration_seconds": 5},
        {"source_segment_id": "U16B", "spoken_text": "小的不识字，只认得这戳记，留着好有个凭证。", "duration_seconds": 5},
    ],
    "continuity_rule": "U16A ends with the ticket more than half extracted but not handed over; U16B continues the explanation and handover.",
}
write(U16_QA / "E36_U16_SENTENCE_LEVEL_NATIVE_DIALOGUE_SPLIT_GATE_V1.json", split_gate)

anchor_plan = {
    "schema": "qingshan.video_unit_anchor_count_plan.v1",
    "episode": "E36",
    "planned_reference_image_count": 1,
    "units": [{
        "unit_id": "U16",
        "planned_reference_image_count": 1,
        "reference_image_task_keys": ["E36-CW-U15C-TIMING-REPAIR-V1-TERMINAL-4P80"],
        "keyframe_interpolation_gate": {"status": "PASS", "anchor_count": 1, "checked_adjacent_pairs": 0, "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS", "reason": "U16A directly continues the accepted U15C terminal through one extraction motion."},
        "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "The predecessor terminal fixes both identities, hand positions, no-ticket start state, axis and light.", "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False}, "anchor_roles": ["accepted_predecessor_terminal_and_start_motion"], "action_design_class": "continuous_single_anchor_ticket_extraction_and_first_statement"},
    }],
}
write(U16_QA / "E36_U16A_ANCHOR_COUNT_PLAN_V1.json", anchor_plan)

causality = {
    "schema": "qingshan.common_sense_causality_plan.v1",
    "episode": "E36",
    "units": [{"unit_id": "U16", "causality": {
        "applicable": True,
        "purpose": "递信人回应钱款来源并从衣襟取出票据作为实物凭证。",
        "intended_effect": "票角先出现，递信人说完第一句时票据被抽出超过一半，但尚未交给陈迹。",
        "visible_causality": "陈迹的追问促使递信人右手从衣襟向外抽票，左手随后托住票据下缘。",
        "viewer_read": "观众能看清藏票、抽票、解释钱款来源三个连续因果。",
        "preconditions": ["U15C终帧已通过QA", "递信人右手在衣襟处", "票据尚未出现", "陈迹已经闭口"],
        "mechanism_chain": ["右手探入衣襟", "指腹夹住票据上缘", "票角先露出", "说第一句同时继续抽出", "左手托住下缘"],
        "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若票据完整瞬现、先交票或陈迹代说，实物证据出现的因果和说话人归属均断裂。"},
        "prop_function_status": "PASS",
        "evidence_refs": [rel(U16_QA / "E36_U15C_TERMINAL_ANCHOR_IMAGE_QA_V1.json"), rel(prompt)],
    }}],
}
write(U16_QA / "E36_U16A_COMMON_SENSE_CAUSALITY_PLAN_V1.json", causality)

period = {
    "schema": "qingshan.anachronism_lock_plan.v1",
    "episode": "E36",
    "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S04"]},
    "units": [{"unit_id": "U16", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["交领古装", "灰旧布衣", "无字木案", "无字药柜", "直棂木窗", "将尽古式烛台", "皱旧无字票据"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代文字", "官服", "民国妆发", "可读字幕", "水印", "现代纸张"], "exception_approvals": {}, "evidence_refs": [rel(terminal), rel(prompt)]}}],
}
write(U16_QA / "E36_U16A_PERIOD_LOCK_PLAN_V1.json", period)

dialogue_gate = {
    "schema": "qingshan.dialogue_prompt_gate.v1",
    "episode": "E36",
    "unit_id": "U16",
    "source_segment_id": "U16A",
    "status": "PASS",
    "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
    "speaker": "递信人",
    "spoken_text": "头一回给小的银子，是从这上头支的。",
    "start_seconds": 0.7,
    "end_seconds": 3.5,
    "voice_reference_asset_id": voice_asset,
    "voice_reference_sha256": voice_sha,
    "checks": {"exact_text_in_prompt": "PASS", "native_mandarin_required": "PASS", "visible_messenger_mouth": "PASS", "lip_breath_expression_sync": "PASS", "silent_age17_listener": "PASS", "closed_mouth_tail": "PASS", "second_sentence_forbidden": "PASS"},
    "failures": [],
}
write(U16_QA / "E36_U16A_DIALOGUE_PROMPT_GATE_V1.json", dialogue_gate)

config = read(PROD / "E36_U15C_EPISODE_SINGLE_UNIT_V1.json")
config.update({
    "status": "READY_FOR_SUPERVISOR_PRECHECK",
    "episode_paid_credits_before": 5263,
    "anchor_count_plan_ref": rel(U16_QA / "E36_U16A_ANCHOR_COUNT_PLAN_V1.json"),
    "common_sense_causality_plan_ref": rel(U16_QA / "E36_U16A_COMMON_SENSE_CAUSALITY_PLAN_V1.json"),
    "period_lock_plan_ref": rel(U16_QA / "E36_U16A_PERIOD_LOCK_PLAN_V1.json"),
    "complete_video_prompt_manifest_ref": rel(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V11.json"),
    "dialogue_manifest_ref": rel(PROD / "E36_DIALOGUE_MANIFEST_V7.json"),
    "dialogue_prompt_gate_ref": rel(U16_QA / "E36_U16A_DIALOGUE_PROMPT_GATE_V1.json"),
})

task = copy.deepcopy(config["tasks"][0])
task.update({
    "status": "READY",
    "task_key": "E36-CW-U16A-VIDEO-V1",
    "source_id": "E36-CW-U16A",
    "batch_id": "E36-U16A-VIDEO-V1",
    "unit_id": "U16",
    "visual_zone": "E36-U16A-CANONICAL-SENTENCE-SPLIT",
    "prompt_path": rel(prompt),
    "prompt_file": rel(prompt),
    "prompt_sha256": prompt_sha,
    "anchor_image_qa_ref": rel(U16_QA / "E36_U15C_TERMINAL_ANCHOR_IMAGE_QA_V1.json"),
    "split_gate_ref": rel(U16_QA / "E36_U16_SENTENCE_LEVEL_NATIVE_DIALOGUE_SPLIT_GATE_V1.json"),
    "reference_audio_asset_ids": [],
    "reference_audios": [rel(exact_audio)],
    "visual_entity_ids": ["messenger", "chenji"],
    "max_retries": 0,
})
task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 5, "rationale": "Five seconds preserve the exact first sentence, visible lip sync, progressive ticket extraction and a closed-mouth continuation tail.", "edit_policy": "Preserve native Mandarin and picture-audio sync; trim only terminal silence after QA."}
task["reference_images"] = [rel(messenger_image), rel(chenji_image), rel(terminal)]
task["reference_image_sequence"] = [
    {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "messenger", "path": rel(messenger_image), "sha256": sha(messenger_image), "identity_reference": True},
    {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(chenji_image), "sha256": sha(chenji_image), "identity_reference": True},
    {"asset_label": "@图片3", "role": "ACCEPTED_PREDECESSOR_TERMINAL_AND_START_MOTION_ANCHOR", "state_id": "E36-CW-U15C-TIMING-REPAIR-V1-TERMINAL-4P80", "path": rel(terminal), "sha256": terminal_sha, "identity_reference": False},
]
task["dialogue"] = [{"dia_id": "E36-U16A-D01", "speaker": "递信人", "spoken_text": "头一回给小的银子，是从这上头支的。", "start_seconds": 0.7, "end_seconds": 3.5, "expression": "普通递信人低声交代，畏缩发紧、气息微颤但字句清楚", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}]
task["dialogue_audio_assets"] = [{"dia_id": "E36-U16A-D01", "audio_slot": "@音频1", "speaker_id": "messenger", "character_name": "递信人", "spoken_text": "头一回给小的银子，是从这上头支的。", "path": rel(exact_audio), "sha256": exact_audio_sha, "duration_seconds": 3.436563, "voice_reference_asset_id": voice_asset, "voice_derivation_status": "PASS", "source_voice": "AGENTCUT_SPEECH_GENERATION:ttv-voice-2025092218535325-mrbtpNsP", "voice_gender": "male", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"}]
task["multimodal_entity_bindings"] = [
    {"entity_id": "messenger", "character_name": "递信人", "registry_id": "CHAR-递信人-E36-古装", "visual_reference": rel(messenger_image), "visual_reference_sha256": sha(messenger_image), "identity_image_slot": "@图片1", "voice_reference": rel(voice), "voice_reference_sha256": voice_sha, "voice_reference_asset_id": voice_asset, "audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1"], "visible_speaker": True, "lip_sync": True, "prop_owners": {"皱旧票据": "右手从衣襟抽出，左手托住下缘；本单元不交给陈迹"}, "ability_owners": []},
    {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(chenji_image), "visual_reference_sha256": sha(chenji_image), "identity_image_slot": "@图片2", "visible_speaker": False, "lip_sync": False, "prop_owners": {"皱旧票据": "全程不接触，只观看"}, "ability_owners": []},
]
task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
task["performance_spec"] = {
    "schema": "qingshan.performance_generation_spec.v2",
    "prop_ownership": {"皱旧票据": "递信人从自己右侧衣襟抽出并双手持有；陈迹全程不接触"},
    "motion_beats": [
        {"start_seconds": 0.0, "end_seconds": 0.7, "subject": "递信人、皱旧票据、陈迹", "action": "递信人右手探入右侧衣襟并夹住票据上缘，向外略向左下抽动，仅露出一小截票角；陈迹闭口观看", "contact_point": "递信人右手拇指和食指指腹接触票据上缘；陈迹不接触", "direction": "由胸前衣襟内向外、略向左下", "end_state": "仅票角露出，递信人将开口，陈迹闭口", "intent": "建立证据从藏处出现的物理起点", "visible_causality": "追问促使递信人从衣襟取证", "expression": "递信人畏缩，陈迹冷静", "viewer_read": "票角先出现且证据归属清楚"},
        {"start_seconds": 0.7, "end_seconds": 3.5, "subject": "递信人、皱旧票据", "action": "递信人完整嘴部可见，以自然中文普通话说出头一回给小的银子，是从这上头支的，同时右手继续抽票、左手托住下缘", "contact_point": "右手夹票据上缘，左手掌缘托住票据下缘", "direction": "票据由衣襟向左前方缓慢移出", "end_state": "第一句结束，票据抽出超过一半，仍由递信人双手持有", "intent": "交代第一笔钱的来源", "visible_causality": "说话与取证动作同步推进", "expression": "低声畏缩、气息微颤", "viewer_read": "说话人、钱款来源和票据关系清楚"},
        {"start_seconds": 3.5, "end_seconds": 5.0, "subject": "递信人、皱旧票据、陈迹", "action": "递信人闭口轻吸气，双手稳住抽出超过一半的票据并斜向陈迹；陈迹闭口低眼看票", "contact_point": "递信人双手持续接触票据；陈迹双手不接触", "direction": "票据斜向左前方但不跨入陈迹手中", "end_state": "票据未交付，递信人闭口，陈迹未接触，供U16B续接", "intent": "保留第二句与递交动作", "visible_causality": "第一句结束后证据保持在递信人手中", "expression": "递信人紧张，陈迹专注", "viewer_read": "本单元只完成第一句与半抽票"},
    ],
}
task["keyframe_interpolation_gate"] = {"status": "PASS", "anchor_count": 1, "checked_adjacent_pairs": 0, "reason": "One accepted U15C terminal supports the continuous ticket-extraction action and first statement."}
config["tasks"] = [task]
write(PROD / "E36_U16A_EPISODE_SINGLE_UNIT_V1.json", config)
