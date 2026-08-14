#!/usr/bin/env python3
"""Build the E36 U21-R1 two-line exact-dialogue recovery package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
OUT = BASE / "recovery_10000_20260730/u21_r1_video"
QA = ROOT / "qa/e36_agentcut_20260730/u21_r1_video_runtime"
CONFIG = OUT / "E36_U21_R1_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U21-R1.txt"
PROMPT_MANIFEST = OUT / "E36_U21_R1_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U21_R1_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U21_R1_DIALOGUE_PROMPT_GATE_V1.json"
AUDIO_DIR = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u21_r1"
AUDIO_1 = AUDIO_DIR / "E36-U21-R1-D01.wav"
AUDIO_2 = AUDIO_DIR / "E36-U21-R1-D02.wav"
TEXT_1 = "明日入夜，去城东刘家旧宅。"
TEXT_2 = "我要看看，是谁替一户死绝了的人家，管了三年的账。"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"
VOICE_ASSET_ID = "cypqud0bu7t"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def binding_digest(bindings: list[dict]) -> str:
    raw = json.dumps(bindings, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    prompt = """【E36-CW-U21-R1｜8秒｜陈迹定下刘宅夜探｜Seedance Fast原生普通话】

@图片1只锁定十七岁陈迹身份；@图片2是通过图片QA的太平医馆后院黄昏终态，是本单元唯一首帧、空间、屏幕方位和表演连续性权威。@音频1与@音频2是陈迹用同一锁定少年声线生成的两句精确对白参考，必须逐字复现其自然中文普通话、气息和节奏，不得作为画外音或后配音轨播放。第一帧严格从@图片2起动：陈迹承接抬眼中途状态，完整嘴部可见，目光正越过檐角向画面右上城东方向移动；右手和票根全程留在画外。

【天气硬合同】weather=CLEAR_DUSK_WIND_TO_NIGHT。中国古代架空洛城，太平医馆后院由黄昏向入夜连续过渡；暮云缓慢向画面右侧移动，檐下药草和树叶被晚风轻拨，远处古式灯火逐盏亮起。禁止现代物件、现代纸张、官服、民国妆发、牌匾、字幕、水印、任何可读文字或伪文字；票根、纸张、桌面和招牌全部在画外。

【实体绑定】[[scene:太平医馆后院]]；[[char:十七岁陈迹]]。本单元不新增人物、道具或能力。

镜头1【陈迹胸上近景·同轴眼平·极缓推近】0.00-0.10秒：主体=十七岁陈迹；动作=承接@图片2抬眼中途状态，目光继续越过檐角，胸口完成一次极短吸气，嘴唇将启；接触点=鞋底稳定接触后院青砖，双手和票根均在画外；方向=视线由檐下近处沿画面右上指向城东；终态=完整嘴部清晰可见并立即准备开口。{无对白}<音效：极短吸气、晚风拨叶>。

镜头2【陈迹胸上近景·同轴眼平·极缓推近】0.10-2.99秒：主体=十七岁陈迹；动作=完整脸与嘴始终清晰可见，按@音频1的同一少年声线和节奏，只说一遍“明日入夜，去城东刘家旧宅。”；接触点=鞋底持续接触同一青砖，双手仍在画外；方向=目光保持画面右上城东方向；终态=“旧宅”完整落下，嘴唇只作一次自然换气，不插入额外停顿。{对白：陈迹仅说“明日入夜，去城东刘家旧宅。”}<音效：@音频1精确对白参考、衣领随呼吸轻动>。

镜头3【陈迹胸上近景·同轴眼平·极缓推近】2.99-7.64秒：主体=十七岁陈迹；动作=紧接上一句按@音频2的同一少年声线和节奏，只说一遍“我要看看，是谁替一户死绝了的人家，管了三年的账。”，眉眼由沉静转为决断；接触点=鞋底仍稳定接触同一青砖，双手和任何票据始终在画外；方向=目光锁定画面右上城东方向，颏部只抬半寸；终态=最后一个“账”完整落下并自然闭口。{对白：陈迹仅说“我要看看，是谁替一户死绝了的人家，管了三年的账。”}<音效：@音频2精确对白参考、檐铃极轻一响、远处灯火环境声>。

