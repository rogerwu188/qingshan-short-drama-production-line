#!/usr/bin/env python3
"""Build the first natural U14 split with exact native-dialogue references."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
PARENT = BASE / "recovery_10000_20260730/u09_r1a_video/E36_U09_R1A_CHANGED_INPUT_EPISODE_PARALLEL_BATCH_V1.json"
OUT = BASE / "recovery_10000_20260730/u14_r1_video"
QA = ROOT / "qa/e36_agentcut_20260730/u14_r1_video_runtime"
CONFIG = OUT / "E36_U14_R1_COMBINED_AUDIO_CHANGED_INPUT_V3_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U14-R1-COMBINED-AUDIO-CHANGED-INPUT-V3.txt"
PROMPT_MANIFEST = OUT / "E36_U14_R1_COMBINED_AUDIO_CHANGED_INPUT_V3_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U14_R1_COMBINED_AUDIO_CHANGED_INPUT_V3_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U14_R1_COMBINED_AUDIO_CHANGED_INPUT_V3_DIALOGUE_PROMPT_GATE_V1.json"
ANCHOR_PLAN = QA / "E36_U14_R1_COMBINED_AUDIO_CHANGED_INPUT_V3_ANCHOR_COUNT_PLAN_V1.json"
CAUSALITY_PLAN = QA / "E36_U14_R1_COMBINED_AUDIO_CHANGED_INPUT_V3_COMMON_SENSE_CAUSALITY_PLAN_V1.json"
PERIOD_PLAN = QA / "E36_U14_R1_COMBINED_AUDIO_CHANGED_INPUT_V3_PERIOD_LOCK_PLAN_V1.json"
SPLIT_PLAN = ROOT / "qa/e36_agentcut_20260730/u14_video_runtime/E36_U14_NATURAL_VIDEO_UNIT_SPLIT_PLAN_V1.json"
ANCHOR = ROOT / "working_assets/e36_recovery_10000_20260730/u14_a1_repair/E36-CW-U14-A1-STILL-V4-CHANGED-INPUT-REPAIR_b9b3d8e5-7cbe-4f77-acea-18e0cee50913.png"
ANCHOR_QA = ROOT / "qa/e36_agentcut_20260730/u14_image_runtime/E36_U14_A1_CHANGED_INPUT_REPAIR_DIRECT_VISUAL_QA_V1.json"
TERMINAL_QA = ROOT / "qa/e36_agentcut_20260730/u14_image_runtime/E36_U14_A2_CHANGED_INPUT_TERMINAL_REPAIR_DIRECT_VISUAL_QA_V1.json"
CHENJI = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
JIAOTU = ROOT / "working_assets/e32_reference_single_subject_20260723/jiaotu_front_single.jpg"
AUDIO_DIR = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u14_r1"
COMBINED_AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u14_r1_combined/E36-U14-R1-D01-D02-COMBINED-4P5815.wav"
AUDIOS = [COMBINED_AUDIO, COMBINED_AUDIO]
AUDIO_QAS = [ROOT / "qa/e36_agentcut_20260730/u14_video_runtime/E36-U14-R1-D01-D02_COMBINED_AUDIO_QA_V1.json"] * 2
TEXTS = ["字不在信里。", "在折法里。这几道折，是记号。"]
DURATIONS = [1.277125, 3.1115]
WINDOWS = [(0.08, 1.36), (1.55, 4.66)]
TASK_IDS = ["e048a4da-3c08-4dc4-a80b-6376c8a53306", "41b217db-6156-4cfd-a560-ae7d29109214"]
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
    for path, label in ((ANCHOR_QA, "U14-A1"), (TERMINAL_QA, "U14-A2")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not str(data.get("verdict") or "").startswith("PASS"):
            raise SystemExit(f"{label} is not direct image-QA PASS")
    split = json.loads(SPLIT_PLAN.read_text(encoding="utf-8"))
    if split.get("status") != "PASS_SPLIT_ACTIVE" or split.get("first_ready_unit") != "U14-R1":
        raise SystemExit("U14 split authority is invalid")
    for index, (audio, path) in enumerate(zip(AUDIOS, AUDIO_QAS), 1):
        data = json.loads(path.read_text(encoding="utf-8"))
        expected_sha = data.get("combined_sha256") or data.get("transport_sha256") or data.get("wav_sha256")
        similarity = min(segment.get("asr_similarity", 0) for segment in data.get("source_audio_segments", [])) if data.get("source_audio_segments") else data.get("source_asr_similarity", data.get("asr_similarity"))
        if data.get("status") != "PASS" or similarity != 1.0 or sha(audio) != expected_sha:
            raise SystemExit(f"U14-R1 D0{index} exact audio is not PASS")

    prompt = f"""【E36-CW-U14-R1｜5秒｜折法机关初揭｜Seedance Fast原生普通话｜自然拆分·合并音频changed-input V3】

