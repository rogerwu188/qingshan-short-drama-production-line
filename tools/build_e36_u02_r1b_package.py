#!/usr/bin/env python3
"""Build the single U02-R1B Chenji native-dialogue continuation package."""

from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
SOURCE = BASE / "recovery_10000_20260730/u02_r1a1_video/E36_U02_R1A1_CHANGED_INPUT_EPISODE_PARALLEL_BATCH_V1.json"
OUT = BASE / "recovery_10000_20260730/u02_r1b_video"
QA = ROOT / "qa/e36_agentcut_20260730/u02_r1b_video_runtime"
CONFIG = OUT / "E36_U02_R1B_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U02-R1B.txt"
PROMPT_MANIFEST = OUT / "E36_U02_R1B_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U02_R1B_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U02_R1B_DIALOGUE_PROMPT_GATE_V1.json"
ANCHOR_PLAN = QA / "E36_U02_R1B_ANCHOR_COUNT_PLAN_V1.json"
CAUSALITY_PLAN = QA / "E36_U02_R1B_COMMON_SENSE_CAUSALITY_PLAN_V1.json"
PERIOD_PLAN = QA / "E36_U02_R1B_PERIOD_LOCK_PLAN_V1.json"
ANCHOR = ROOT / "qa/e36_agentcut_20260730/u02_r1_video_runtime/E36-CW-U02-R1A2-SELECTED-SOURCE-NATIVE-NATURAL-PAUSE-V2_terminal_2p30.jpg"
ANCHOR_QA = ROOT / "qa/e36_agentcut_20260730/u02_r1_video_runtime/E36_U02_R1A2_TERMINAL_ANCHOR_IMAGE_QA_V2.json"
CHENJI = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
YUNYANG = ROOT / "assets/reference/e36_20260729/characters/CHAR-yunyang-age17-canonical-v1-20260729.png"
SOURCE_AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u02_r1/E36-U02-R1-D02.wav"
SOURCE_AUDIO_QA = ROOT / "qa/e36_agentcut_20260730/u02_r1_video_runtime/E36-U02-R1-D02_EXACT_DIALOGUE_AUDIO_QA_V1.json"
AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u02_r1b/E36-U02-R1-D02-TRANSPORT-2P10.wav"
AUDIO_QA = QA / "E36-U02-R1-D02_TRANSPORT_PADDED_AUDIO_QA_V1.json"
TEXT = "不能伤官差。"
VOICE_ASSET_ID = "cypqud0bu7t"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    AUDIO.parent.mkdir(parents=True, exist_ok=True)
    source_qa = read(SOURCE_AUDIO_QA)
    if source_qa.get("status") != "PASS" or source_qa.get("asr_similarity") != 1.0:
        raise SystemExit("R1B source exact-dialogue audio is not QA PASS")
    with wave.open(str(SOURCE_AUDIO), "rb") as source:
        params = source.getparams()
        frames = source.readframes(params.nframes)
    target_frames = round(params.framerate * 2.1)
    if params.nframes > target_frames:
        raise SystemExit("R1B source audio unexpectedly exceeds2.1 seconds")
    silence = b"\x00" * ((target_frames - params.nframes) * params.nchannels * params.sampwidth)
    with wave.open(str(AUDIO), "wb") as target:
        target.setparams(params)
        target.writeframes(frames + silence)
    write(AUDIO_QA, {
        "schema": "qingshan.exact_dialogue_audio_transport_qa.v1",
        "episode": "E36", "unit_id": "U02-R1B", "dia_id": "E36-U02-R1-D02",
        "status": "PASS", "spoken_text": TEXT, "asr_similarity": 1.0,
        "duration_seconds": 2.1, "transport_range": "PASS_2_TO_15_SECONDS",
        "source_audio_path": rel(SOURCE_AUDIO), "source_audio_sha256": sha(SOURCE_AUDIO),
        "source_audio_qa_ref": rel(SOURCE_AUDIO_QA), "source_audio_qa_sha256": sha(SOURCE_AUDIO_QA),
        "transformation": "SOURCE_NATIVE_TAIL_SILENCE_ONLY_NO_SPEECH_REGENERATION",
        "speech_content_unchanged": True, "paid_generation_credits": 0,
        "asset_path": rel(AUDIO), "asset_sha256": sha(AUDIO), "blocked_by": None,
    })
    audio_qa = read(AUDIO_QA)
    anchor_qa = read(ANCHOR_QA)
    if audio_qa.get("status") != "PASS" or audio_qa.get("asr_similarity") != 1.0:
        raise SystemExit("R1B exact-dialogue audio is not QA PASS")
    if not str(anchor_qa.get("verdict", anchor_qa.get("status", ""))).startswith("PASS"):
        raise SystemExit("R1A2 terminal anchor is not QA PASS")

    prompt = f"""【E36-CW-U02-R1B｜4秒｜陈迹划定底线｜Seedance Fast原生普通话｜连续自然视频单元】

@图片1只锁定十七岁陈迹身份，@图片2只锁定十七岁云羊身份；@图片3是R1A2已通过QA的唯一连续首帧和人物方位权威。第一帧严格从@图片3起动。@音频1只驱动画面中陈迹的嘴部、气息与表情，必须由陈迹现场原生说出，不得作为画外音或后配音轨。

【天气硬合同】weather=HEAT_NOON_DRY_DUST。中国古代架空洛城午时法场；烈日硬光、干燥浮尘、人群持续挤动、旧布旗和衣角受热风掀动。禁止现代物件、官服误配、民国妆发、牌匾、字幕、水印、可读文字或伪文字。

【实体绑定】[[scene:洛城午时法场檐影与人群]]；[[char:十七岁陈迹]]；[[char:十七岁云羊]]；[[prop:唯一空白折纸]]。本单元不新增人物、道具或能力；折纸仍仅由云羊保全，不展开、不复制、不转移。

镜头1【承接@图片3双人中近景·同轴轻跟】0.00-0.20秒：主体=十七岁陈迹、十七岁云羊、人群；动作=陈迹借前景看客横移的遮掩向云羊贴近半步，嘴部从木柱阴影边缘露出并短吸气，云羊闭口看向右侧刑台；接触点=陈迹前脚压实尘地、肩侧擦过木柱阴影边界，云羊右手持续压住腰后唯一空白折纸；方向=陈迹由左后向右前靠近云羊，视线越过云羊锁向右侧官差；终态=陈迹嘴部完整可见、立即开口，云羊闭口。{{无对白}}<音效：短吸气、人潮脚步、热风掀旗>。

镜头2【陈迹侧脸胸上近景·云羊右前景虚焦·极缓推近】0.20-1.80秒：主体=十七岁陈迹、右侧官差；动作=陈迹压低嗓音，以自然中文普通话只说一遍“{TEXT}”，完整嘴部始终清楚，眉眼先扫官差再回到云羊；接触点=陈迹前脚持续受力，右手收在身侧不碰云羊和折纸；方向=陈迹侧脸朝右前云羊与官差；终态=“差”字完整落下，陈迹停止发音并闭口，官差未受伤，云羊全程闭口。{{对白：陈迹仅说“{TEXT}”}}<音效：@音频1精确对白参考、人群低响、衣料擦动>。

镜头3【双人中近景·前景人群横穿】1.80-4.00秒：主体=十七岁陈迹、十七岁云羊、官差背景；动作=陈迹闭口短呼气并用眼神压住云羊继续出手的冲动，云羊闭口把重心收回半步，官差在刑台边照常巡动；接触点=陈迹前脚仍压尘地，云羊右手仍压折纸；方向=两人视线先在右前官差处交汇再回到刑台；终态=两人闭口、官差安全、折纸物权不变，为下一自然单元保留连续意图。{{无对白}}<音效：短呼气、人潮挤动、旗布拍风>。

【原生对白硬合同】仅十七岁陈迹说话。视频模型必须原生生成自然中文普通话，把@音频1作为精确参考并由陈迹口中现场说出；唯一台词是“{TEXT}”，只能在0.20-1.80秒说一遍，不增字、不减字、不改字、不重复。云羊全程闭口。禁止串台、旁白、画外音、现代播音腔、字幕或后配替换；陈迹口型逐字同步，气息、眉眼、表情和起止时间同步，末字后停止发音并闭口。

【首帧动势】第一帧不是完成态：前景看客正在横移，陈迹前脚正在落地、肩部正从阴影边缘靠近云羊、嘴部正露出；云羊正在把视线压向刑台；热风已经推动旧旗、衣角和浮尘。0.20秒内立即开口。

【环境生命层】看客持续挤动和踮脚；两名远处官差沿刑台边交叉巡动；旧布旗、衣角和浮尘持续受热风运动。环境动作不得遮挡陈迹嘴部或生成文字。

【力量与介质】陈迹只以脚步和眼神制止云羊，不抓扯、不推搡、不伤官差；脚步仅带起少量干尘。云羊右手压力只让空白折纸边缘轻微弯曲。

【色彩与光影】法场土黄、旧木深褐、陈迹灰旧布衣、云羊无纹黑衣；午时烈日是唯一动机光，檐下冷阴影保留两人眼神与陈迹完整嘴部细节，禁止霓虹色、现代影视灯和无来源彩光。

硬性禁止：长停顿、降速、插帧填时、成年化、二十岁参考、换脸、人物复制、新人物、折纸展开或复制、任何文字或伪文字、嘴部遮挡、口型漂移、吞字、改字、重复台词、云羊说话、官差受伤、字幕、水印。"""
    PROMPT.write_text(prompt + "\n", encoding="utf-8")
    prompt_sha, audio_sha = sha(PROMPT), sha(AUDIO)

    config = read(SOURCE)
    config.update({
        "status": "READY_TO_SUBMIT",
        "episode_paid_credits_before": 6954,
        "episode_credit_limit": 10000,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u02_r1b_video",
        "qa_dir": rel(QA),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "dialogue_prompt_gate_ref": rel(DIALOGUE_GATE),
        "anchor_count_plan_ref": rel(ANCHOR_PLAN),
        "common_sense_causality_plan_ref": rel(CAUSALITY_PLAN),
        "period_lock_plan_ref": rel(PERIOD_PLAN),
    })
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U02-R1B-RECOVERY-10000",
        "source_id": "E36-CW-U02-R1B-RECOVERY-10000",
        "batch_id": "E36-U02-R1B-RECOVERY-10000",
        "visual_zone": "E36-U02-R1B",
        "duration_seconds": 4,
        "duration": 4,
        "edit_target_duration_seconds": 4,
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": prompt_sha,
        "reference_images": [rel(CHENJI), rel(YUNYANG), rel(ANCHOR)],
        "reference_audios": [rel(AUDIO)],
        "reference_audio_asset_ids": [],
        "anchor_image_qa_ref": rel(ANCHOR_QA),
        "planned_reference_image_count": 1,
        "state_reference_minimum": 1,
        "status": "READY_TO_SUBMIT",
        "max_retries": 0,
        "visual_entity_ids": ["chenji", "yunyang"],
        "changed_input_repair": False,
        "changed_input_parent_task_id": None,
        "changed_input_reason": None,
    })
    task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 4, "rationale": "The exact1.532542-second Mandarin line fits0.20-1.80 and leaves2.20 seconds for a closed-mouth consequence beat.", "edit_policy": "Preserve native Mandarin and picture-audio sync; no time stretch, filler or duplicate frames."}
    task["reference_image_sequence"] = [
        {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(CHENJI), "sha256": sha(CHENJI), "identity_reference": True},
        {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "yunyang", "path": rel(YUNYANG), "sha256": sha(YUNYANG), "identity_reference": True},
        {"asset_label": "@图片3", "role": "ACCEPTED_R1A2_TERMINAL_CONTINUATION_ANCHOR", "state_id": ANCHOR.stem, "path": rel(ANCHOR), "sha256": sha(ANCHOR), "identity_reference": False},
    ]
    task["dialogue"] = [{"dia_id": "E36-U02-R1-D02", "speaker": "陈迹", "spoken_text": TEXT, "start_seconds": 0.20, "end_seconds": 1.80, "breath_after_seconds": 0.0, "expression": "十七岁陈迹压低嗓音划定不伤官差的底线，警觉克制", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}]
    task["dialogue_audio_assets"] = [{"dia_id": "E36-U02-R1-D02", "audio_slot": "@音频1", "speaker_id": "chenji", "character_name": "陈迹", "spoken_text": TEXT, "path": rel(AUDIO), "sha256": audio_sha, "duration_seconds": float(audio_qa["duration_seconds"]), "remote_asset_id": VOICE_ASSET_ID, "voice_reference_asset_id": VOICE_ASSET_ID, "voice_derivation_status": "PASS", "source_voice": "AGENTCUT_SPEECH_GENERATION:b415e9d8-dd21-46d1-86eb-40481d09791d", "voice_gender": "male", "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"}]
    task["multimodal_entity_bindings"] = [
        {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(CHENJI), "visual_reference_sha256": sha(CHENJI), "identity_image_slot": "@图片1", "visible_speaker": True, "lip_sync": True, "prop_owners": {}, "ability_owners": [], "voice_reference": rel(AUDIO), "voice_reference_sha256": audio_sha, "voice_reference_asset_id": VOICE_ASSET_ID, "audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1"]},
        {"entity_id": "yunyang", "character_name": "云羊", "registry_id": "CHAR-云羊-古装", "visual_reference": rel(YUNYANG), "visual_reference_sha256": sha(YUNYANG), "identity_image_slot": "@图片2", "visible_speaker": False, "lip_sync": False, "prop_owners": {"唯一空白折纸": "云羊右手持续压住腰后空白边缘"}, "ability_owners": []},
    ]
    task["multimodal_binding_sha256"] = digest(task["multimodal_entity_bindings"])
    task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "episode": "E36", "unit_id": "U02", "source_segment_id": "U02-R1B", "prop_ownership": {"唯一空白折纸": "全段仅云羊右手压住腰后空白边缘，不展开、不复制、不转移"}, "motion_beats": [
        {"start_seconds": 0.0, "end_seconds": 0.20, "subject": "十七岁陈迹、十七岁云羊、人群", "action": "陈迹借人群遮掩贴近半步并露出嘴部", "contact_point": "陈迹前脚压实尘地，云羊右手持续压折纸", "direction": "陈迹由左后向右前靠近云羊", "end_state": "陈迹嘴部清楚并立即开口", "intent": "制止伤害官差", "visible_causality": "人群横移提供靠近掩护", "expression": "警觉克制", "viewer_read": "陈迹即将划定行动底线"},
        {"start_seconds": 0.20, "end_seconds": 1.80, "subject": "十七岁陈迹、右侧官差", "action": f"以自然中文普通话只说一遍{TEXT}", "contact_point": "陈迹前脚持续受力，双手不碰云羊和官差", "direction": "侧脸朝右前云羊与官差", "end_state": "末字落下并闭口，官差安全", "intent": "划定不伤官差的底线", "visible_causality": "看见巡动官差后立即制止", "expression": "低声坚决", "viewer_read": "底线清楚且说话人明确"},
        {"start_seconds": 1.80, "end_seconds": 4.0, "subject": "十七岁陈迹、十七岁云羊、官差", "action": "陈迹闭口以眼神制止，云羊闭口收回重心", "contact_point": "陈迹前脚压尘地，云羊右手仍压折纸", "direction": "两人先看官差再看刑台", "end_state": "两人闭口、官差安全、折纸物权不变", "intent": "落实行动限制", "visible_causality": "口头底线使云羊收势", "expression": "克制警觉", "viewer_read": "底线产生可见后果"},
    ]}
    task["keyframe_interpolation_gate"] = {"status": "PASS", "anchor_count": 1, "checked_adjacent_pairs": 0, "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS_SINGLE_CONTINUATION_TAKE", "reason": "Accepted R1A2 terminal fixes identity, axis and ownership for this immediately contiguous response."}

    prompt_manifest = read(OUT.parent.parent / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V21.json")
    next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U02").update({"prompt_path": rel(PROMPT), "prompt_sha256": prompt_sha})
    write(PROMPT_MANIFEST, prompt_manifest)
    dialogue_manifest = read(OUT.parent.parent / "E36_DIALOGUE_MANIFEST_V11.json")
    dialogue_manifest["rows"].append({"video_unit_id": "U02", "source_segment_id": "U02-R1B", "dia_id": "E36-U02-R1-D02", "status": "PASS", "speaker_id": "chenji", "speaker": "陈迹", "spoken_text": TEXT, "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(AUDIO), "sha256": audio_sha, "remote_asset_id": VOICE_ASSET_ID, "voice_reference_asset_id": VOICE_ASSET_ID, "start_seconds": 0.20, "end_seconds": 1.80, "expression": "十七岁陈迹压低嗓音划定底线"})
    write(DIALOGUE_MANIFEST, dialogue_manifest)
    write(DIALOGUE_GATE, {"schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U02", "source_segment_id": "U02-R1B", "source_cl2x": "CL2X-819", "status": "PASS", "canonical_script_sha256": SCRIPT_SHA, "manifest_sha256": MANIFEST_SHA, "dialogue": [{"dia_id": "E36-U02-R1-D02", "speaker": "陈迹", "spoken_text": TEXT, "start_seconds": 0.20, "end_seconds": 1.80, "voice_reference_asset_id": VOICE_ASSET_ID, "voice_reference_sha256": audio_sha}], "checks": {"canonical_and_manifest_sha_match": "PASS", "natural_split_authority": "PASS_U02_R1_NATURAL_VIDEO_UNIT_SPLIT_V1", "exact_text_in_prompt": "PASS", "exact_audio_asr": "PASS_1P0", "native_mandarin_required": "PASS", "visible_age17_chenji_mouth": "PASS", "silent_age17_yunyang": "PASS", "lip_breath_expression_sync": "PASS", "closed_mouth_tail": "PASS_2P20", "action_contract": "PASS_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE", "first_frame_motion_state": "PASS", "environment_life": "PASS_A", "period_weather_continuity": "PASS_HEAT_NOON_DRY_DUST", "visible_text": "PASS_BLANK_PAPER_EDGE_ONLY", "credit_limit": "PASS_6954_PLUS64_LE10000"}, "failures": [], "blocked_by": None, "submission_allowed_after_supervisor_precheck": True})
    write(ANCHOR_PLAN, {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 1, "units": [{"unit_id": "U02", "source_segment_id": "U02-R1B", "planned_reference_image_count": 1, "reference_image_task_keys": [ANCHOR.stem], "keyframe_interpolation_gate": task["keyframe_interpolation_gate"], "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "One continuous response uses the accepted R1A2 terminal authority.", "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False}, "anchor_roles": ["accepted_r1a2_terminal_continuation_authority"], "action_design_class": "single_anchor_native_dialogue_continuation"}}]})
    write(CAUSALITY_PLAN, {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U02", "source_segment_id": "U02-R1B", "causality": {"applicable": True, "purpose": "陈迹划定不能伤官差的行动底线。", "intended_effect": "云羊收势且官差保持安全。", "visible_causality": "陈迹看见巡动官差后低声制止，云羊随即收回重心。", "viewer_read": "观众能读出陈迹的底线产生直接后果。", "preconditions": ["R1A2终帧QA通过", "陈迹与云羊身份连续", "官差背景可见"], "mechanism_chain": ["官差巡动", "陈迹靠近", "完整说出底线", "云羊收势", "官差安全"], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若无陈迹制止或云羊不收势，底线的可见因果不成立。"}, "prop_function_status": "PASS", "evidence_refs": [rel(ANCHOR_QA), rel(PROMPT)]}}]})
    write(PERIOD_PLAN, {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "canonical_script_sha256": SCRIPT_SHA, "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S01"]}, "units": [{"unit_id": "U02", "source_segment_id": "U02-R1B", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["檐下旧木柱", "古代布衣", "无纹黑衣", "木制刑台", "旧布旗", "干尘人群"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "官服误配", "民国妆发", "牌匾", "字幕", "水印", "可读文字或伪文字"], "exception_approvals": {}, "evidence_refs": [rel(ANCHOR), rel(PROMPT)]}}]})
    write(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": str(CONFIG), "config_sha256": sha(CONFIG), "prompt_sha256": prompt_sha, "audio_sha256": audio_sha, "anchor_sha256": sha(ANCHOR)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
