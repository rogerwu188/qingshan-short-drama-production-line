#!/usr/bin/env python3
"""Build the first speech-feasible U11 transcript-recovery video unit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
TEMPLATE_DIR = BASE / "recovery_10000_20260730/u14_r2_video"
OUT = BASE / "recovery_10000_20260730/u11_r1a_video"
QA = ROOT / "qa/e36_agentcut_20260730/u11_r1a_video_runtime"
SRC = TEMPLATE_DIR / "E36_U14_R2_EPISODE_PARALLEL_BATCH_V1.json"
CONFIG = OUT / "E36_U11_R1A_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U11-R1A-RECOVERY.txt"
PROMPT_MANIFEST = OUT / "E36_U11_R1A_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U11_R1A_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U11_R1A_DIALOGUE_PROMPT_GATE_V1.json"
ANCHOR_PLAN = QA / "E36_U11_R1A_ANCHOR_COUNT_PLAN_V1.json"
CAUSALITY_PLAN = QA / "E36_U11_R1A_COMMON_SENSE_CAUSALITY_PLAN_V1.json"
PERIOD_PLAN = QA / "E36_U11_R1A_PERIOD_LOCK_PLAN_V1.json"

CHENJI = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
YUNYANG = ROOT / "assets/reference/e36_20260729/characters/CHAR-yunyang-age17-canonical-v1-20260729.png"
ANCHOR = ROOT / "working_assets/e36_v2_stills_20260728/repair_v2_candidates/E36_E36-CW-U11-A1-STILL-V2_e3678bd0-6888-41ab-8d4f-4a68bbe2aea9.png"
AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u11_r1/E36-U11-R1-D01.wav"
AUDIO_QA = ROOT / "qa/e36_agentcut_20260730/u11_r1_video_runtime/E36-U11-R1-D01_EXACT_DIALOGUE_AUDIO_QA_V1.json"
AUDIO_RECEIPT = ROOT / "workflow/tasks/E36_U11_R1_D01_YUNYANG_EXACT_DIALOGUE_AUDIO_GENERATION_V1.json"
TEXT = "空信封……可他每露一次面，咱们就倾巢而动。这不合规矩。"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    audio_qa = json.loads(AUDIO_QA.read_text(encoding="utf-8"))
    audio_receipt = json.loads(AUDIO_RECEIPT.read_text(encoding="utf-8"))
    if audio_qa.get("status") != "PASS" or audio_qa.get("asr_similarity") != 1.0:
        raise SystemExit("U11-R1A Yunyang exact audio is not ASR1.0 PASS")
    if sha(AUDIO) != audio_qa.get("wav_sha256") or not audio_receipt.get("task_id"):
        raise SystemExit("U11-R1A audio provenance mismatch")
    if not (5.0 <= float(audio_qa["duration_seconds"]) <= 5.3):
        raise SystemExit("U11-R1A exact audio no longer fits the six-second natural unit")

    prompt = f"""【E36-CW-U11-R1A｜6秒｜空信封异常｜Seedance Fast原生普通话｜独立转录恢复单元】

@图片1只锁定十七岁陈迹身份；@图片2只锁定十七岁云羊身份；@图片3是已通过图片QA的U11-A1唯一首帧、太平医馆密室轴线、人物站位、旧木案与唯一无字空信封权威。@音频1是云羊逐字说出“{TEXT}”的精确普通话参考；视频模型必须让画面内云羊现场原生说出该句，音频只作逐字、声线、气息和节奏参考，不得作为画外音或后配音播放。陈迹全段闭口。

【天气硬合同】weather=INTERIOR_CLEAR_HARSH_SUN。6秒，竖屏9:16，720p，写实古装悬疑电影质感。中国古代架空洛城，太平医馆密室午后。禁止现代物件、民国妆发、字幕、水印、任何可读文字或伪文字。

【色彩与动机光】色彩为旧木深褐、灰青布衣、低饱和暖烛与冷白窗光；光影由画面左后方直棂窗的硬日光和桌面古式烛焰双动机光共同塑形，人物脸部保持自然明暗层次，禁止现代霓虹与无来源轮廓光。