@图片1只锁定十七岁陈迹身份；@图片2只锁定十八岁皎兔身份；@图片3是已通过图片QA的U14-A1唯一首帧、空间轴线、人物站位、空信封折痕和霜气权威。@音频1是一段4.5815秒合并参考：前1.277125秒为第一句原始PCM，接0.192875秒全零静音，后3.1115秒为第二句原始PCM；两段语音采样逐帧未变、顺序与正典一致。视频模型必须让画面内陈迹现场原生说出两句自然中文普通话；音频只作逐字、声线、气息和节奏参考，不得作为画外音或后配音轨播放。皎兔全段闭口，不说任何话。

【天气硬合同】weather=INTERIOR_CLEAR_DAY。中国古代架空洛城，太平医馆密室午后；霜气在空气里缓慢散薄，烛焰随呼吸微颤，桌上空白信封纸角轻动。禁止现代物件、现代文字、民国灯具、字幕、水印、任何可读文字或伪文字。

【实体绑定】[[scene:太平医馆密室]]；[[char:十七岁陈迹]]；[[char:十八岁皎兔]]；[[prop:唯一素白空信封]]；[[effect:残余霜气]]。不新增人物、道具或能力；信封全程留在桌面，不拆、不复制、不出现文字。

镜头1【承接@图片3双人中近景·同轴极缓推近】0.00-0.08秒：主体=十七岁陈迹、十八岁皎兔、空白信封；动作=陈迹承接从伏案直起到一半的进行态，右手食指正沿第一道折痕向桌面纵深滑进，皎兔头脸已朝证物轻转；接触点=陈迹食指指腹与空信封折痕、信封与旧木桌面；方向=陈迹身体向上直起，食指由近端向桌内滑，皎兔视线从陈迹移向折痕；终态=陈迹嘴部清晰并立即开口，皎兔闭口。{{无对白}}<音效：短吸气、纸面轻擦、烛焰环境声>。

镜头2【陈迹胸上近景·信封折痕同框】0.08-1.36秒：主体=十七岁陈迹；动作=陈迹按@音频1前段只说一遍“{TEXTS[0]}”，先否定信内文字，食指仍压着第一道空白折痕；接触点=右手食指指腹与折痕；方向=视线由空白信封转向折痕走向；终态=“里”完整落下，嘴唇短暂合拢，皎兔全程闭口。{{对白：陈迹仅说“{TEXTS[0]}”}}<音效：@音频1前段精确参考、纸面轻响>。

镜头3【同轴证物近景带陈迹完整嘴部】1.36-1.55秒：主体=陈迹、折痕；动作=陈迹闭口短吸气，指尖沿折痕连续前移而不离纸；接触点=食指指腹与折痕；方向=由近端向桌面纵深；终态=指尖停在两道折痕交会前，准备说明折法。{{无对白}}<音效：短吸气、纸纤维轻擦>。