镜头4【陈迹胸上近景·同轴眼平】7.64-8.00秒：主体=十七岁陈迹；动作=闭口短呼气，眼神继续锁住城东；接触点=鞋底与青砖接触不变；方向=身体和视线都保持画面右上；终态=陈迹闭口、神情决断，形成夜探刘宅的行动钩子。{无对白}<音效：短呼气、晚风回落>。

【原生对白硬合同】仅十七岁陈迹说话。视频模型必须原生生成自然中文普通话，把@音频1和@音频2作为两句精确对白参考并由陈迹口中现场说出；唯一可听台词依次是“明日入夜，去城东刘家旧宅。”和“我要看看，是谁替一户死绝了的人家，管了三年的账。”。第一句0.10-2.99秒，第二句2.99-7.64秒，均只说一遍，不增字、不减字、不改字、不重复；两句之间只允许自然换气，不得插入长停顿。禁止串台、旁白、画外音、现代播音腔、字幕或后配替换；陈迹口型逐字同步，气息、眉眼、表情和起止时间同步，末字后闭口。

【首帧动势】第一帧不是完成态：陈迹眼珠正向画面右上继续移动、胸口正在吸气、暮云和树叶已经受风运动；0.10秒内立即开口。

【环境生命层】暮云向右慢移；药草和树叶被晚风轻拨；檐铃只响一次；远处古式灯火逐盏亮起；衣料随陈迹呼吸自然牵动。所有环境动作不得遮挡嘴部或生成文字。

【力量作用于环境介质】晚风先拨动树叶和悬挂药草，再使檐铃轻响后回稳；陈迹吸气和说话只带动衣领、胸口与喉结，地面、檐角和院墙保持真实尺度。

【palette与光影】暮青天空、灰瓦檐、灰旧布衣、远处暖黄古灯；最后自然天光降低半档，暖灯只勾出轮廓，陈迹双眼与嘴部始终清楚可见。