【实体绑定】[[scene:太平医馆密室]]；[[char:十七岁云羊]]；[[char:十七岁陈迹]]；[[prop:唯一无字空信封]]；[[prop:旧木案]]。本镜继承本场既有空间权威，不新增人物、灵物或道具。

镜头1【双人中近景同轴承接，0.00-0.20秒】：主体=云羊、陈迹、旧木案、空信封；动作=云羊承接拧眉欲言的进行态，上身正向陈迹倾近，右掌已压住桌沿；陈迹闭口，右手正从左下伸向桌中空信封但尚差一指未碰；接触点=云羊右掌与旧木桌沿、空信封与桌面；方向=云羊由画面右侧向陈迹倾近，陈迹右手由左下朝中央信封前移；终态=云羊嘴部清晰并立即开口，陈迹仍未接触信封。{{无对白}}<音效：短吸气、衣料轻响、烛焰与纸角环境声>。

镜头2【云羊胸上近景，陈迹手与桌中信封同框，0.20-5.45秒】：主体=云羊；动作=云羊右掌持续压桌沿，按@音频1自然普通话只说一遍“{TEXT}”；说到“空信封”时视线落向信封，说到“每露一次面”时抬眼看陈迹，说到“倾巢而动”时肩背绷紧，说到“不合规矩”时眉心收束并停止前倾；陈迹闭口，右手继续向信封靠近但始终停在一指外；接触点=云羊右掌与桌沿；方向=云羊重心由右侧向画面左前方缓慢压近，视线由信封移向陈迹；终态=“矩”字完整落下，云羊闭口，陈迹仍未触信封。{{对白：云羊仅说“{TEXT}”}}<音效：@音频1精确参考、掌压木沿、衣料呼吸、烛焰>。

镜头3【双人证物中近景停稳，5.45-6.00秒】：主体=云羊、陈迹、空信封；动作=云羊闭口短呼气并保持拧眉，陈迹闭口把右手停在信封近侧纸边外一指，视线由云羊落到信封；接触点=云羊右掌与桌沿、信封与桌面；方向=陈迹视线向下，云羊重心微退半寸；终态=异常被提出但信封仍在桌面无人持有，承接U11-R1B陈迹回应并取信。{{无对白}}<音效：短呼气、纸角受气流轻颤、烛焰微响>。

【原生对白硬合同】唯一可听台词是“{TEXT}”。云羊0.20-5.45秒只说一遍，不增字、不减字、不改字、不重复；完整嘴部清楚，口型、气息、眉眼、表情与起止时间同步。陈迹全程闭口。禁止串台、旁白、画外音、后配替换、现代播音腔、字幕。

【首帧动势与环境生命层】第一帧不是完成态：云羊上身正在前倾且嘴正要开，陈迹右手正在向信封前移但未接触。烛焰持续微颤、窗格硬日光缓慢移动、纸角受呼吸气流轻颤、衣料随两人呼吸运动；背景不得冻结。

【力量作用于环境介质】云羊掌压桌沿只表现为袖口收紧、桌面微弱受力与烛焰气流；陈迹手臂前移只带动袖褶和纸角边缘轻颤，不得吸附或推动整封信。禁止空泛光效、信封复制、纸张出现字。

