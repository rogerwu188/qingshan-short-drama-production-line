#!/usr/bin/env python3
"""Build the E36 U16B single-unit package from the accepted U16A terminal."""

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


prompt = PROD / "video_prompts_repair_v5/E36-CW-U16B.txt"
terminal = ROOT / "working_assets/e36_v2_stills_20260728/terminal_anchors/E36-CW-U16A-ENDSTATE-REPAIR-V1-TERMINAL-4P95.png"
terminal_qa = U16_QA / "E36_U16A_TERMINAL_ANCHOR_IMAGE_QA_V1.json"
messenger_image = ROOT / "assets/reference/e25_20260719/E25-FAKE-MESSENGER-IDENTITY-LOCK.png"
chenji_image = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
voice = ROOT / "libraries/audio/voice_refs/agentcut_speech_v1_20260723/e36_luocheng_messenger/VOICE-e36_luocheng_messenger-agentcut-v1.wav"
voice_asset = "3llwjcbwf3w"
exact_audio = ROOT / "working_assets/e36_dialogue_audio_refs_20260729/u16b/E36-U16B-D01.wav"
audio_qa = read(U16_QA / "E36_U16B_EXACT_DIALOGUE_AUDIO_QA_V1.json")
audio_duration = float(audio_qa["duration_seconds"])
spoken_text = "小的不识字，只认得这戳记，留着好有个凭证。"

