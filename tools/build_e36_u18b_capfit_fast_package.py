#!/usr/bin/env python3
"""Build the exact-dialogue U18B continuation with the accepted U18A terminal."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
QA = ROOT / "qa/e36_v2_stills_repair_20260729/u18_video_runtime"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


spoken = "满门殁尽、无一活口，案子早结了、封了档，凶手都伏了法！"
duration = 6
start, end = 0.05, 5.90
prompt = PROD / "video_prompts_repair_v12/E36-CW-U18B.txt"
anchor = ROOT / "working_assets/e36_v2_stills_20260728/u18_local_repairs/E36-CW-U18B-A1-U18A-TERMINAL-4P95-V1.jpg"
anchor_qa = QA / "E36_U18B_TERMINAL_ANCHOR_IMAGE_QA_V1.json"
yunyang = ROOT / "assets/reference/e36_20260729/characters/CHAR-yunyang-age17-canonical-v1-20260729.png"
chenji = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
messenger = ROOT / "assets/reference/e25_20260719/E25-FAKE-MESSENGER-IDENTITY-LOCK.png"
voice = ROOT / "libraries/audio/voice_refs/agentcut_speech_v1_20260723/yunyang/VOICE-yunyang-agentcut-v1.wav"
audio = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u18b/E36-U18B-D01.wav"
audio_qa_path = QA / "E36_U18B_YUNYANG_EXACT_DIALOGUE_AUDIO_QA_V1.json"
audio_qa = read(audio_qa_path)

prompt.parent.mkdir(parents=True, exist_ok=True)
prompt.write_text(f"""【E36-CW-U18B｜6秒｜云羊灭门案第二句｜Seedance Fast原生普通话】

@图片1只锁定十七岁云羊身份，@图片2只锁定十七岁陈迹身份，@图片3只锁定成年男性递信人身份；@图片4是U18A通过视频QA后的4.95秒终态，是本单元唯一首帧、空间、屏幕方位与表演连续性权威。第一帧严格从@图片4起动：云羊位于画面右侧俯身、震惊失色且嘴已闭合；陈迹位于左侧闭口看案面；递信人在中后景持续发抖。@音频1只驱动云羊嘴部、气息与表情。

【天气硬合同】weather=INTERIOR_CLEAR_DUSK_ENTERING。中国古代架空洛城，太平医馆密室午后偏晚，暮色沿无字木墙缓慢右移，古式烛焰将尽而轻跳。禁止现代物件、现代纸张、官服、民国妆发、牌匾、字幕、水印；票根及一切可读文字全程在画外。

【实体绑定】[[scene:太平医馆密室]]；[[char:十七岁云羊]]；[[char:十七岁陈迹]]；[[char:递信人]]；[[prop:刘家旧钱票根位于画外案面]]。本单元不新增人物、道具或能力。

镜头1【云羊近景·陈迹肩后平视·极缓推近】0.00-0.05秒：主体=云羊；动作=承接@图片4闭口终态，胸口急促起伏一次并立刻开口；接触点=双手不接触画外票根；方向=视线从左侧陈迹压回左下案面；终态=嘴部完整可见并进入第一个“满”字。{{无对白}}<急促吸气、烛芯噼啪>

镜头2【云羊近景·同轴眼平·极缓推近】0.05-5.90秒：主体=云羊；动作=完整嘴部始终可见，以自然中文普通话只说一遍“{spoken}”，口型、气息、震惊转急迫的表情严格同步@音频1；接触点=云羊与画外票根保持一掌间隔，陈迹在画外压住票根；方向=云羊视线由左下案面抬向左侧陈迹，头部只抬半寸；终态=最后一个“法”说完后自然闭口，目光锁住陈迹。{{云羊：{spoken}}}<@音频1原生普通话、衣料轻绷、递信人压抑呼吸>

镜头3【三人中近景·同轴平视】5.90-6.00秒：主体=云羊、陈迹、递信人；动作=云羊闭口短呼气，陈迹闭口回望云羊，递信人肩背继续发抖；接触点=票根仍在画外且只由陈迹保全；方向=云羊看陈迹，陈迹目光由案面抬半寸；终态=云羊第二句完整落定，三人均闭口，为陈迹下一句留口。{{无对白}}<短呼气、布袖摩擦、室内低风>

【对白硬合同】唯一可听台词就是@音频1对应的“{spoken}”。只能由云羊在0.05-5.90秒说一遍。陈迹与递信人全程闭口。禁止漏字、改词、重说、抢话、串台、旁白、画外音、现代播音腔、字幕或后配替换；必须由视频模型原生生成自然中文普通话并同步口型、气息、表情和起止时间。