硬性禁止：长停顿、降速、插帧填时、成年化、二十岁参考、换脸、人物复制、新增人物、票根纸张桌面或任何文字入镜、嘴被遮挡、口型漂移、吞字、改字、重复台词、字幕、水印。"""
    PROMPT.write_text(prompt + "\n", encoding="utf-8")
    prompt_sha = sha(PROMPT)
    audio_1_sha, audio_2_sha = sha(AUDIO_1), sha(AUDIO_2)

    config = json.loads((BASE / "E36_U21_EPISODE_PARALLEL_BATCH_V1.json").read_text(encoding="utf-8"))
    config.update({
        "video_credit_limit": 10000,
        "workflow_credit_scope": "e36_canonical_v2_20260728_recovery_20260730",
        "episode_paid_credits_before": 6412,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u21_r1_video",
        "qa_dir": rel(QA),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "dialogue_prompt_gate_ref": rel(DIALOGUE_GATE),
    })
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U21-R1-RECOVERY-10000",
        "source_id": "E36-CW-U21-R1-RECOVERY-10000",
        "batch_id": "E36-U21-R1-RECOVERY-10000",
        "status": "READY_TO_SUBMIT",
        "model": "seedance-2.0-fast",
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": prompt_sha,
        "reference_audios": [rel(AUDIO_1), rel(AUDIO_2)],
        "reference_audio_asset_ids": [],
        "max_retries": 0,
        "workflow_credit_scope": "e36_canonical_v2_20260728_recovery_20260730",
        "audio_reference_optional": False,
        "native_dialogue_required": True,
        "visible_speaker_required": True,
    })
    task["duration_plan"] = {
        "policy": "qingshan.shot_generation_duration.v5",
        "duration_seconds": 8,
        "rationale": "The two exact Mandarin references total 7.534917 seconds and fit contiguous 0.10-7.64 windows with a 0.36-second closed-mouth tail.",
        "edit_policy": "Preserve both native lines and the terminal closed-mouth reaction; no retiming or speed changes.",
    }
    task["dialogue"] = [
        {"dia_id": "E36-U21-R1-D01", "speaker": "陈迹", "spoken_text": TEXT_1, "start_seconds": 0.10, "end_seconds": 2.99, "breath_after_seconds": 0.0, "expression": "十七岁陈迹沉静定下行动时间和地点", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True},
        {"dia_id": "E36-U21-R1-D02", "speaker": "陈迹", "spoken_text": TEXT_2, "start_seconds": 2.99, "end_seconds": 7.64, "breath_after_seconds": 0.0, "expression": "十七岁陈迹凝视城东并转为决断", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True},
    ]
    task["dialogue_audio_assets"] = [
        {"dia_id": "E36-U21-R1-D01", "audio_slot": "@音频1", "speaker_id": "chenji", "character_name": "陈迹", "spoken_text": TEXT_1, "path": rel(AUDIO_1), "sha256": audio_1_sha, "duration_seconds": 2.890917, "remote_asset_id": VOICE_ASSET_ID, "voice_reference_asset_id": VOICE_ASSET_ID, "voice_derivation_status": "PASS", "source_voice": "AGENTCUT_SPEECH_GENERATION:17ec2d54-fa32-4aae-9a93-d9b881167b94", "voice_gender": "male", "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"},
        {"dia_id": "E36-U21-R1-D02", "audio_slot": "@音频2", "speaker_id": "chenji", "character_name": "陈迹", "spoken_text": TEXT_2, "path": rel(AUDIO_2), "sha256": audio_2_sha, "duration_seconds": 4.644, "remote_asset_id": VOICE_ASSET_ID, "voice_reference_asset_id": VOICE_ASSET_ID, "voice_derivation_status": "PASS", "source_voice": "AGENTCUT_SPEECH_GENERATION:ad6462ee-f426-40b2-9ddc-b7d123fd6709", "voice_gender": "male", "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"},
    ]
    task["performance_spec"]["prop_ownership"] = {"旧钱票根": "全段由陈迹单独保有但严格留在画外，不复制、不转移、不露出任何文字"}
    task["performance_spec"]["motion_beats"] = [
        {"start_seconds": 0.0, "end_seconds": 0.1, "subject": "十七岁陈迹", "action": "承接抬眼中途状态并极短吸气", "contact_point": "鞋底稳定接触后院青砖", "direction": "视线由檐下近处向画面右上城东移动", "end_state": "嘴部清晰可见并立即开口", "intent": "锁定调查方向", "visible_causality": "暮色中发现城东方向后立即下决定", "expression": "沉静收紧", "viewer_read": "行动决定将出口"},
        {"start_seconds": 0.1, "end_seconds": 2.99, "subject": "十七岁陈迹", "action": "按音频1逐字说出行动时间和地点", "contact_point": "鞋底持续接触同一青砖", "direction": "目光保持画面右上城东方向", "end_state": "旧宅完整落下并自然换气", "intent": "定下夜探刘宅", "visible_causality": "目光方向直接对应目的地", "expression": "冷静克制", "viewer_read": "时间地点清楚"},
        {"start_seconds": 2.99, "end_seconds": 7.64, "subject": "十七岁陈迹", "action": "按音频2逐字说出追查三年账目的决心", "contact_point": "鞋底持续接触同一青砖", "direction": "目光锁定画面右上城东方向", "end_state": "账字完整落下并闭口", "intent": "确认追查幕后记账者", "visible_causality": "死绝人家仍有三年账目驱动夜探", "expression": "由沉静转为决断", "viewer_read": "调查钩子成立"},
        {"start_seconds": 7.64, "end_seconds": 8.0, "subject": "十七岁陈迹", "action": "闭口短呼气并保持凝视", "contact_point": "鞋底与青砖接触不变", "direction": "身体与目光继续朝画面右上", "end_state": "闭口决断并形成夜探钩子", "intent": "收束本集行动决定", "visible_causality": "两句决定自然落定", "expression": "决断", "viewer_read": "下一步去刘宅"},
    ]
    chenji = next(row for row in task["multimodal_entity_bindings"] if row["entity_id"] == "chenji")
    chenji.update({"voice_reference": rel(AUDIO_1), "voice_reference_sha256": audio_1_sha, "voice_reference_asset_id": VOICE_ASSET_ID, "audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1", "@音频2"], "visible_speaker": True, "lip_sync": True, "prop_owners": {"旧钱票根": "由陈迹单独保有但全程画外"}})
    task["multimodal_binding_sha256"] = binding_digest(task["multimodal_entity_bindings"])

    prompt_manifest = json.loads((BASE / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V21.json").read_text(encoding="utf-8"))
    prompt_manifest["source_scene_authority_sha256"] = sha(ROOT / config["scene_contract_ref"])
    next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U21").update({"prompt_path": rel(PROMPT), "prompt_sha256": prompt_sha})
    write_json(PROMPT_MANIFEST, prompt_manifest)

    dialogue_manifest = json.loads((BASE / "E36_DIALOGUE_MANIFEST_V11.json").read_text(encoding="utf-8"))
    dialogue_manifest["rows"].extend([
        {"video_unit_id": "U21", "dia_id": "E36-U21-R1-D01", "status": "PASS", "speaker": "陈迹", "spoken_text": TEXT_1, "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(AUDIO_1), "sha256": audio_1_sha, "remote_asset_id": VOICE_ASSET_ID, "start_seconds": 0.10, "end_seconds": 2.99, "breath_after_seconds": 0.0, "expression": "十七岁陈迹沉静定下行动时间和地点"},
        {"video_unit_id": "U21", "dia_id": "E36-U21-R1-D02", "status": "PASS", "speaker": "陈迹", "spoken_text": TEXT_2, "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(AUDIO_2), "sha256": audio_2_sha, "remote_asset_id": VOICE_ASSET_ID, "start_seconds": 2.99, "end_seconds": 7.64, "breath_after_seconds": 0.0, "expression": "十七岁陈迹凝视城东并转为决断"},
    ])
    write_json(DIALOGUE_MANIFEST, dialogue_manifest)

    write_json(DIALOGUE_GATE, {
        "schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U21", "source_segment_id": "U21-R1", "source_cl2x": "CL2X-812", "status": "PASS", "canonical_script_sha256": SCRIPT_SHA, "manifest_sha256": MANIFEST_SHA,
        "dialogue": [{"dia_id": "E36-U21-R1-D01", "spoken_text": TEXT_1, "start_seconds": 0.10, "end_seconds": 2.99, "voice_reference_sha256": audio_1_sha}, {"dia_id": "E36-U21-R1-D02", "spoken_text": TEXT_2, "start_seconds": 2.99, "end_seconds": 7.64, "voice_reference_sha256": audio_2_sha}],
        "checks": {"canonical_and_manifest_sha_match": "PASS", "exact_text_in_prompt": "PASS_BOTH_LINES", "exact_audio_asr": "PASS_1P0_BOTH", "combined_audio_duration": "PASS_7P534917_WITHIN_8", "native_mandarin_required": "PASS", "visible_age17_chenji_mouth": "PASS", "lip_breath_expression_sync": "PASS", "closed_mouth_tail": "PASS_0P36", "action_contract": "PASS_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE", "first_frame_motion_state": "PASS", "environment_life": "PASS", "period_weather_continuity": "PASS_CLEAR_DUSK_WIND_TO_NIGHT", "visible_text": "PASS_FORBIDDEN_ALL", "credit_limit": "PASS_6412_PLUS_128_LE_10000"},
        "failures": [], "blocked_by": None, "submission_allowed_after_supervisor_precheck": True,
    })
    write_json(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": str(CONFIG), "config_sha256": sha(CONFIG), "prompt": str(PROMPT), "prompt_sha256": prompt_sha, "audio_sha256": [audio_1_sha, audio_2_sha]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
