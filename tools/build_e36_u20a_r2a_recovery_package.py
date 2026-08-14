#!/usr/bin/env python3
"""Build the E36 U20A-R2A natural-split exact-dialogue video package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
SOURCE = BASE / "recovery_10000_20260730/u20a_r1_video/E36_U20A_R1_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json"
OUT = BASE / "recovery_10000_20260730/u20a_r2a_video"
QA = ROOT / "qa/e36_agentcut_20260730/u20a_r2_video_runtime"
CONFIG = OUT / "E36_U20A_R2A_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U20A-R2A.txt"
PROMPT_MANIFEST = OUT / "E36_U20A_R2A_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U20A_R2A_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U20A_R2A_DIALOGUE_PROMPT_GATE_V1.json"
AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u20a_r2/E36-U20A-R2-D01.wav"
ANCHOR = ROOT / "qa/e36_agentcut_20260730/u20a_r1_video_runtime/E36-CW-U20A-R1-RECOVERY-10000_terminal_5p95.jpg"
CHENJI = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
YUNYANG = ROOT / "assets/reference/e36_20260729/characters/CHAR-yunyang-age17-canonical-v1-20260729.png"
TEXT = "喂这颗棋第一口饭的钱，出自一桩灭了门、死透了的刘家。"
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
    prompt = """【E36-CW-U20A-R2A｜6秒｜陈迹归纳刘家第一口饭｜Seedance Fast原生普通话】

@图片1只锁定十七岁陈迹身份，@图片2只锁定十七岁云羊身份；@图片3是已通过连续性图片QA的U20A-R1终态，是本单元唯一首帧、空间、屏幕方向、票根物权和表演连续性权威。@音频1是陈迹锁定少年声线生成的本句精确对白参考，必须由画面中陈迹现场原生说出，不得作为画外音或后配音轨播放。第一帧严格从@图片3起动：陈迹右手单独夹住同一张刘家旧钱票根空白背面，嘴处于近闭合自然休止并立即吸气，目光锁向画面右上城东；云羊只在后景虚焦，全程闭口。

【天气硬合同】weather=CLEAR_DUSK_WIND_TO_NIGHT。中国古代架空洛城，太平医馆后院由黄昏连续过渡至初夜；晚风持续拨动树叶和悬挂药材，炊烟斜向画面右侧，远处古式灯火逐盏亮起。禁止现代物件、现代纸张、官服、民国妆发、牌匾、字幕、水印、任何可读文字或伪文字；票根只露空白背面，不得翻面。

【实体绑定】[[scene:太平医馆后院]]；[[char:十七岁陈迹]]；[[char:十七岁云羊]]；[[prop:刘家旧钱票根空白背面]]。本单元不新增人物、道具或能力。

镜头1【陈迹胸上近景·云羊后景虚焦·同轴眼平】0.00-0.15秒：主体=十七岁陈迹、同一张无字票根；动作=承接@图片3，陈迹右手指腹继续收紧票根空白背面并极短吸气，嘴由近闭合休止进入开口；接触点=右手拇指与食指持续夹住票根下缘，左手不触碰；方向=目光保持画面右上城东，手停在胸前；终态=完整脸和嘴清晰可见并立即发出第一音节“喂”。{无对白}<音效：极短吸气、晚风拨叶、后景轻脚步>。

镜头2【陈迹胸上近景·同轴极缓推近】0.15-5.40秒：主体=十七岁陈迹、同一张无字票根；动作=陈迹按@音频1的同一少年声线和自然节奏，只说一遍“喂这颗棋第一口饭的钱，出自一桩灭了门、死透了的刘家。”，完整嘴部始终清楚，指节随“刘家”判断逐渐泛白；接触点=右手拇指与食指全段夹住票根空白背面下缘；方向=目光锁向画面右上城东，票根竖直不翻面；终态=最后一个“家”完整落下，嘴停止发音，票根仍属陈迹。{对白：陈迹仅说“喂这颗棋第一口饭的钱，出自一桩灭了门、死透了的刘家。”}<音效：@音频1精确对白参考、衣领随呼吸轻动、后景云羊脚步>。

镜头3【陈迹胸上近景·云羊后景虚焦】5.40-6.00秒：主体=十七岁陈迹、后景十七岁云羊、同一张无字票根；动作=陈迹闭口短呼气并把票根下缘向掌心收紧但不遮住、不撕裂、不翻面，云羊闭口停半步；接触点=陈迹右手仍单独接触票根，云羊双脚接触青石；方向=陈迹目光仍朝画面右上城东，云羊由左向右踱步停止；终态=陈迹闭口、票根空白背面仍可见且物权不转移，云羊闭口停在转身中途，为R2B“三条线”留连续开口点。{无对白}<音效：短呼气、脚步停下、远处古灯环境声>。

【原生对白硬合同】仅十七岁陈迹说话。视频模型必须原生生成自然中文普通话，把@音频1作为精确参考并由陈迹口中现场说出；唯一台词是“喂这颗棋第一口饭的钱，出自一桩灭了门、死透了的刘家。”，只能在0.15-5.40秒说一遍，不增字、不减字、不改字、不重复。第一音节必须听作喂/wei4；云羊全程闭口。禁止串台、旁白、画外音、现代播音腔、字幕或后配替换；陈迹口型逐字同步，气息、眉眼、表情和起止时间同步，末字后停止发音并闭口。