【环境生命层】暮色光沿墙右移；烛焰轻跳；递信人在中后景持续发抖并吞咽一次；衣料随呼吸自然牵动。所有环境动作不得遮住云羊嘴部。

【力量与环境介质】云羊急促呼吸的力量只带动黑色布袖、领口和胸口轻微起伏；递信人的颤抖只带动粗布肩线；室内低风让烛焰轻摆一次后回正，木墙、药柜与尘粒保持真实尺度。

【色彩与光影】密室午青、暮色初染、陈迹灰旧布衣、云羊黑衣、递信人褐衣；窗外暖暮光轻描轮廓，古式烛火提供动机光，暗部保留面部细节，云羊眼睛和嘴部清楚可见。

硬性禁止：完成态起手后长停顿，降速，插帧填时，成年化，换脸，人物复制，新增人物，票根或任何文字入镜，手碰物证，嘴被遮挡，口型漂移，漏掉“满门殁尽”开头，吞掉“伏了法”结尾，重复台词，陈迹说话，递信人说话，字幕，水印。
""", encoding="utf-8")

prompt_manifest = read(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V19.json")
for row in prompt_manifest["rows"]:
    if row["unit_id"] == "U18":
        row["prompt_path"] = rel(prompt)
        row["prompt_sha256"] = sha(prompt)
write(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V20.json", prompt_manifest)

dialogue_manifest = read(PROD / "E36_DIALOGUE_MANIFEST_V9.json")
dialogue_manifest["rows"] = [row for row in dialogue_manifest["rows"] if row.get("video_unit_id") != "U18"]
dialogue_manifest["rows"].append({
    "dia_id": "E36-U18B-D01", "video_unit_id": "U18", "speaker_id": "yunyang", "speaker": "云羊",
    "spoken_text": spoken, "status": "PASS", "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE",
    "path": rel(audio), "sha256": sha(audio), "duration_seconds": float(audio_qa["duration_seconds"]),
    "voice_reference_asset_id": "v0udrgrojud", "voice_derivation_status": "PASS",
    "source_voice": "AGENTCUT_SPEECH_GENERATION:clone_20250922_190214_400934",
    "start_seconds": start, "end_seconds": end, "expression": "十七岁云羊震惊转急迫，气息发紧但普通话自然清楚",
})
write(PROD / "E36_DIALOGUE_MANIFEST_V10.json", dialogue_manifest)

anchor_plan = {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 1,
    "units": [{"unit_id": "U18", "source_segment_id": "U18B", "planned_reference_image_count": 1,
        "reference_image_task_keys": [anchor.stem],
        "keyframe_interpolation_gate": {"status": "PASS", "anchor_count": 1, "checked_adjacent_pairs": 0,
            "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS_SINGLE_CONTINUATION_TAKE",
            "reason": "The passed U18A terminal fixes identities, positions, dusk light, closed mouths and Yunyang's active reaction for one continuous follow-up line."},
        "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "One continuous spoken follow-up has no prop transfer or spatial re-anchor.",
            "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False,
                "prop_ownership_transition": False, "non_interpolable_terminal_state": False},
            "anchor_roles": ["accepted_u18a_terminal_continuation_authority"], "action_design_class": "single_anchor_native_dialogue_continuation"}}]}
write(QA / "E36_U18B_ANCHOR_COUNT_PLAN_V1.json", anchor_plan)

causality = {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U18", "source_segment_id": "U18B", "causality": {
    "applicable": True, "purpose": "云羊承接认出刘家后的震惊，立即补全三年前灭门案已结案封档的事实。",
    "intended_effect": "第二句让陈迹意识到有人仍在为死案付钱。", "visible_causality": "U18A闭口终态直接转急促吸气和第二句，不重置空间。",
    "viewer_read": "观众能读出云羊因认出刘家而连续补充旧案事实，并把下一步推理交给闭口倾听的陈迹。",
    "preconditions": ["U18A修复源已通过视频QA", "4.95秒终态锚已通过图片QA", "陈迹与递信人闭口", "票根和文字区均在画外"],
    "mechanism_chain": ["云羊承接震惊", "急促吸气", "完整说出结案封档事实", "闭口看向陈迹"],
    "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若重演第一句、陈迹串台或文字入镜，连续因果和对白归属失效。"},
    "prop_function_status": "PASS", "evidence_refs": [rel(anchor_qa), rel(prompt)]}}]}
write(QA / "E36_U18B_COMMON_SENSE_CAUSALITY_PLAN_V1.json", causality)

period = {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", rel(PROD / "E36_SCENE_STATE_AUTHORITY_V1.json") + "#E36-CW-S04"]},
    "units": [{"unit_id": "U18", "source_segment_id": "U18B", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["交领古装", "灰旧布衣", "黑色古装", "褐色粗布", "无字木墙", "古式烛光"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代纸张", "官服", "民国妆发", "牌匾", "字幕", "水印"], "exception_approvals": {}, "evidence_refs": [rel(anchor), rel(prompt)]}}]}
write(QA / "E36_U18B_PERIOD_LOCK_PLAN_V1.json", period)

dialogue_gate = {"schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U18", "source_segment_id": "U18B", "status": "PASS", "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6", "speaker": "云羊", "spoken_text": spoken, "start_seconds": start, "end_seconds": end, "voice_reference_asset_id": "v0udrgrojud", "voice_reference_sha256": sha(voice), "checks": {"exact_text_in_prompt": "PASS", "native_mandarin_required": "PASS", "visible_yunyang_mouth": "PASS", "lip_breath_expression_sync": "PASS", "silent_age17_chenji": "PASS", "silent_messenger": "PASS", "closed_mouth_tail": "PASS"}, "failures": []}
write(QA / "E36_U18B_DIALOGUE_PROMPT_GATE_V1.json", dialogue_gate)

base = read(PROD / "E36_U18A_EPISODE_SINGLE_UNIT_V2.json")
base.update({"status": "READY_FOR_SUPERVISOR_PRECHECK", "episode_paid_credits_before": 5591,
    "qa_dir": rel(QA), "anchor_count_plan_ref": rel(QA / "E36_U18B_ANCHOR_COUNT_PLAN_V1.json"),
    "common_sense_causality_plan_ref": rel(QA / "E36_U18B_COMMON_SENSE_CAUSALITY_PLAN_V1.json"),
    "period_lock_plan_ref": rel(QA / "E36_U18B_PERIOD_LOCK_PLAN_V1.json"),
    "complete_video_prompt_manifest_ref": rel(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V20.json"),
    "dialogue_manifest_ref": rel(PROD / "E36_DIALOGUE_MANIFEST_V10.json"),
    "dialogue_prompt_gate_ref": rel(QA / "E36_U18B_DIALOGUE_PROMPT_GATE_V1.json")})
task = copy.deepcopy(base["tasks"][0])
task.update({"task_key": "E36-CW-U18B-VIDEO-V1-FAST", "source_id": "E36-CW-U18B", "batch_id": "E36-U18B-VIDEO-V1-FAST",
    "unit_id": "U18", "scene_id": "E36-CW-S04", "visual_zone": "E36-U18B-YUNYANG-CLOSED-CASE-FOLLOWUP",
    "duration_seconds": duration, "duration": duration, "edit_target_duration_seconds": duration, "model": "seedance-2.0-fast",
    "prompt_path": rel(prompt), "prompt_file": rel(prompt), "prompt_sha256": sha(prompt), "anchor_image_qa_ref": rel(anchor_qa),
    "reference_images": [rel(yunyang), rel(chenji), rel(messenger), rel(anchor)], "reference_audios": [rel(audio)],
    "reference_audio_asset_ids": [], "planned_reference_image_count": 1, "state_reference_minimum": 1,
    "dialogue": [{"dia_id": "E36-U18B-D01", "speaker": "云羊", "spoken_text": spoken, "start_seconds": start, "end_seconds": end,
        "expression": "十七岁云羊震惊转急迫，气息发紧但普通话自然清楚", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}],
    "dialogue_audio_assets": [{"dia_id": "E36-U18B-D01", "audio_slot": "@音频1", "speaker_id": "yunyang", "character_name": "云羊", "spoken_text": spoken,
        "path": rel(audio), "sha256": sha(audio), "duration_seconds": float(audio_qa["duration_seconds"]), "voice_reference_asset_id": "v0udrgrojud",
        "voice_derivation_status": "PASS", "source_voice": "AGENTCUT_SPEECH_GENERATION:clone_20250922_190214_400934", "voice_gender": "male", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"}],
    "audio_reference_optional": False, "native_dialogue_required": True, "visible_speaker_required": True,
    "temporal_visual_qa_required": True, "visual_entity_ids": ["yunyang", "chenji", "messenger"], "status": "READY", "max_retries": 0})
task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": duration,
    "rationale": "Six seconds fit the verified 5.828-second line with a 0.05-second onset and 0.10-second closed-mouth tail.",
    "edit_policy": "Preserve native Mandarin and picture-audio sync; no time stretch or inserted filler."}
task["reference_image_sequence"] = [
    {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "yunyang", "path": rel(yunyang), "sha256": sha(yunyang), "identity_reference": True},
    {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(chenji), "sha256": sha(chenji), "identity_reference": True},
    {"asset_label": "@图片3", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "messenger", "path": rel(messenger), "sha256": sha(messenger), "identity_reference": True},
    {"asset_label": "@图片4", "role": "ACCEPTED_U18A_TERMINAL_CONTINUATION_AUTHORITY", "state_id": anchor.stem, "path": rel(anchor), "sha256": sha(anchor), "identity_reference": False},
]
task["multimodal_entity_bindings"][0].update({"audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1"], "voice_reference": rel(voice), "voice_reference_sha256": sha(voice)})
task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "episode": "E36", "unit_id": "U18", "source_segment_id": "U18B", "duration_seconds": duration,
    "prop_ownership": {"刘家旧钱票根": "陈迹在画外持续保全；云羊保持一掌间隔；本单元不显示票面"}, "motion_beats": [
        {"start_seconds": 0.0, "end_seconds": 0.05, "subject": "云羊", "action": "承接闭口终态并急促吸气", "contact_point": "双手不接触画外票根", "direction": "视线由左侧陈迹压回左下案面", "end_state": "嘴部可见并立即开口", "intent": "承接震惊", "visible_causality": "第一句后立刻补充", "expression": "震惊转急迫", "viewer_read": "连续反应"},
        {"start_seconds": start, "end_seconds": end, "subject": "云羊", "action": f"以自然中文普通话只说一遍{spoken}", "contact_point": "与画外票根保持一掌间隔", "direction": "视线由左下案面抬向左侧陈迹", "end_state": "台词结束并自然闭口", "intent": "补全灭门案已结案封档事实", "visible_causality": "认出刘家后陈述旧案", "expression": "气息发紧、急迫", "viewer_read": "说话人与信息清楚"},
        {"start_seconds": end, "end_seconds": duration, "subject": "云羊、陈迹、递信人", "action": "云羊闭口短呼气，陈迹闭口回望，递信人继续发抖", "contact_point": "票根仍在画外由陈迹保全", "direction": "云羊看陈迹", "end_state": "三人均闭口，为陈迹下一句留口", "intent": "落定信息", "visible_causality": "对白后自然反应", "expression": "震惊、冷静、惊惧", "viewer_read": "续接清楚"}]}
task["keyframe_interpolation_gate"] = anchor_plan["units"][0]["keyframe_interpolation_gate"]
base["tasks"] = [task]
write(PROD / "E36_U18B_EPISODE_SINGLE_UNIT_FAST_V1.json", base)

cap = {"schema": "qingshan.e36_capfit_plan.v1", "episode": "E36", "status": "PASS", "actual_credits_before_next_video": 5591,
    "actual_breakdown": {"image": 561, "video": 5020, "audio": 10}, "budget_cap": 6000, "remaining_before_next_video": 409,
    "observed_fast_rate_evidence": {"model": "seedance-2.0-fast", "observed_duration_seconds": 15, "observed_charge_credits": 105, "derived_credits_per_second": 7,
        "evidence": "workflow/tasks/E17_E28_ACCOUNT_VIDEO_CREDIT_WINDOW_AUDIT_20260722.json:2844-2868 plus working_assets/e16_api_20260711/continuous_segments/E16-CS-D55-D62-CORONER_PRESSURE/submit_receipt.json"},
    "remaining_plan": [
        {"segment": "U18B", "duration_seconds": 6, "model": "seedance-2.0-fast", "projected_credits": 42},
        {"segment": "U18C", "duration_seconds": 5, "model": "seedance-2.0-fast", "projected_credits": 35},
        {"segment": "U18D", "duration_seconds": 5, "model": "seedance-2.0-fast", "projected_credits": 35},
        {"segment": "U06_FALLBACK", "duration_seconds": 5, "model": "seedance-2.0-fast", "projected_credits": 35},
        {"segment": "U07_FALLBACK", "duration_seconds": 5, "model": "seedance-2.0-fast", "projected_credits": 35},
        {"segment": "U17_FALLBACK", "duration_seconds": 5, "model": "seedance-2.0-fast", "projected_credits": 35}],
    "projected_additional_credits": 217, "projected_episode_total": 5808, "headroom": 192,
    "hard_gate": "PASS_AT_OR_BELOW_6000_WITH_ALL_DECLARED_COVERAGE", "notes": ["U18B duration is exact-audio-derived.", "U18C/U18D remain conservative five-second natural-dialogue units and require native Chenji video voice; no wrong-voice TTS reference will be fabricated.", "Any live billing variance must stop the next paid submission and recompute from exact statements."]}
write(QA / "E36_CAPFIT_REPLAN_5808_V7.json", cap)
print(PROD / "E36_U18B_EPISODE_SINGLE_UNIT_FAST_V1.json")