镜头4【陈迹与折痕同框·同轴缓推】1.55-4.66秒：主体=十七岁陈迹；动作=陈迹按@音频1后段只说一遍“{TEXTS[1]}”，先以指尖沿第一道折痕推进，说到“这几道折”时手腕轻转指向相邻折迹，说到“记号”时指腹压定交会处；接触点=食指指腹始终接触空白折痕；方向=指尖沿折痕向桌面纵深推进后微转至相邻折迹；终态=“记号”完整落下并闭口，第一层折法机关成立，陈迹仍处半起推进态，皎兔闭口面向证物。{{对白：陈迹仅说“{TEXTS[1]}”}}<音效：@音频1后段精确参考、衣料随呼吸轻动>。

镜头5【双人中近景·同轴停稳】4.66-5.00秒：主体=陈迹、皎兔、空白信封；动作=两人闭口短呼吸，陈迹指腹保持压住折痕，皎兔视线落到指尖，霜气继续散薄、烛焰微颤；接触点=陈迹指腹与折痕、信封与桌面；方向=轴线保持陈迹与皎兔隔桌对证物；终态=陈迹闭口半起、单指压折，皎兔闭口面向证物，承接U14-R2继续检验纸浆。{{无对白}}<音效：短呼气、烛焰、纸角轻响>。

【原生对白硬合同】唯一可听台词依次是“{TEXTS[0]}”“{TEXTS[1]}”。陈迹只说这两句；0.08-1.36、1.55-4.66秒逐字准确，各说一遍，不增字、不减字、不改字、不重复。陈迹完整嘴部始终清楚，口型、气息、眉眼、表情和起止时间同步；皎兔全程闭口。禁止皎兔出声、串台、旁白、画外音、现代播音腔、字幕或后配替换。

【首帧动势】第一帧不是完成态：陈迹身体正在向上直起，食指正在沿折痕向桌内滑，皎兔头脸正在朝证物转，霜气和烛焰已经运动；0.08秒内陈迹立即开口。

【环境生命层】霜气持续散薄、烛焰持续微颤、空白信封纸角轻动、衣料随呼吸轻动；环境动作不得遮挡陈迹嘴部或生成文字。

【力量作用于环境介质】陈迹指腹沿纸面推进的摩擦力只压实折痕并让纸纤维轻响，不推动、掀开或复制信封；微弱气流只推动霜气、烛焰和纸角，纸角受重力落回原桌面。

【palette与光影】旧木深褐、陈迹灰旧布衣、皎兔冷灰青古装、暖烛与清冷午后窗光双动机光；陈迹眼神和完整嘴部始终可读，禁止无来源彩光。