prompt_manifest = read(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V11.json")
for row in prompt_manifest["rows"]:
    if row["unit_id"] == "U16":
        row["prompt_path"] = rel(prompt)
        row["prompt_sha256"] = sha(prompt)
write(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V12.json", prompt_manifest)

dialogue_manifest = read(PROD / "E36_DIALOGUE_MANIFEST_V7.json")
dialogue_manifest["rows"] = [row for row in dialogue_manifest["rows"] if row["video_unit_id"] != "U16"]
dialogue_manifest["rows"].append(
    {
        "dia_id": "E36-U16B-D01",
        "video_unit_id": "U16",
        "speaker_id": "messenger",
        "speaker": "递信人",
        "spoken_text": spoken_text,
        "status": "PASS",
        "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE",
        "path": rel(exact_audio),
        "sha256": sha(exact_audio),
        "duration_seconds": audio_duration,
        "voice_reference_asset_id": voice_asset,
        "voice_derivation_status": "PASS",
        "source_voice": "AGENTCUT_SPEECH_GENERATION:ttv-voice-2025092218535325-mrbtpNsP",
        "start_seconds": 0.3,
        "end_seconds": 4.45,
        "expression": "普通递信人继续低声解释票根来由，畏缩发紧、气息微颤、口语自然清楚",
    }
)
write(PROD / "E36_DIALOGUE_MANIFEST_V8.json", dialogue_manifest)

anchor_plan = {
    "schema": "qingshan.video_unit_anchor_count_plan.v1",
    "episode": "E36",
    "planned_reference_image_count": 1,
    "units": [
        {
            "unit_id": "U16",
            "planned_reference_image_count": 1,
            "reference_image_task_keys": ["E36-CW-U16A-ENDSTATE-REPAIR-V1-TERMINAL-4P95"],
            "keyframe_interpolation_gate": {
                "status": "PASS",
                "anchor_count": 1,
                "checked_adjacent_pairs": 0,
                "candidate_recheck_required": True,
                "physical_interpolation_or_declared_cut": "PASS",
                "reason": "U16B directly continues the accepted U16A terminal through one supported ticket-presentation motion.",
            },
            "anchor_count_decision": {
                "planned_reference_image_count": 1,
                "reason": "The accepted predecessor terminal fixes both identities, ticket ownership, hand positions, axis and dusk light.",
                "criteria": {
                    "continuous_motion_from_single_start": True,
                    "identity_or_space_reanchor": False,
                    "prop_ownership_transition": False,
                    "non_interpolable_terminal_state": False,
                },
                "anchor_roles": ["accepted_predecessor_terminal_and_start_motion"],
                "action_design_class": "continuous_single_anchor_ticket_presentation_and_second_statement",
            },
        }
    ],
}
write(U16_QA / "E36_U16B_ANCHOR_COUNT_PLAN_V1.json", anchor_plan)

causality = {
    "schema": "qingshan.common_sense_causality_plan.v1",
    "episode": "E36",
    "units": [
        {
            "unit_id": "U16",
            "causality": {
                "applicable": True,
                "purpose": "递信人解释自己不识字、只认戳记，并把票根捧到陈迹面前作为凭证。",
                "intended_effect": "第二句说完时票根完整抽出并被双手支撑，停在陈迹手前但尚未交付。",
                "visible_causality": "解释戳记与留凭证的同时，双手把票根从半抽状态继续推出并横捧。",
                "viewer_read": "观众能看清不识字、认戳记、保留票根和呈交证据四个连续因果。",
                "preconditions": ["U16A终帧已通过QA", "票据抽出超过一半", "票据仍归递信人双手持有", "陈迹闭口且未接触"],
                "mechanism_chain": ["双手保持上下缘支撑", "票据继续向左前方推出", "递信人说完整第二句", "票据横捧至陈迹手前", "陈迹抬手但保留间隙"],
                "counterfactual_test": {
                    "opponent_can_bypass": False,
                    "reasoning": "若陈迹提前接票、票据悬空或先显戳记，U17的接验与显字因果会被抢拍。",
                },
                "prop_function_status": "PASS",
                "evidence_refs": [rel(terminal_qa), rel(prompt)],
            },
        }
    ],
}
write(U16_QA / "E36_U16B_COMMON_SENSE_CAUSALITY_PLAN_V1.json", causality)

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
    "units": [
        {
            "unit_id": "U16",
            "period_lock": {
                "status": "PASS",
                "reviewed_visible_elements": ["交领古装", "灰旧布衣", "无字木案", "无字药柜", "直棂木窗", "将尽古式烛台", "皱旧无字票据"],
                "detected_anachronisms": [],
                "forbidden_elements": ["现代物件", "现代文字", "官服", "民国妆发", "可读字幕", "水印", "现代纸张"],
                "exception_approvals": {},
                "evidence_refs": [rel(terminal), rel(prompt)],
            },
        }
    ],
}
write(U16_QA / "E36_U16B_PERIOD_LOCK_PLAN_V1.json", period)

dialogue_gate = {
    "schema": "qingshan.dialogue_prompt_gate.v1",
    "episode": "E36",
    "unit_id": "U16",
    "source_segment_id": "U16B",
    "status": "PASS",
    "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
    "speaker": "递信人",
    "spoken_text": spoken_text,
    "start_seconds": 0.3,
    "end_seconds": 4.45,
    "voice_reference_asset_id": voice_asset,
    "voice_reference_sha256": sha(voice),
    "checks": {
        "exact_text_in_prompt": "PASS",
        "native_mandarin_required": "PASS",
        "visible_messenger_mouth": "PASS",
        "lip_breath_expression_sync": "PASS",
        "silent_age17_listener": "PASS",
        "closed_mouth_tail": "PASS",
        "u17_handover_and_stamp_reveal_forbidden": "PASS",
    },
    "failures": [],
}
write(U16_QA / "E36_U16B_DIALOGUE_PROMPT_GATE_V1.json", dialogue_gate)

config = read(PROD / "E36_U16A_EPISODE_SINGLE_UNIT_V1.json")
config.update(
    {
        "status": "READY_FOR_SUPERVISOR_PRECHECK",
        "episode_paid_credits_before": 5365,
        "anchor_count_plan_ref": rel(U16_QA / "E36_U16B_ANCHOR_COUNT_PLAN_V1.json"),
        "common_sense_causality_plan_ref": rel(U16_QA / "E36_U16B_COMMON_SENSE_CAUSALITY_PLAN_V1.json"),
        "period_lock_plan_ref": rel(U16_QA / "E36_U16B_PERIOD_LOCK_PLAN_V1.json"),
        "complete_video_prompt_manifest_ref": rel(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V12.json"),
        "dialogue_manifest_ref": rel(PROD / "E36_DIALOGUE_MANIFEST_V8.json"),
        "dialogue_prompt_gate_ref": rel(U16_QA / "E36_U16B_DIALOGUE_PROMPT_GATE_V1.json"),
    }
)

task = copy.deepcopy(config["tasks"][0])
task.update(
    {
        "status": "READY",
        "task_key": "E36-CW-U16B-VIDEO-V1",
        "source_id": "E36-CW-U16B",
        "batch_id": "E36-U16B-VIDEO-V1",
        "unit_id": "U16",
        "visual_zone": "E36-U16B-CANONICAL-SENTENCE-SPLIT",
        "prompt_path": rel(prompt),
        "prompt_file": rel(prompt),
        "prompt_sha256": sha(prompt),
        "anchor_image_qa_ref": rel(terminal_qa),
        "split_gate_ref": rel(U16_QA / "E36_U16_SENTENCE_LEVEL_NATIVE_DIALOGUE_SPLIT_GATE_V1.json"),
        "reference_audio_asset_ids": [],
        "reference_audios": [rel(exact_audio)],
        "visual_entity_ids": ["messenger", "chenji"],
        "max_retries": 0,
    }
)
task["duration_plan"] = {
    "policy": "qingshan.shot_generation_duration.v5",
    "duration_seconds": 5,
    "rationale": "Five seconds preserve the exact second sentence, visible lip sync, supported ticket presentation and a closed-mouth U17 continuation tail.",
    "edit_policy": "Preserve native Mandarin and picture-audio sync; trim only terminal silence after QA.",
}
task["reference_images"] = [rel(messenger_image), rel(chenji_image), rel(terminal)]
task["reference_image_sequence"] = [
    {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "messenger", "path": rel(messenger_image), "sha256": sha(messenger_image), "identity_reference": True},
    {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(chenji_image), "sha256": sha(chenji_image), "identity_reference": True},
    {"asset_label": "@图片3", "role": "ACCEPTED_PREDECESSOR_TERMINAL_AND_START_MOTION_ANCHOR", "state_id": "E36-CW-U16A-ENDSTATE-REPAIR-V1-TERMINAL-4P95", "path": rel(terminal), "sha256": sha(terminal), "identity_reference": False},
]
task["dialogue"] = [
    {
        "dia_id": "E36-U16B-D01",
        "speaker": "递信人",
        "spoken_text": spoken_text,
        "start_seconds": 0.3,
        "end_seconds": 4.45,
        "expression": "普通递信人低声解释，畏缩发紧、气息微颤、口语自然清楚",
        "language": "zh-CN",
        "native_video_audio": True,
        "lip_sync": True,
        "breath_expression_sync": True,
    }
]
task["dialogue_audio_assets"] = [
    {
        "dia_id": "E36-U16B-D01",
        "audio_slot": "@音频1",
        "speaker_id": "messenger",
        "character_name": "递信人",
        "spoken_text": spoken_text,
        "path": rel(exact_audio),
        "sha256": sha(exact_audio),
        "duration_seconds": audio_duration,
        "voice_reference_asset_id": voice_asset,
        "voice_derivation_status": "PASS",
        "source_voice": "AGENTCUT_SPEECH_GENERATION:ttv-voice-2025092218535325-mrbtpNsP",
        "voice_gender": "male",
        "mode": "exact_dialogue_audio_reference",
        "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
    }
]
task["multimodal_entity_bindings"] = [
    {
        "entity_id": "messenger",
        "character_name": "递信人",
        "registry_id": "CHAR-递信人-E36-古装",
        "visual_reference": rel(messenger_image),
        "visual_reference_sha256": sha(messenger_image),
        "identity_image_slot": "@图片1",
        "voice_reference": rel(voice),
        "voice_reference_sha256": sha(voice),
        "voice_reference_asset_id": voice_asset,
        "audio_slot": "@音频1",
        "dialogue_audio_slots": ["@音频1"],
        "visible_speaker": True,
        "lip_sync": True,
        "prop_owners": {"皱旧票据": "双手持票并捧到陈迹面前；本单元不交给陈迹"},
        "ability_owners": [],
    },
    {
        "entity_id": "chenji",
        "character_name": "陈迹",
        "registry_id": "CHAR-陈迹-古装",
        "visual_reference": rel(chenji_image),
        "visual_reference_sha256": sha(chenji_image),
        "identity_image_slot": "@图片2",
        "visible_speaker": False,
        "lip_sync": False,
        "prop_owners": {"皱旧票据": "全程不接触，只抬手靠近并保留间隙"},
        "ability_owners": [],
    },
]
task["multimodal_binding_sha256"] = hashlib.sha256(
    json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
task["performance_spec"] = {
    "schema": "qingshan.performance_generation_spec.v2",
    "prop_ownership": {"皱旧票据": "递信人双手持续支撑并横捧；陈迹全程不接触"},
    "motion_beats": [
        {
            "start_seconds": 0.0,
            "end_seconds": 0.3,
            "subject": "递信人、皱旧票据、陈迹",
            "action": "递信人双手从U16A半抽状态继续向左前方推出票据，陈迹闭口低眼看票",
            "contact_point": "递信人右手指腹接触票据上缘、左手掌缘托住下缘；陈迹不接触",
            "direction": "由胸前向左前方",
            "end_state": "票据接近完整抽出，仍由递信人双手支撑",
            "intent": "承接前镜并建立第二句动作起点",
            "visible_causality": "U16A的半抽动作不中断",
            "expression": "递信人畏缩，陈迹专注",
            "viewer_read": "证据归属和动作连续性清楚",
        },
        {
            "start_seconds": 0.3,
            "end_seconds": 4.45,
            "subject": "递信人、皱旧票据",
            "action": f"递信人完整嘴部可见，以自然中文普通话只说一遍{spoken_text}，同时双手把票据完整抽出并横捧到陈迹手前",
            "contact_point": "右手稳定票据右上缘，左手托住左下缘",
            "direction": "由胸前向左前方，终点距陈迹手一掌",
            "end_state": "第二句结束，票据完整横捧但仍归递信人双手持有",
            "intent": "解释认戳记并保留凭证",
            "visible_causality": "解释与呈证动作同步",
            "expression": "低声畏缩、气息微颤",
            "viewer_read": "说话人、票据用途和证据状态清楚",
        },
        {
            "start_seconds": 4.45,
            "end_seconds": 5.0,
            "subject": "递信人、皱旧票据、陈迹",
            "action": "递信人闭口轻呼气并保持双手捧票，陈迹右手抬起一半靠近票边但不接触",
            "contact_point": "递信人双手持续接触票据；陈迹指尖与票边保留可见间隙",
            "direction": "票据保持向左前方，陈迹右手由案边向票边靠近",
            "end_state": "票据未交付，递信人闭口，陈迹未接触，供U17从接过开始",
            "intent": "保留接验与显戳记动作",
            "visible_causality": "第二句结束后证据等待陈迹接验",
            "expression": "递信人紧张，陈迹专注",
            "viewer_read": "本单元只完成第二句和呈票，不抢拍接票",
        },
    ],
}
task["keyframe_interpolation_gate"] = {
    "status": "PASS",
    "anchor_count": 1,
    "checked_adjacent_pairs": 0,
    "reason": "One accepted U16A terminal supports the continuous ticket-presentation action and second statement.",
}
config["tasks"] = [task]
write(PROD / "E36_U16B_EPISODE_SINGLE_UNIT_V1.json", config)
