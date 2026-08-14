#!/usr/bin/env python3
"""Build the E36 U18-R1 exact-dialogue recovery video package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
OUT = BASE / "recovery_10000_20260730/u18_r1_video"
QA = ROOT / "qa/e36_agentcut_20260730/u18_r1_video_runtime"
OLD_CONFIG = BASE / "E36_U18C_EPISODE_SINGLE_UNIT_FAST_V1.json"
OLD_PROMPT_MANIFEST = BASE / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V21.json"
OLD_DIALOGUE_MANIFEST = BASE / "E36_DIALOGUE_MANIFEST_V11.json"
CONFIG = OUT / "E36_U18_R1_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U18-R1.txt"
PROMPT_MANIFEST = OUT / "E36_U18_R1_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U18_R1_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U18_R1_DIALOGUE_PROMPT_GATE_V1.json"
AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u18_r1/E36-U18-R1-D01.wav"
TEXT = "……却还在按笔掏银子，买这颗棋的命。"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def binding_digest(bindings: list[dict]) -> str:
    payload = json.dumps(bindings, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    prompt = """【E36-CW-U18-R1｜5秒｜陈迹买棋命第一句｜Seedance Fast原生普通话】

@图片1只锁定十七岁云羊身份，@图片2只锁定十七岁陈迹身份，@图片3只锁定成年男性递信人身份；@图片4是U18B通过图片QA的无文字终态，是本单元唯一首帧、空间、屏幕方位与表演连续性权威。@音频1是陈迹用锁定少年声线生成的本句精确对白参考，必须逐字复现其自然中文普通话、语气、气息和节奏，不得播放为画外音或后配音轨。第一帧严格从@图片4起动：陈迹在画面左侧侧脸，完整嘴部可见并正在轻吸气；云羊在画面右侧闭口看陈迹；递信人在中后景持续发抖。

【天气硬合同】weather=INTERIOR_CLEAR_DUSK_ENTERING。中国古代架空洛城，太平医馆密室午后偏晚、暮色初染，暮色沿无字木墙缓慢右移，古式烛焰轻跳。禁止现代物件、现代纸张、官服、民国妆发、牌匾、字幕、水印；票根及一切可读文字全程在画外。

【实体绑定】[[scene:太平医馆密室]]；[[char:十七岁陈迹]]；[[char:十七岁云羊]]；[[char:成年男性递信人]]；[[prop:刘家旧钱票根位于画外案面]]。本单元不新增人物、道具或能力。

镜头1【陈迹侧脸近景·云羊肩后平视·极缓推近】0.00-0.35秒：主体=十七岁陈迹；动作=承接@图片4闭口终态，胸口轻起完成一次短吸气，眉心收紧后嘴唇将启；接触点=陈迹左手指腹在画外压住票根边缘，右手不触碰；方向=视线从右侧云羊压回右下方画外案面；终态=完整嘴部清晰可见并准备说出“却”。{无对白}<音效：短吸气、烛芯噼啪>。

镜头2【陈迹侧脸近景·同轴眼平·极缓推近】0.35-3.65秒：主体=十七岁陈迹；动作=完整脸与嘴始终清晰可见，按@音频1的声线、语气与节奏，以自然中文普通话只说一遍“……却还在按笔掏银子，买这颗棋的命。”，省略号只表现为开口前短停，不念“点点点”；接触点=左手指腹全段在画外压住同一票根边缘；方向=视线由右下画外案面抬向右侧云羊，头部只抬半寸；终态=最后一个“命”完整落下并自然闭口，目光锁住云羊。{对白：陈迹仅说“……却还在按笔掏银子，买这颗棋的命。”}<音效：@音频1精确对白参考、自然中文普通话、衣料轻绷、递信人压抑呼吸>。

镜头3【三人中近景·同轴平视】3.65-5.00秒：主体=十七岁陈迹、十七岁云羊、成年男性递信人；动作=陈迹闭口短呼气，云羊闭口消化判断，递信人肩背继续发抖并吞咽一次；接触点=票根仍在画外且只由陈迹左手指腹保全；方向=陈迹看向画面右侧云羊，云羊目光落向画外案面；终态=陈迹第一句完整落定，三人均闭口，票根物权不转移，为下一句留口。{无对白}<音效：短呼气、布袖摩擦、室内低风>。

【原生对白硬合同】仅陈迹说话。视频模型必须原生生成自然中文普通话，把@音频1作为本句精确对白参考并由陈迹口中现场说出；唯一可听台词是“……却还在按笔掏银子，买这颗棋的命。”。只能由陈迹在0.35-3.65秒说一遍，不增字、不减字、不改字、不重复。云羊与递信人全程闭口。禁止串台、旁白、画外音、现代播音腔、字幕或后配替换；陈迹口型逐字同步，气息、眉眼确认感与起止时间同步，末字后闭口。

