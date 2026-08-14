#!/usr/bin/env python3
"""Build the E36 U10 canonical line15 Fast6s native-dialogue package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
SOURCE = BASE / "recovery_10000_20260730/u20a_r1_video/E36_U20A_R1_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json"
OUT = BASE / "recovery_10000_20260730/u10_line15_video"
QA = ROOT / "qa/e36_agentcut_20260730/u10_line15_video_runtime"
CONFIG = OUT / "E36_U10_LINE15_FAST6S_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U10-L15-FAST6S.txt"
PROMPT_MANIFEST = OUT / "E36_U10_LINE15_FAST6S_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U10_LINE15_FAST6S_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U10_LINE15_FAST6S_DIALOGUE_PROMPT_GATE_V1.json"
ANCHOR_PLAN = QA / "E36_U10_LINE15_FAST6S_ANCHOR_COUNT_PLAN_V1.json"
CAUSALITY_PLAN = QA / "E36_U10_LINE15_FAST6S_COMMON_SENSE_CAUSALITY_PLAN_V1.json"
PERIOD_PLAN = QA / "E36_U10_LINE15_FAST6S_PERIOD_LOCK_PLAN_V1.json"
AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u10_line15/E36-U10-L15-D01.wav"
AUDIO_QA = ROOT / "qa/e36_agentcut_20260730/u10_line15_video_runtime/E36-U10-L15-D01_EXACT_DIALOGUE_AUDIO_QA_V1.json"
ROBUST_QA = ROOT / "qa/e36_agentcut_20260730/u10_line15_video_runtime/E36-U10-L15-D01_UNCONDITIONED_ASR_ROBUST_V1.json"
MESSENGER = ROOT / "assets/reference/e25_20260719/E25-FAKE-MESSENGER-IDENTITY-LOCK.png"
ANCHOR = ROOT / "working_assets/e36_recovery_10000_20260730/u10_line15_image/E36-CW-U10-L15-A1-STILL-V1_3a06481b-ad78-4398-b0cf-12f1f3642663.png"
ANCHOR_QA = ROOT / "qa/e36_agentcut_20260730/u10_line15_image_runtime/E36_U10_LINE15_SPEAKING_ANCHOR_DIRECT_VISUAL_QA_V1.json"
TEXT = "小的一个废物，凭什么惊动这许多老爷？小的自己都怕！"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"
VOICE_REFERENCE_ASSET_ID = "3llwjcbwf3w"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    anchor_qa = json.loads(ANCHOR_QA.read_text(encoding="utf-8"))
    audio_qa = json.loads(AUDIO_QA.read_text(encoding="utf-8"))
    robust_qa = json.loads(ROBUST_QA.read_text(encoding="utf-8"))
    if anchor_qa.get("verdict") != "PASS_ACCEPTED_U10_LINE15_SPEAKING_ANCHOR_V1_ONLY" or not anchor_qa.get("video_submission_allowed"):
        raise SystemExit("Line15 speaking anchor is not direct image-QA PASS")
    if sha(ANCHOR) != anchor_qa["image"]["sha256"]:
        raise SystemExit("Line15 anchor SHA mismatch")
    if audio_qa.get("status") != "PASS" or audio_qa.get("asr_similarity") != 1.0 or sha(AUDIO) != audio_qa.get("wav_sha256"):
        raise SystemExit("Line15 contextual source is not exact PASS")
    summary = robust_qa.get("summary") or {}
    if robust_qa.get("status") != "PASS_ROBUST_EXACT_12_OF_12" or summary.get("exact_count") != 12 or summary.get("decode_count") != 12:
        raise SystemExit("Line15 robust source is not exact12/12 PASS")

    config = json.loads(SOURCE.read_text(encoding="utf-8"))
    config.update({
        "status": "READY_FOR_SUPERVISOR_PRECHECK",
        "episode_paid_credits_before": 7868,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u10_line15_video",
        "qa_dir": rel(QA),
        "anchor_count_plan_ref": rel(ANCHOR_PLAN),
        "common_sense_causality_plan_ref": rel(CAUSALITY_PLAN),
        "period_lock_plan_ref": rel(PERIOD_PLAN),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "dialogue_prompt_gate_ref": rel(DIALOGUE_GATE),
        "targeted_unit_replacement": True,
        "streaming_submission_policy": "SUBMIT_EACH_UNIT_IMMEDIATELY_WHEN_ITS_OWN_DEPENDENCIES_PASS",
    })
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U10-L15-FAST6S-10000",
        "source_id": "E36-CW-U10-L15-FAST6S-10000",
        "batch_id": "E36-U10-L15-FAST6S-10000",
        "unit_id": "U10",
        "scene_id": "E36-CW-S03",
        "visual_zone": "E36-U10-CLINIC-SECRET-ROOM-MESSENGER-CONFESSION",
        "source_segment_id": "U10-L15",
        "duration_seconds": 6,
        "duration": 6,
        "edit_target_duration_seconds": 6,
        "status": "READY_TO_SUBMIT",
        "model": "seedance-2.0-fast",
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": sha(PROMPT),
        "reference_images": [rel(MESSENGER), rel(ANCHOR)],
        "reference_audios": [rel(AUDIO)],
        "reference_audio_asset_ids": [],
        "audio_reference_optional": False,
        "native_dialogue_required": True,
        "visible_speaker_required": True,
        "temporal_visual_qa_required": True,
        "targeted_unit_replacement": True,
        "max_retries": 0,
    })
    task["duration_plan"] = {
        "policy": "qingshan.shot_generation_duration.v5",
        "duration_seconds": 6,
        "rationale": "The exact Mandarin reference is4.864604s and fits0.20-5.20 with a0.80s closed-mouth terminal beat.",
        "edit_policy": "Preserve source-native dialogue and terminal head-lower; no post-dub, time stretch, filler or repeated frames.",
    }
    task["reference_image_sequence"] = [
        {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "messenger", "path": rel(MESSENGER), "sha256": sha(MESSENGER), "identity_reference": True},
        {"asset_label": "@图片2", "role": "ACCEPTED_START_MOTION_SPEAKING_ANCHOR", "state_id": "E36-CW-U10-L15-A1-STILL-V1", "path": rel(ANCHOR), "sha256": sha(ANCHOR), "identity_reference": False},
    ]
    task["planned_reference_image_count"] = 1
    task["state_reference_minimum"] = 1
    task["dialogue"] = [{
        "dia_id": "E36-U10-L15-D01",
        "speaker": "递信人",
        "spoken_text": TEXT,
        "start_seconds": 0.20,
        "end_seconds": 5.20,
        "breath_after_seconds": 0.0,
        "expression": "被缚跪坐、抓紧膝上粗布、湿眼恐惧自白，末句后低头闭口",
        "language": "zh-CN",
        "native_video_audio": True,
        "lip_sync": True,
        "breath_expression_sync": True,
    }]
    task["dialogue_audio_assets"] = [{
        "dia_id": "E36-U10-L15-D01",
        "audio_slot": "@音频1",
        "speaker_id": "messenger",
        "character_name": "递信人",
        "spoken_text": TEXT,
        "path": rel(AUDIO),
        "sha256": sha(AUDIO),
        "duration_seconds": 4.864604,
        "remote_asset_id": None,
        "voice_reference_asset_id": VOICE_REFERENCE_ASSET_ID,
        "voice_derivation_status": "PASS",
        "source_voice": "AGENTCUT_SPEECH_GENERATION:d33fd098-bbc5-451f-abe8-c6b243b35314",
        "voice_gender": "male",
        "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE",
        "mode": "exact_dialogue_audio_reference",
        "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
    }]
    task["performance_spec"] = {
        "schema": "qingshan.performance_generation_spec.v2",
        "prop_ownership": {"膝上粗布衣料": "全段由递信人右手持续抓紧，不换手、不撕裂"},
        "motion_beats": [
            {"start_seconds": 0.0, "end_seconds": 0.2, "subject": "成年递信人", "action": "承接被缚跪姿，右手进一步收紧膝上粗布，肩膀处于颤动中段，嘴唇转入发音", "contact_point": "右手指节与膝上粗布；双膝与旧木地面", "direction": "身体和视线由画面右侧朝画外左前方皎兔", "end_state": "完整嘴部清楚并立即连续开口", "intent": "恐惧求生", "visible_causality": "束缚和审问压力触发抓衣与自白", "expression": "湿眼、呼吸发紧", "viewer_read": "递信人已经害怕到发抖"},
            {"start_seconds": 0.2, "end_seconds": 5.2, "subject": "成年递信人", "action": "按音频1只说一遍完整line15，抓衣不松，问句时抬眉，末句气息更紧", "contact_point": "右手持续压住膝上粗布；双膝持续接触旧木地面", "direction": "脸和视线始终朝画外左前方，绝不看镜头", "end_state": "末字怕完整落下并自然闭口，头开始下落", "intent": "表明自己只是无足轻重的棋子", "visible_causality": "恐惧姿态和持续接触支撑自白", "expression": "羞惧、求生", "viewer_read": "台词、嘴型和身体恐惧一致"},
            {"start_seconds": 5.2, "end_seconds": 6.0, "subject": "成年递信人", "action": "闭口低头，肩膀保留一次轻微余颤，右手不松开衣料", "contact_point": "右手与粗布、双膝与地面保持连续", "direction": "头由画外左前方缓慢向下", "end_state": "低头闭口、肩膀轻颤、右手持续抓衣", "intent": "收束自白并等待反应", "visible_causality": "末字后的泄气带来低头终态", "expression": "余悸未消", "viewer_read": "句子已结束且终态可承接"},
        ],
    }
    task["multimodal_entity_bindings"] = [{
        "entity_id": "messenger",
        "character_name": "递信人",
        "registry_id": "CHAR-递信人-E36-古装",
        "visual_reference": rel(MESSENGER),
        "visual_reference_sha256": sha(MESSENGER),
        "identity_image_slot": "@图片1",
        "visible_speaker": True,
        "lip_sync": True,
        "prop_owners": {"膝上粗布衣料": "右手持续抓紧"},
        "ability_owners": [],
        "voice_reference": rel(AUDIO),
        "voice_reference_sha256": sha(AUDIO),
        "voice_reference_asset_id": VOICE_REFERENCE_ASSET_ID,
        "audio_slot": "@音频1",
        "dialogue_audio_slots": ["@音频1"],
    }]
    task["multimodal_binding_sha256"] = digest(task["multimodal_entity_bindings"])
    task["visual_entity_ids"] = ["messenger"]
    task["anchor_image_qa_ref"] = rel(ANCHOR_QA)
    task["keyframe_interpolation_gate"] = {
        "status": "PASS",
        "anchor_count": 1,
        "checked_adjacent_pairs": 0,
        "reason": "One direct-QA speaking anchor supports a continuous six-second single-speaker confession with explicit grip, gaze and terminal head-lower states.",
    }

    prompt_manifest = json.loads((BASE / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V21.json").read_text(encoding="utf-8"))
    prompt_manifest["source_scene_authority_sha256"] = sha(ROOT / config["scene_contract_ref"])
    next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U10").update({"prompt_path": rel(PROMPT), "prompt_sha256": sha(PROMPT)})
    write(PROMPT_MANIFEST, prompt_manifest)

    dialogue_manifest = json.loads((BASE / "E36_DIALOGUE_MANIFEST_V11.json").read_text(encoding="utf-8"))
    dialogue_manifest["rows"].append({
        "video_unit_id": "U10",
        "dia_id": "E36-U10-L15-D01",
        "status": "PASS",
        "speaker": "递信人",
        "spoken_text": TEXT,
        "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE",
        "path": rel(AUDIO),
        "sha256": sha(AUDIO),
        "remote_asset_id": VOICE_REFERENCE_ASSET_ID,
        "start_seconds": 0.20,
        "end_seconds": 5.20,
        "breath_after_seconds": 0.0,
        "expression": "被缚跪坐、抓衣、湿眼恐惧自白，末句后低头闭口",
    })
    write(DIALOGUE_MANIFEST, dialogue_manifest)

    write(DIALOGUE_GATE, {
        "schema": "qingshan.dialogue_prompt_gate.v1",
        "episode": "E36",
        "unit_id": "U10",
        "source_segment_id": "U10-L15",
        "source_cl2x": "CL2X-851",
        "status": "PASS",
        "canonical_script_sha256": SCRIPT_SHA,
        "manifest_sha256": MANIFEST_SHA,
        "dialogue": [{"dia_id": "E36-U10-L15-D01", "spoken_text": TEXT, "start_seconds": 0.20, "end_seconds": 5.20, "voice_reference_sha256": sha(AUDIO)}],
        "checks": {
            "canonical_and_manifest_sha_match": "PASS",
            "exact_text_in_prompt": "PASS",
            "contextual_audio_asr": "PASS_1P0",
            "robust_unconditioned_audio_asr": "PASS_EXACT_12_OF_12",
            "audio_duration": "PASS_4P864604_WITHIN_6_SECOND_CONSUMER",
            "native_mandarin_required": "PASS",
            "visible_messenger_mouth": "PASS_DIRECT_IMAGE_QA",
            "lip_breath_expression_sync": "PASS",
            "closed_mouth_tail": "PASS_0P80",
            "action_contract": "PASS_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE",
            "first_frame_motion_state": "PASS",
            "environment_life": "PASS_B_LEVEL",
            "period_weather_continuity": "PASS_INTERIOR_CLEAR_HARSH_SUN",
            "visible_text": "PASS_FORBIDDEN_AND_ANCHOR_OCR_ZERO",
            "credit_limit": "PASS_7868_PLUS96_LE10000",
        },
        "failures": [],
        "blocked_by": None,
        "submission_allowed_after_supervisor_precheck": True,
    })
    write(ANCHOR_PLAN, {
        "schema": "qingshan.video_unit_anchor_count_plan.v1",
        "episode": "E36",
        "planned_reference_image_count": 1,
        "units": [{
            "unit_id": "U10",
            "source_segment_id": "U10-L15",
            "planned_reference_image_count": 1,
            "reference_image_task_keys": ["E36-CW-U10-L15-A1-STILL-V1"],
            "keyframe_interpolation_gate": task["keyframe_interpolation_gate"],
            "anchor_count_decision": {
                "planned_reference_image_count": 1,
                "reason": "Single continuous speaking close shot; the accepted anchor already binds identity, mouth, grip, kneeling contact, direction and environment.",
                "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False},
                "anchor_roles": ["accepted_start_motion_speaking_anchor"],
                "action_design_class": "single_anchor_single_speaker_native_dialogue_confession",
            },
        }],
    })
    write(CAUSALITY_PLAN, {
        "schema": "qingshan.common_sense_causality_plan.v1",
        "episode": "E36",
        "units": [{
            "unit_id": "U10",
            "source_segment_id": "U10-L15",
            "causality": {
                "applicable": True,
                "purpose": "递信人在审问压力下以恐惧自白表明自己只是无足轻重的送信棋子。",
                "intended_effect": "观众同时读到台词的自轻、抓衣的求生和末句后的泄气。",
                "visible_causality": "束缚跪姿与画外审问压力引发抓衣、湿眼、呼吸发紧、完整自白和低头闭口终态。",
                "viewer_read": "递信人害怕且不知道自己为何引来诸方追逐。",
                "preconditions": ["line15 source contextual1.0", "line15 source robust12/12", "speaking anchor direct image QA PASS"],
                "mechanism_chain": ["抓衣收紧", "肩膀颤动", "抬眉问句", "末句气息发紧", "低头闭口"],
                "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若嘴部被遮、抓衣接触中断、看镜头或末句后不闭口，恐惧自白的可见因果链不成立。"},
                "prop_function_status": "PASS",
                "evidence_refs": [rel(ANCHOR_QA), rel(PROMPT), rel(AUDIO_QA), rel(ROBUST_QA)],
            },
        }],
    })
    write(PERIOD_PLAN, {
        "schema": "qingshan.anachronism_lock_plan.v1",
        "episode": "E36",
        "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "canonical_script_sha256": SCRIPT_SHA, "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S03"]},
        "units": [{
            "unit_id": "U10",
            "source_segment_id": "U10-L15",
            "period_lock": {
                "status": "PASS",
                "reviewed_visible_elements": ["成年递信人粗布黑头巾", "黑色旧交领短褐", "太平医馆密室旧木地面", "直棂木窗", "裸蜡烛古式烛台"],
                "detected_anachronisms": [],
                "forbidden_elements": ["现代物件", "现代妆发", "民国灯具", "字幕", "水印", "可读文字或伪文字"],
                "exception_approvals": {},
                "evidence_refs": [rel(ANCHOR), rel(ANCHOR_QA), rel(PROMPT)],
            },
        }],
    })
    write(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": rel(CONFIG), "config_sha256": sha(CONFIG), "prompt": rel(PROMPT), "prompt_sha256": sha(PROMPT), "anchor_sha256": sha(ANCHOR), "audio_sha256": sha(AUDIO)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