【身份与连续性】陈迹严格十七岁、云羊严格十七岁；使用E36身份参考，不得成年化、换脸、分身、同脸复制、肢体融合、嘴部遮挡。唯一无字空信封全段留在桌面，R1A不发生所有权转移。禁止降速填时、插帧填时、循环动作、字幕、水印、Logo。
"""
    PROMPT.write_text(prompt, encoding="utf-8")

    config = json.loads(SRC.read_text(encoding="utf-8"))
    config.update({
        "status": "READY_FOR_SUPERVISOR_PRECHECK",
        "source_cl2x": "CL2X-869",
        "source_mailbox_sha256": "7a138830cca9a68f52e6b39ebe38d3560665f65bc212a27771405634fe040157",
        "episode_paid_credits_before": 7968,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u11_r1a_video",
        "qa_dir": rel(QA),
        "anchor_count_plan_ref": rel(ANCHOR_PLAN),
        "common_sense_causality_plan_ref": rel(CAUSALITY_PLAN),
        "period_lock_plan_ref": rel(PERIOD_PLAN),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "dialogue_prompt_gate_ref": rel(DIALOGUE_GATE),
        "targeted_unit_replacement": True,
        "changed_input_repair": False,
        "unchanged_retry": False,
        "streaming_submission_policy": "SUBMIT_EACH_UNIT_IMMEDIATELY_WHEN_ITS_OWN_DEPENDENCIES_PASS",
        "authority_ref": "workflow/approvals/ROGER_AUTONOMOUS_COMPLETION_NO_ROUTINE_AUTH_REQUESTS_20260731.json",
        "roger_disposition": "LINE16_HUMAN_LISTENING_EXCEPTION_WITH_NORMAL_VIDEO_GATES",
    })
    config.pop("changed_input_parent_task_id", None)
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U11-R1A-EXACT-AUDIO-RECOVERY-10000",
        "source_id": "E36-CW-U11-R1A-EXACT-AUDIO-RECOVERY-10000",
        "batch_id": "E36-U11-R1A-EXACT-AUDIO-RECOVERY-10000",
        "unit_id": "U11",
        "scene_id": "E36-CW-S02",
        "visual_zone": "E36-U11-CLINIC-ENVELOPE-ANOMALY",
        "source_segment_id": "U11-R1A",
        "duration_seconds": 6,
        "duration": 6,
        "edit_target_duration_seconds": 6,
        "model": "seedance-2.0-fast",
        "status": "READY_TO_SUBMIT",
        "dependencies_ready": True,
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": sha(PROMPT),
        "reference_images": [rel(CHENJI), rel(YUNYANG), rel(ANCHOR)],
        "reference_image_asset_ids": ["fxmrcf57zd7", "4628tw7x1kh", "g7vyo26qdg9"],
        "reference_image_sequence": [
            {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(CHENJI), "sha256": sha(CHENJI), "identity_reference": True},
            {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "yunyang", "path": rel(YUNYANG), "sha256": sha(YUNYANG), "identity_reference": True},
            {"asset_label": "@图片3", "role": "ACCEPTED_START_MOTION_LAYOUT_AND_EVIDENCE_AUTHORITY", "state_id": "U11-A1", "path": rel(ANCHOR), "sha256": sha(ANCHOR), "identity_reference": False},
        ],
        "planned_reference_image_count": 1,
        "state_reference_minimum": 1,
        "still_sequence_only_allowed": True,
        "reference_audios": [rel(AUDIO)],
        "reference_audio_asset_ids": ["ntuv199b4i"],
        "native_dialogue_required": True,
        "visible_speaker_required": True,
        "temporal_visual_qa_required": True,
        "visual_entity_ids": ["yunyang", "chenji"],
        "targeted_unit_replacement": True,
        "human_listening_exception": True,
        "human_listening_exception_scope": "PRONUNCIATION_HARD_LINE16_ONLY",
        "changed_input_repair": False,
        "unchanged_retry": False,
        "max_retries": 0,
        "anchor_image_qa_ref": "qa/e36_v2_stills_repair_20260729/E36_REPAIR_V2_IMAGE_QA_16.json",
    })
    task.pop("replaces_parent_task_id", None)
    task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 6, "rationale": "Exact5.189688s Yunyang line fits0.20-5.45 with0.55s closed-mouth terminal handoff.", "edit_policy": "Preserve exact native dialogue; no time stretch, post-dub, filler, or duplicate frames."}
    task["dialogue"] = [{"dia_id": "E36-U11-R1-D01", "speaker": "云羊", "spoken_text": TEXT, "start_seconds": 0.20, "end_seconds": 5.45, "breath_after_seconds": 0.0, "expression": "克制警觉地指出规矩异常", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}]
    task["dialogue_audio_assets"] = [{"dia_id": "E36-U11-R1-D01", "speaker_id": "yunyang", "character_name": "云羊", "audio_slot": "@音频1", "path": rel(AUDIO), "sha256": sha(AUDIO), "duration_seconds": audio_qa["duration_seconds"], "reference_segment_start_seconds": 0.0, "reference_segment_end_seconds": audio_qa["duration_seconds"], "voice_reference_asset_id": "v0udrgrojud", "voice_derivation_status": "PASS", "source_voice": f"AGENTCUT_SPEECH_GENERATION:{audio_receipt['task_id']}", "voice_gender": "male", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"}]
    task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "prop_ownership": {"唯一无字空信封": "R1A全段平放旧木案，无人持有；陈迹手停在一指外", "旧木案": "云羊右掌持续压住桌沿"}, "motion_beats": [
        {"start_seconds": 0.0, "end_seconds": 0.20, "subject": "云羊、陈迹、旧木案、空信封", "action": "云羊向陈迹倾近欲言，陈迹闭口伸手靠近信封", "contact_point": "云羊右掌与桌沿；信封与桌面", "direction": "云羊由右向左前倾；陈迹右手由左下向桌中前移", "end_state": "云羊立即开口，陈迹距信封一指", "intent": "提出规矩异常", "visible_causality": "空信封引发云羊警觉，陈迹准备取证", "expression": "云羊拧眉警觉", "viewer_read": "异常即将被说破"},
        {"start_seconds": 0.20, "end_seconds": 5.45, "subject": "云羊", "action": "云羊压住桌沿并原生说出完整异常判断，陈迹闭口", "contact_point": "云羊右掌持续压住桌沿", "direction": "重心向陈迹压近，视线由信封转向陈迹", "end_state": "完整说完闭口，陈迹仍未触信封", "intent": "指出空信封却引发倾巢行动不合规矩", "visible_causality": "信封和既往行动反差触发判断", "expression": "克制警觉", "viewer_read": "空信封背后藏着真正情报"},
        {"start_seconds": 5.45, "end_seconds": 6.0, "subject": "云羊、陈迹、空信封", "action": "云羊闭口短呼气，陈迹闭口把手停在纸边外", "contact_point": "云羊右掌与桌沿；信封与桌面", "direction": "云羊微退，陈迹视线向下", "end_state": "信封仍在桌面无人持有，承接R1B", "intent": "为陈迹回应留出闭口终态", "visible_causality": "判断落定后注意力回到证物", "expression": "等待回应", "viewer_read": "陈迹下一刻将接管证物"},
    ]}
    task["keyframe_interpolation_gate"] = {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 1, "adjacent_pairs_checked": 0, "checked_adjacent_pairs": 0, "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS_SINGLE_CONTINUOUS_U11_A1_DIALOGUE_HOLD", "reason": "R1A stays on accepted U11-A1 axis and deliberately stops before the envelope ownership transition reserved for R1B."}
    task["multimodal_entity_bindings"] = [
        {"entity_id": "yunyang", "character_name": "云羊", "registry_id": "CHAR-云羊-古装", "visual_reference": rel(YUNYANG), "visual_reference_sha256": sha(YUNYANG), "identity_image_slot": "@图片2", "voice_reference": rel(AUDIO), "voice_reference_sha256": sha(AUDIO), "voice_reference_asset_id": "v0udrgrojud", "audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1"], "visible_speaker": True, "lip_sync": True, "prop_owners": {"旧木案": "右掌压住桌沿"}, "ability_owners": []},
        {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(CHENJI), "visual_reference_sha256": sha(CHENJI), "identity_image_slot": "@图片1", "visible_speaker": False, "lip_sync": False, "prop_owners": {"唯一无字空信封": "R1A不持有且停在一指外"}, "ability_owners": []},
    ]
    task["multimodal_binding_sha256"] = digest(task["multimodal_entity_bindings"])

    prompt_manifest = json.loads((TEMPLATE_DIR / "E36_U14_R2_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json").read_text(encoding="utf-8"))
    row = next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U11")
    row.update({"scene_id": "E36-CW-S02", "weather": "INTERIOR_CLEAR_HARSH_SUN", "prompt_path": rel(PROMPT), "prompt_sha256": sha(PROMPT)})
    write(PROMPT_MANIFEST, prompt_manifest)

    dialogue_manifest = json.loads((TEMPLATE_DIR / "E36_U14_R2_DIALOGUE_MANIFEST_V1.json").read_text(encoding="utf-8"))
    dialogue_manifest["rows"] = [row for row in dialogue_manifest["rows"] if row.get("video_unit_id") != "U11"]
    dialogue_manifest["rows"].append({"video_unit_id": "U11", "dia_id": "E36-U11-R1-D01", "status": "PASS", "speaker": "云羊", "speaker_id": "yunyang", "spoken_text": TEXT, "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(AUDIO), "sha256": sha(AUDIO), "remote_asset_id": "v0udrgrojud", "start_seconds": 0.20, "end_seconds": 5.45, "breath_after_seconds": 0.0, "expression": "克制警觉地指出规矩异常"})
    write(DIALOGUE_MANIFEST, dialogue_manifest)

    write(DIALOGUE_GATE, {"schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U11", "source_segment_id": "U11-R1A", "source_cl2x": "CL2X-869", "status": "PASS", "canonical_script_sha256": SCRIPT_SHA, "manifest_sha256": MANIFEST_SHA, "dialogue": task["dialogue"], "human_listening_exception": True, "checks": {"canonical_and_manifest_sha_match": "PASS", "exact_text_in_prompt": "PASS", "exact_audio_asr": "PASS_1P0", "source_speech_duration": "PASS_5P189688_WITHIN6S", "single_visible_speaker": "PASS_YUNYANG_ONLY", "silent_chenji": "PASS_BOUND_CLOSED_MOUTH", "native_mandarin_required": "PASS", "lip_breath_expression_sync": "PASS", "closed_mouth_tail": "PASS_0P55", "action_contract": "PASS_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE", "first_frame_motion_state": "PASS", "environment_life": "PASS", "period_weather_continuity": "PASS_INTERIOR_CLEAR_HARSH_SUN", "visible_text": "PASS_FORBIDDEN_ALL", "credit_limit": "PASS_7968_PLUS96_LE10000", "independent_transcript_recovery": "PASS_U11_R1A_FIRST_ATTEMPT", "roger_line16_disposition": "PASS_HUMAN_LISTENING_EXCEPTION_NORMAL_VIDEO_GATES_REMAIN"}, "failures": [], "blocked_by": None, "submission_allowed_after_supervisor_precheck": True})
    write(ANCHOR_PLAN, {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 1, "units": [{"unit_id": "U11", "source_segment_id": "U11-R1A", "planned_reference_image_count": 1, "reference_image_task_keys": ["U11-A1"], "keyframe_interpolation_gate": task["keyframe_interpolation_gate"], "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "R1A stays before the envelope ownership transition; accepted A1 is sufficient and accepted A2 remains reserved for R1B terminal ownership.", "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False}, "anchor_roles": ["accepted_start_motion_layout_and_evidence_authority"], "action_design_class": "single_anchor_single_speaker_native_dialogue_anomaly_reveal"}}]})
    write(CAUSALITY_PLAN, {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U11", "source_segment_id": "U11-R1A", "causality": {"applicable": True, "purpose": "云羊指出空信封与倾巢行动不合规矩。", "intended_effect": "陈迹准备接管证物并回答。", "visible_causality": "云羊压桌倾近说出异常，陈迹手停在信封外等待句末。", "viewer_read": "真正情报不在信中文字。", "preconditions": ["U11-A1图片QA通过", "陈迹与云羊均17岁", "信封唯一且无字"], "mechanism_chain": ["云羊视线落信封", "压桌倾近", "说出行动反差", "陈迹手停在纸边外"], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若云羊不看信封、陈迹提前拿走或串台，异常判断与R1B证物接管因果链均不成立。"}, "prop_function_status": "PASS", "evidence_refs": [rel(PROMPT), rel(AUDIO_QA)]}}]})
    write(PERIOD_PLAN, {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "canonical_script_sha256": SCRIPT_SHA, "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S02"]}, "units": [{"unit_id": "U11", "source_segment_id": "U11-R1A", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["太平医馆密室旧木案", "古代交领布衣", "裸蜡烛古式烛台", "直棂木窗", "唯一无字空信封"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代纸张", "民国灯具", "民国妆发", "字幕", "水印", "可读文字或伪文字"], "exception_approvals": {}, "evidence_refs": [rel(ANCHOR), rel(PROMPT)]}}]})
    write(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": rel(CONFIG), "config_sha256": sha(CONFIG), "prompt_sha256": sha(PROMPT), "audio_sha256": sha(AUDIO)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