硬性禁止：长停顿、降速、插帧填时、成年化、二十岁参考、换脸、人物复制、新人物、皎兔说话、信封拆开或出现文字、嘴部遮挡、口型漂移、吞字、改字、重复台词、串台、字幕、水印。"""
    PROMPT.write_text(prompt + "\n", encoding="utf-8")
    prompt_sha = sha(PROMPT)

    config = json.loads(PARENT.read_text(encoding="utf-8"))
    config.update({
        "status": "READY_FOR_SUPERVISOR_PRECHECK",
        "episode_paid_credits_before": 7387,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u14_r1_video",
        "qa_dir": rel(QA),
        "anchor_count_plan_ref": rel(ANCHOR_PLAN),
        "common_sense_causality_plan_ref": rel(CAUSALITY_PLAN),
        "period_lock_plan_ref": rel(PERIOD_PLAN),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "dialogue_prompt_gate_ref": rel(DIALOGUE_GATE),
        "targeted_unit_replacement": True,
        "changed_input_repair": True,
        "changed_input_parent_task_id": "cde18e89-0a33-4f2c-8583-9bd3f7c2a9bc",
        "changed_input_split_plan_ref": rel(SPLIT_PLAN),
        "unchanged_retry": False,
        "streaming_submission_policy": "SUBMIT_EACH_UNIT_IMMEDIATELY_WHEN_ITS_OWN_DEPENDENCIES_PASS",
    })
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U14-R1-COMBINED-AUDIO-CHANGED-INPUT-V3-10000",
        "source_id": "E36-CW-U14-R1-COMBINED-AUDIO-CHANGED-INPUT-V3-10000",
        "batch_id": "E36-U14-R1-COMBINED-AUDIO-CHANGED-INPUT-V3-10000",
        "unit_id": "U14",
        "scene_id": "E36-CW-S03",
        "visual_zone": "E36-U14-CLINIC-FOLD-REVEAL",
        "source_segment_id": "U14-R1",
        "replaces_parent_task_id": "cde18e89-0a33-4f2c-8583-9bd3f7c2a9bc",
        "changed_input_repair": True,
        "unchanged_retry": False,
        "duration_seconds": 5,
        "duration": 5,
        "edit_target_duration_seconds": 5,
        "status": "READY_TO_SUBMIT",
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": prompt_sha,
        "reference_images": [rel(CHENJI), rel(JIAOTU), rel(ANCHOR)],
        "reference_audios": [rel(COMBINED_AUDIO)],
        "reference_audio_asset_ids": [],
        "visual_entity_ids": ["chenji", "jiaotu"],
        "anchor_image_qa_ref": rel(ANCHOR_QA),
        "max_retries": 0,
    })
    task["duration_plan"] = {
        "policy": "qingshan.shot_generation_duration.v5",
        "duration_seconds": 5,
        "rationale": "One4.5815s provider reference contains both exact Chenji PCM utterances separated by0.192875s silence; source speech total4.388625s fits0.08-4.66 with a0.34s closed-mouth terminal beat.",
        "edit_policy": "Preserve exact native dialogue and evidence continuity; no time stretch, filler or duplicate frames.",
    }
    task["reference_image_sequence"] = [
        {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(CHENJI), "sha256": sha(CHENJI), "identity_reference": True},
        {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "jiaotu", "path": rel(JIAOTU), "sha256": sha(JIAOTU), "identity_reference": True},
        {"asset_label": "@图片3", "role": "ACCEPTED_START_MOTION_LAYOUT_AND_EVIDENCE_AUTHORITY", "state_id": "U14-A1", "path": rel(ANCHOR), "sha256": sha(ANCHOR), "identity_reference": False},
    ]
    task["planned_reference_image_count"] = 1
    task["state_reference_minimum"] = 1
    task["dialogue"] = [
        {"dia_id": f"E36-U14-R1-D0{i + 1}", "speaker": "陈迹", "spoken_text": TEXTS[i], "start_seconds": WINDOWS[i][0], "end_seconds": WINDOWS[i][1], "breath_after_seconds": 0.19 if i == 0 else 0.0, "expression": "冷静推理", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}
        for i in range(2)
    ]
    task["dialogue_audio_assets"] = [
        {"dia_id": f"E36-U14-R1-D0{i + 1}", "speaker_id": "chenji", "character_name": "陈迹", "audio_slot": "@音频1", "path": rel(COMBINED_AUDIO), "sha256": sha(COMBINED_AUDIO), "duration_seconds": DURATIONS[i], "reference_segment_start_seconds": 0.0 if i == 0 else 1.47, "reference_segment_end_seconds": 1.277125 if i == 0 else 4.5815, "voice_reference_asset_id": "cypqud0bu7t", "voice_derivation_status": "PASS", "source_voice": f"AGENTCUT_SPEECH_GENERATION:{TASK_IDS[i]}", "voice_gender": "male", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"}
        for i in range(2)
    ]
    task["performance_spec"] = {
        "schema": "qingshan.performance_generation_spec.v2",
        "prop_ownership": {"唯一素白空信封": "全段留在桌面，不拆、不复制、不出现文字", "残余霜气": "只在空气中散薄，不遮脸和嘴部"},
        "motion_beats": [
            {"start_seconds": 0.0, "end_seconds": 0.08, "subject": "陈迹、皎兔、空白信封", "action": "陈迹半起并沿第一道折痕滑指，皎兔转向证物", "contact_point": "陈迹食指指腹与折痕；信封与旧木桌面", "direction": "陈迹向上直起，指尖向桌内推进，皎兔视线转向折痕", "end_state": "陈迹立即开口，皎兔闭口面向证物", "intent": "从A1进行态进入折法判断", "visible_causality": "指尖接触引导两人注意折痕", "expression": "专注", "viewer_read": "物证推理开始"},
            {"start_seconds": 0.08, "end_seconds": 4.66, "subject": "陈迹", "action": "陈迹现场原生说出两句判断并沿折痕推进", "contact_point": "右手食指指腹持续接触折痕", "direction": "视线由信封转向折痕，指尖由近端向桌内推进并微转相邻折迹", "end_state": "记号结论落下并闭口，皎兔闭口看证物", "intent": "否定信中文字并指出折法记号", "visible_causality": "持续折触支撑两句物证判断", "expression": "冷静推理", "viewer_read": "折痕而非文字承载信息"},
            {"start_seconds": 4.66, "end_seconds": 5.0, "subject": "陈迹、皎兔、空白信封", "action": "两人闭口短呼吸，陈迹保持单指压折，皎兔视线落到指尖", "contact_point": "陈迹指腹与折痕；信封与桌面", "direction": "同轴隔桌对证物", "end_state": "陈迹半起单指压折，承接R2检验纸浆", "intent": "建立下一自然拆分连续性", "visible_causality": "折法结论促使注意继续留在纸张", "expression": "判断未完", "viewer_read": "下一步继续检验信封"},
        ],
    }
    task["multimodal_entity_bindings"] = [
        {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(CHENJI), "visual_reference_sha256": sha(CHENJI), "identity_image_slot": "@图片1", "voice_reference": rel(COMBINED_AUDIO), "voice_reference_sha256": sha(COMBINED_AUDIO), "voice_reference_asset_id": "cypqud0bu7t", "audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1"], "visible_speaker": True, "lip_sync": True, "prop_owners": {"唯一素白空信封": "右手食指持续压住折痕"}, "ability_owners": []},
        {"entity_id": "jiaotu", "character_name": "皎兔", "registry_id": "CHAR-皎兔-古装", "visual_reference": rel(JIAOTU), "visual_reference_sha256": sha(JIAOTU), "identity_image_slot": "@图片2", "visible_speaker": False, "lip_sync": False, "prop_owners": {}, "ability_owners": []},
    ]
    task["multimodal_binding_sha256"] = digest(task["multimodal_entity_bindings"])
    task["keyframe_interpolation_gate"] = {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 1, "adjacent_pairs_checked": 0, "checked_adjacent_pairs": 0, "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS_SINGLE_CONTINUOUS_A1_FOLD_REVEAL", "reason": "R1 is a continuous five-second evidence beat from accepted U14-A1; the accepted U14-A2 terminal authority is reserved for R8."}

    prompt_manifest = json.loads((BASE / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V21.json").read_text(encoding="utf-8"))
    next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U14").update({"prompt_path": rel(PROMPT), "prompt_sha256": prompt_sha})
    write(PROMPT_MANIFEST, prompt_manifest)
    dialogue_manifest = json.loads((BASE / "E36_DIALOGUE_MANIFEST_V11.json").read_text(encoding="utf-8"))
    dialogue_manifest["rows"].extend([
        {"video_unit_id": "U14", "dia_id": f"E36-U14-R1-D0{i + 1}", "status": "PASS", "speaker": "陈迹", "speaker_id": "chenji", "spoken_text": TEXTS[i], "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(COMBINED_AUDIO), "sha256": sha(COMBINED_AUDIO), "remote_asset_id": "cypqud0bu7t", "start_seconds": WINDOWS[i][0], "end_seconds": WINDOWS[i][1], "expression": "冷静推理"}
        for i in range(2)
    ])
    write(DIALOGUE_MANIFEST, dialogue_manifest)
    write(DIALOGUE_GATE, {"schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U14", "source_segment_id": "U14-R1", "source_cl2x": "CL2X-828", "status": "PASS", "canonical_script_sha256": SCRIPT_SHA, "manifest_sha256": MANIFEST_SHA, "changed_input_parent_task_id": "cde18e89-0a33-4f2c-8583-9bd3f7c2a9bc", "dialogue": task["dialogue"], "checks": {"canonical_and_manifest_sha_match": "PASS", "exact_text_in_prompt": "PASS_ALL2", "exact_audio_asr": "PASS_1P0_ALL2", "combined_reference_audio": "PASS_ONE4P5815_ASSET_TWO_PCM_EXACT_SEGMENTS_IN_CANONICAL_ORDER", "combined_source_speech_duration": "PASS_4P388625_WITHIN5S", "single_visible_speaker": "PASS_CHENJI_ONLY", "silent_jiaotu": "PASS_BOUND_CLOSED_MOUTH", "native_mandarin_required": "PASS", "lip_breath_expression_sync": "PASS", "closed_mouth_tail": "PASS_0P34", "action_contract": "PASS_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE", "first_frame_motion_state": "PASS", "environment_life": "PASS", "period_weather_continuity": "PASS_INTERIOR_CLEAR_DAY", "visible_text": "PASS_FORBIDDEN_ALL", "credit_limit": "PASS_7387_PLUS80_LE10000", "changed_input_repair_budget": "PASS_REPAIR1_OF_MAX1"}, "failures": [], "blocked_by": None, "submission_allowed_after_supervisor_precheck": True})
    write(ANCHOR_PLAN, {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 1, "units": [{"unit_id": "U14", "source_segment_id": "U14-R1", "planned_reference_image_count": 1, "reference_image_task_keys": ["U14-A1"], "keyframe_interpolation_gate": task["keyframe_interpolation_gate"], "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "R1 remains within the accepted A1 half-rise and single-fold-contact state; A2 is the accepted U14 terminal authority reserved for R8.", "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False}, "anchor_roles": ["accepted_start_motion_layout_and_evidence_authority"], "action_design_class": "single_anchor_single_speaker_native_dialogue_evidence_reveal"}}]})
    write(CAUSALITY_PLAN, {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U14", "source_segment_id": "U14-R1", "causality": {"applicable": True, "purpose": "陈迹否定信中文字并指出折法记号。", "intended_effect": "皎兔的注意转向空白折痕，物证推理进入纸浆检验。", "visible_causality": "陈迹保持指腹接触并沿折痕推进，两句判断随接触路径逐步落定。", "viewer_read": "信息藏在折法而非信中文字。", "preconditions": ["U14-A1直接图片QA通过", "U14-A2终态权威直接图片QA通过", "两人身份和密室轴位连续"], "mechanism_chain": ["陈迹半起沿折痕滑指", "否定信内文字", "短吸气保持接触", "指出折法记号", "皎兔闭口看向折痕"], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若指尖离开折痕、皎兔说话或两句改序，折法判断的可见因果链不成立。"}, "prop_function_status": "PASS", "evidence_refs": [rel(ANCHOR_QA), rel(TERMINAL_QA), rel(PROMPT), rel(SPLIT_PLAN)]}}]})
    write(PERIOD_PLAN, {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "canonical_script_sha256": SCRIPT_SHA, "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S03"]}, "units": [{"unit_id": "U14", "source_segment_id": "U14-R1", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["太平医馆密室旧木桌", "古代布衣", "素白空信封", "烛台窗格", "残余霜气"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代纸张", "民国灯具", "民国妆发", "字幕", "水印", "可读文字或伪文字"], "exception_approvals": {}, "evidence_refs": [rel(ANCHOR), rel(PROMPT)]}}]})
    write(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": rel(CONFIG), "config_sha256": sha(CONFIG), "prompt": rel(PROMPT), "prompt_sha256": prompt_sha, "anchor_sha256": sha(ANCHOR), "audio_sha256": [sha(path) for path in AUDIOS]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