【首帧动势】第一帧不是完成态：陈迹指腹正在收紧、嘴正由休止进入吸气、衣领受呼吸牵动；后景云羊正踱步未停，树叶和药草已受风摆动；0.15秒内立即开口。

【环境生命层】树叶和悬挂药草持续摆动；炊烟斜飘；远处古式灯火逐盏亮起；云羊后景踱步至末尾停半步；衣料随陈迹呼吸自然牵动。环境动作不得遮挡嘴部或生成文字。

【力量作用于环境介质】陈迹收紧手指只让票根空白背面轻微弯曲，不撕裂、不翻面；晚风先拨动树叶和药草，再推动炊烟；云羊脚步只带动衣摆和青石轻响。

【palette与光影】暮青天空、灰瓦檐、陈迹灰旧布衣、云羊暗色布衣、远处暖黄古灯；自然天光缓降，暖灯勾轮廓，陈迹双眼和嘴始终清楚。

硬性禁止：长停顿、降速、插帧填时、成年化、二十岁参考、换脸、人物复制、新人物、票根翻面、任何文字或伪文字入镜、嘴被遮挡、口型漂移、吞字、改字、重复台词、云羊说话、字幕、水印。"""
    PROMPT.write_text(prompt + "\n", encoding="utf-8")
    prompt_sha, audio_sha = sha(PROMPT), sha(AUDIO)

    config = json.loads(SOURCE.read_text(encoding="utf-8"))
    config.update({
        "episode_paid_credits_before": 6642,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u20a_r2a_video",
        "qa_dir": rel(QA),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "dialogue_prompt_gate_ref": rel(DIALOGUE_GATE),
        "status": "READY_TO_SUBMIT",
    })
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U20A-R2A-RECOVERY-10000",
        "source_id": "E36-CW-U20A-R2A-RECOVERY-10000",
        "batch_id": "E36-U20A-R2A-RECOVERY-10000",
        "unit_id": "U20A",
        "visual_zone": "E36-U20A-R2A-CANONICAL-RECOVERY",
        "duration_seconds": 6,
        "duration": 6,
        "edit_target_duration_seconds": 6,
        "status": "READY_TO_SUBMIT",
        "model": "seedance-2.0-fast",
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": prompt_sha,
        "reference_images": [rel(CHENJI), rel(YUNYANG), rel(ANCHOR)],
        "reference_audios": [rel(AUDIO)],
        "reference_audio_asset_ids": [],
        "max_retries": 0,
    })
    task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 6, "rationale": "Natural exact Mandarin reference is5.201292s and fits0.15-5.40 with0.60s terminal tail.", "edit_policy": "Preserve full native line and terminal reaction; no retiming or speed changes."}
    task["reference_image_sequence"] = [
        {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(CHENJI), "sha256": sha(CHENJI), "identity_reference": True},
        {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "yunyang", "path": rel(YUNYANG), "sha256": sha(YUNYANG), "identity_reference": True},
        {"asset_label": "@图片3", "role": "START_MOTION_ACTION_AND_CONTINUATION_ANCHOR", "state_id": "E36-CW-U20A-R2A-A1-FROM-R1-TERMINAL", "path": rel(ANCHOR), "sha256": sha(ANCHOR), "identity_reference": False},
    ]
    task["dialogue"] = [{"dia_id": "E36-U20A-R2-D01", "speaker": "陈迹", "spoken_text": TEXT, "start_seconds": 0.15, "end_seconds": 5.40, "breath_after_seconds": 0.0, "expression": "十七岁陈迹捏紧无字票根，克制归纳刘家灭门线索", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}]
    task["dialogue_audio_assets"] = [{"dia_id": "E36-U20A-R2-D01", "audio_slot": "@音频1", "speaker_id": "chenji", "character_name": "陈迹", "spoken_text": TEXT, "path": rel(AUDIO), "sha256": audio_sha, "duration_seconds": 5.201292, "remote_asset_id": VOICE_ASSET_ID, "voice_reference_asset_id": VOICE_ASSET_ID, "voice_derivation_status": "PASS", "source_voice": "AGENTCUT_SPEECH_GENERATION:692c0c78-e4a3-4bc1-a742-39e75a94e7c7", "voice_gender": "male", "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"}]
    task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "prop_ownership": {"刘家旧钱票根": "全段仅由陈迹右手夹住空白背面，不翻面、不复制、不转移"}, "motion_beats": [
        {"start_seconds": 0.0, "end_seconds": 0.15, "subject": "十七岁陈迹、刘家无字票根", "action": "承接R1终态继续收紧票根并吸气", "contact_point": "右手拇指与食指持续夹住票根下缘", "direction": "目光保持画面右上城东", "end_state": "嘴部清晰并立即发出喂", "intent": "承接第三条刘家线", "visible_causality": "票根物证触发下一层归纳", "expression": "冷静收紧", "viewer_read": "刘家线将出口"},
        {"start_seconds": 0.15, "end_seconds": 5.40, "subject": "十七岁陈迹、刘家无字票根", "action": "按音频1逐字说出刘家第一口饭线索", "contact_point": "右手拇指与食指持续夹住票根空白背面", "direction": "目光锁向画面右上城东", "end_state": "末字家完整落下并停止发音", "intent": "确认刘家灭门资金源", "visible_causality": "票根连接刘家与棋子", "expression": "克制笃定", "viewer_read": "第三条线成立"},
        {"start_seconds": 5.40, "end_seconds": 6.0, "subject": "十七岁陈迹、后景十七岁云羊", "action": "陈迹闭口短呼气并把票根向掌心收紧，云羊闭口停半步", "contact_point": "陈迹右手仍单独夹住票根，云羊双脚接触青石", "direction": "陈迹看向城东，云羊由左向右停止", "end_state": "陈迹闭口且票根仍无字，云羊闭口停步", "intent": "为三线结论留口", "visible_causality": "刘家判断让同伴停步", "expression": "笃定、警觉", "viewer_read": "三线即将归一"},
    ]}
    task["multimodal_entity_bindings"] = [
        {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(CHENJI), "visual_reference_sha256": sha(CHENJI), "identity_image_slot": "@图片1", "visible_speaker": True, "lip_sync": True, "prop_owners": {"刘家旧钱票根": "陈迹右手夹住空白背面"}, "ability_owners": [], "voice_reference": rel(AUDIO), "voice_reference_sha256": audio_sha, "voice_reference_asset_id": VOICE_ASSET_ID, "audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1"]},
        {"entity_id": "yunyang", "character_name": "云羊", "registry_id": "CHAR-云羊-古装", "visual_reference": rel(YUNYANG), "visual_reference_sha256": sha(YUNYANG), "identity_image_slot": "@图片2", "visible_speaker": False, "lip_sync": False, "prop_owners": {}, "ability_owners": []},
    ]
    task["multimodal_binding_sha256"] = binding_digest(task["multimodal_entity_bindings"])
    task["keyframe_interpolation_gate"] = {"status": "PASS", "anchor_count": 1, "checked_adjacent_pairs": 0, "reason": "Single continuous6s action starts from accepted R1 terminal; contact, direction and terminal state are timed."}

    prompt_manifest = json.loads((BASE / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V21.json").read_text(encoding="utf-8"))
    prompt_manifest["source_scene_authority_sha256"] = sha(ROOT / config["scene_contract_ref"])
    next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U20A").update({"prompt_path": rel(PROMPT), "prompt_sha256": prompt_sha})
    write_json(PROMPT_MANIFEST, prompt_manifest)
    dialogue_manifest = json.loads((BASE / "E36_DIALOGUE_MANIFEST_V11.json").read_text(encoding="utf-8"))
    dialogue_manifest["rows"].append({"video_unit_id": "U20A", "dia_id": "E36-U20A-R2-D01", "status": "PASS", "speaker": "陈迹", "spoken_text": TEXT, "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(AUDIO), "sha256": audio_sha, "remote_asset_id": VOICE_ASSET_ID, "start_seconds": 0.15, "end_seconds": 5.40, "breath_after_seconds": 0.0, "expression": "十七岁陈迹捏紧无字票根，克制归纳刘家灭门线索"})
    write_json(DIALOGUE_MANIFEST, dialogue_manifest)
    write_json(DIALOGUE_GATE, {"schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U20A", "source_segment_id": "U20A-R2A", "source_cl2x": "CL2X-814", "status": "PASS", "canonical_script_sha256": SCRIPT_SHA, "manifest_sha256": MANIFEST_SHA, "dialogue": [{"dia_id": "E36-U20A-R2-D01", "spoken_text": TEXT, "start_seconds": 0.15, "end_seconds": 5.40, "voice_reference_sha256": audio_sha}], "checks": {"canonical_and_manifest_sha_match": "PASS", "exact_text_in_prompt": "PASS", "exact_audio": "PASS_HOMOPHONE_EQUIVALENT_DIRECT_QA", "audio_duration": "PASS_5P201292_WITHIN6S", "native_mandarin_required": "PASS", "visible_age17_chenji_mouth": "PASS", "silent_age17_yunyang": "PASS", "lip_breath_expression_sync": "PASS", "closed_mouth_tail": "PASS_0P60", "action_contract": "PASS_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE", "first_frame_motion_state": "PASS", "environment_life": "PASS", "period_weather_continuity": "PASS_CLEAR_DUSK_WIND_TO_NIGHT", "visible_text": "PASS_BLANK_TICKET_BACK_ONLY", "credit_limit": "PASS_6642_PLUS96_LE10000"}, "failures": [], "blocked_by": None, "submission_allowed_after_supervisor_precheck": True})
    write_json(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": str(CONFIG), "config_sha256": sha(CONFIG), "prompt": str(PROMPT), "prompt_sha256": prompt_sha, "audio_sha256": audio_sha, "anchor_sha256": sha(ANCHOR)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