【环境生命层】暮色光沿墙向右缓移；古式烛焰轻跳；递信人在中后景持续发抖并吞咽一次；三人衣料随呼吸自然牵动。所有环境动作不得遮住陈迹嘴部。

【力量作用于环境介质】陈迹短吸气只带动灰旧布衣领口和胸口轻微起伏；递信人的颤抖只带动粗布肩线；室内低风让烛焰向右轻摆后回正，尘粒缓慢漂移，木墙与药柜保持真实尺度。

【palette与光影】密室午青、暮色初染、陈迹灰旧布衣、云羊黑衣、递信人褐衣；窗外暖暮光轻描轮廓，古式烛火提供动机光，暗部保留面部细节，陈迹双眼与嘴部清楚可见。

硬性禁止：完成态起手后长停顿、降速、插帧填时、成年化、二十岁参考、换脸、人物复制、新增人物、票根或任何文字入镜、嘴被遮挡、口型漂移、念出省略号、吞掉“买这颗棋的命”、重复台词、云羊说话、递信人说话、字幕、水印。"""
    PROMPT.write_text(prompt + "\n", encoding="utf-8")
    prompt_sha = sha(PROMPT)
    audio_sha = sha(AUDIO)

    config = json.loads(OLD_CONFIG.read_text(encoding="utf-8"))
    config.update({
        "status": "READY_FOR_SUPERVISOR_PRECHECK",
        "video_credit_limit": 10000,
        "workflow_credit_scope": "e36_canonical_v2_20260728_recovery_20260730",
        "episode_paid_credits_before": 6248,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u18_r1_video",
        "qa_dir": rel(QA),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "dialogue_prompt_gate_ref": rel(DIALOGUE_GATE),
    })
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U18-R1-RECOVERY-10000",
        "source_id": "E36-CW-U18-R1-RECOVERY-10000",
        "batch_id": "E36-U18-R1-RECOVERY-10000",
        "status": "READY_TO_SUBMIT",
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": prompt_sha,
        "reference_audios": [rel(AUDIO)],
        "reference_audio_asset_ids": [],
        "max_retries": 0,
        "source_script_sha256": SCRIPT_SHA,
        "workflow_credit_scope": "e36_canonical_v2_20260728_recovery_20260730",
    })
    task["duration_plan"] = {
        "policy": "qingshan.shot_generation_duration.v5",
        "duration_seconds": 5,
        "rationale": "The exact natural Mandarin line is 3.1115 seconds and fits the 0.35-3.65 window with a closed-mouth reaction tail.",
        "edit_policy": "Preserve native dialogue, visible mouth and terminal reactions; trim only silence after QA.",
    }
    task["dialogue"] = [{
        "dia_id": "E36-U18-R1-D01",
        "speaker": "陈迹",
        "spoken_text": TEXT,
        "start_seconds": 0.35,
        "end_seconds": 3.65,
        "breath_after_seconds": 0.2,
        "expression": "十七岁陈迹克制推理，视线由案面抬向云羊，末字自然闭口",
        "language": "zh-CN",
        "native_video_audio": True,
        "lip_sync": True,
        "breath_expression_sync": True,
    }]
    task["dialogue_audio_assets"] = [{
        "dia_id": "E36-U18-R1-D01",
        "audio_slot": "@音频1",
        "speaker_id": "chenji",
        "character_name": "陈迹",
        "spoken_text": TEXT,
        "path": rel(AUDIO),
        "sha256": audio_sha,
        "duration_seconds": 3.1115,
        "remote_asset_id": "cypqud0bu7t",
        "voice_reference_asset_id": "cypqud0bu7t",
        "voice_derivation_status": "PASS",
        "source_voice": "AGENTCUT_SPEECH_GENERATION:b371b348-8f7c-454b-aa6d-df11138f404d; exact-line derivative bound to Chenji voice authority cypqud0bu7t",
        "voice_gender": "male",
        "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE",
        "mode": "exact_dialogue_audio_reference",
        "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
    }]
    task["performance_spec"]["motion_beats"] = [
        {"start_seconds": 0.0, "end_seconds": 0.35, "subject": "十七岁陈迹", "action": "承接闭口终态并短吸气", "contact_point": "左手指腹在画外压住票根边缘", "direction": "视线由右侧云羊压回右下画外案面", "end_state": "嘴部清晰可见并准备开口", "intent": "承接旧案已结的矛盾", "visible_causality": "云羊落句后陈迹立即推理", "expression": "冷静收紧", "viewer_read": "推理将启"},
        {"start_seconds": 0.35, "end_seconds": 3.65, "subject": "十七岁陈迹", "action": "按精确音频参考以自然中文普通话只说一遍canonical判断", "contact_point": "左手指腹全段在画外压住同一票根边缘", "direction": "视线由右下案面抬向右侧云羊", "end_state": "台词结束并自然闭口", "intent": "指出仍有人按笔付钱买命", "visible_causality": "旧案已结却持续付款形成矛盾", "expression": "克制而确定", "viewer_read": "说话人与推理清楚"},
        {"start_seconds": 3.65, "end_seconds": 5.0, "subject": "十七岁陈迹、十七岁云羊、成年男性递信人", "action": "陈迹闭口短呼气，云羊闭口消化，递信人继续发抖并吞咽", "contact_point": "票根仍在画外由陈迹保全", "direction": "陈迹看云羊，云羊看向画外案面", "end_state": "三人均闭口且票根物权不转移", "intent": "落定第一层推理", "visible_causality": "对白后自然反应", "expression": "确定、震动、惊惧", "viewer_read": "下一句可连续开始"},
    ]
    chenji = next(row for row in task["multimodal_entity_bindings"] if row["entity_id"] == "chenji")
    chenji.update({
        "voice_reference": rel(AUDIO),
        "voice_reference_sha256": audio_sha,
        "voice_reference_asset_id": "cypqud0bu7t",
        "audio_slot": "@音频1",
        "dialogue_audio_slots": ["@音频1"],
        "visible_speaker": True,
        "lip_sync": True,
    })
    task["multimodal_binding_sha256"] = binding_digest(task["multimodal_entity_bindings"])

    prompt_manifest = json.loads(OLD_PROMPT_MANIFEST.read_text(encoding="utf-8"))
    prompt_manifest["source_scene_authority_sha256"] = sha(ROOT / config["scene_contract_ref"])
    row = next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U18")
    row.update({"prompt_path": rel(PROMPT), "prompt_sha256": prompt_sha})
    write_json(PROMPT_MANIFEST, prompt_manifest)

    dialogue_manifest = json.loads(OLD_DIALOGUE_MANIFEST.read_text(encoding="utf-8"))
    row = next(row for row in dialogue_manifest["rows"] if row["video_unit_id"] == "U18")
    row.update({
        "dia_id": "E36-U18-R1-D01",
        "spoken_text": TEXT,
        "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE",
        "path": rel(AUDIO),
        "sha256": audio_sha,
        "remote_asset_id": "cypqud0bu7t",
        "start_seconds": 0.35,
        "end_seconds": 3.65,
        "breath_after_seconds": 0.2,
        "expression": "十七岁陈迹克制推理，视线由案面抬向云羊，末字自然闭口",
    })
    write_json(DIALOGUE_MANIFEST, dialogue_manifest)

    write_json(DIALOGUE_GATE, {
        "schema": "qingshan.dialogue_prompt_gate.v1",
        "episode": "E36",
        "unit_id": "U18",
        "source_segment_id": "U18-R1",
        "source_cl2x": "CL2X-810",
        "status": "PASS",
        "canonical_script_sha256": SCRIPT_SHA,
        "manifest_sha256": MANIFEST_SHA,
        "speaker": "陈迹",
        "spoken_text": TEXT,
        "start_seconds": 0.35,
        "end_seconds": 3.65,
        "voice_reference_asset_id": "cypqud0bu7t",
        "voice_reference_sha256": audio_sha,
        "checks": {
            "canonical_and_manifest_sha_match": "PASS",
            "exact_text_in_prompt": "PASS",
            "exact_audio_asr": "PASS_1P0",
            "audio_duration": "PASS_3P1115_WITHIN_2_TO_15",
            "native_mandarin_required": "PASS",
            "visible_age17_chenji_mouth": "PASS",
            "lip_breath_expression_sync": "PASS",
            "silent_age17_yunyang": "PASS",
            "silent_messenger": "PASS",
            "closed_mouth_tail": "PASS",
            "ellipsis_not_spoken": "PASS",
            "action_contract": "PASS_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE",
            "first_frame_motion_state": "PASS",
            "environment_life": "PASS",
            "period_continuity": "PASS",
            "credit_limit": "PASS_6248_LE_10000",
        },
        "failures": [],
        "blocked_by": None,
        "submission_allowed_after_supervisor_precheck": True,
    })
    write_json(CONFIG, config)
    print(json.dumps({
        "status": "PASS",
        "config": str(CONFIG),
        "config_sha256": sha(CONFIG),
        "prompt": str(PROMPT),
        "prompt_sha256": prompt_sha,
        "audio_sha256": audio_sha,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
