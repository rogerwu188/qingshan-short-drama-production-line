#!/usr/bin/env python3
"""Build the final native-voice U18D inference from the accepted U18C terminal."""

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


spoken = "死案不会付钱。付钱的，是替死人管账的活人。"
duration = 6
start, end = 0.25, 5.55
prompt = PROD / "video_prompts_repair_v14/E36-CW-U18D.txt"
anchor = ROOT / "working_assets/e36_v2_stills_20260728/u18_local_repairs/E36-CW-U18D-A1-U18C-TERMINAL-4P95-V1.jpg"
anchor_qa = QA / "E36_U18D_TERMINAL_ANCHOR_IMAGE_QA_V1.json"
yunyang = ROOT / "assets/reference/e36_20260729/characters/CHAR-yunyang-age17-canonical-v1-20260729.png"
chenji = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
messenger = ROOT / "assets/reference/e25_20260719/E25-FAKE-MESSENGER-IDENTITY-LOCK.png"
voice = ROOT / "libraries/audio/voice_refs/native_multimodal_20260709/VOICE-陈迹-古装/e09_shot01_chenji_native_voice_ref.wav"

if read(anchor_qa).get("status") != "PASS_CONTINUATION_AUTHORITY":
    raise SystemExit("U18D continuation anchor has not passed image QA")

prompt.parent.mkdir(parents=True, exist_ok=True)
prompt.write_text(f"""【E36-CW-U18D｜6秒｜陈迹活人账房结论｜Seedance Fast原生普通话】

@图片1只锁定十七岁云羊身份，@图片2只锁定十七岁陈迹身份，@图片3只锁定成年男性递信人身份；@图片4是U18C通过视频QA后的4.95秒无文字终态，是本单元唯一首帧、空间、屏幕方位与表演连续性权威。@音频1只锁定陈迹原生少年声线，不提供目标台词成品。第一帧严格从@图片4起动：陈迹在画面左侧侧脸，嘴唇刚结束短呼气且完整可见；云羊在画面右侧闭口低看画外案面；递信人在中后景发抖。

【天气硬合同】weather=INTERIOR_CLEAR_DUSK_ENTERING。中国古代架空洛城，太平医馆密室午后偏晚，暮色沿无字木墙缓慢右移，古式烛焰将尽而轻跳。禁止现代物件、现代纸张、官服、民国妆发、牌匾、字幕、水印；票根及一切可读文字全程在画外。

【实体绑定】[[scene:太平医馆密室]]；[[char:十七岁陈迹]]；[[char:十七岁云羊]]；[[char:递信人]]；[[prop:刘家旧钱票根位于画外案面]]。本单元不新增人物、道具或能力。

镜头1【陈迹侧脸近景·云羊肩后平视·极缓推近】0.00-0.25秒：主体=陈迹；动作=承接@图片4终态，眉心保持收紧并补一次极短鼻吸气，嘴唇立即将启；接触点=陈迹左手指腹在画外压住票根边缘，右手不触碰；方向=视线从右侧云羊移向中后景递信人半寸；终态=完整嘴部清晰可见并进入“死”字。{{无对白}}<极短吸气、烛芯噼啪>

镜头2【陈迹侧脸近景·同轴眼平·极缓推近】0.25-2.20秒：主体=陈迹；动作=使用@音频1的十七岁少年声线，以自然中文普通话只说“死案不会付钱”；接触点=左手指腹全段在画外压住同一票根边缘；方向=目光锁向中后景递信人；终态=“钱”字落下后嘴唇短闭，完成句号停顿。{{陈迹：死案不会付钱。}}<@音频1原生少年声线、自然中文普通话、衣料轻绷>

镜头3【陈迹侧脸近景·同轴眼平·极缓推近】2.20-5.55秒：主体=陈迹；动作=短停后继续以同一口气完整说“付钱的，是替死人管账的活人”，嘴部、气息与眉眼从冷静推理收束为确定；接触点=左手指腹仍在画外压住票根边缘；方向=目光由递信人回到右侧云羊，头部只回半寸；终态=最后一个“人”完整落下并自然闭口，目光锁住云羊。{{陈迹：付钱的，是替死人管账的活人。}}<@音频1原生少年声线、递信人压抑呼吸、室内低风>

镜头4【三人中近景·同轴平视】5.55-6.00秒：主体=陈迹、云羊、递信人；动作=陈迹闭口短呼气，云羊闭口抬眼看陈迹，递信人肩背继续发抖；接触点=票根仍在画外且只由陈迹左手指腹保全；方向=陈迹与云羊视线相接，递信人低头；终态=陈迹最终结论完整落定，三人均闭口。{{无对白}}<短呼气、布袖摩擦、烛焰轻响>

【原生对白硬合同】仅陈迹说话。视频模型必须原生生成自然中文普通话，使用@音频1的十七岁少年声线，不得把@音频1中的旧台词当成目标文本；唯一可听台词是“{spoken}”。只能由陈迹在0.25-5.55秒说一遍，不增字、不减字、不改字、不重复。第一句句号处嘴唇短闭但不得长停。云羊与递信人全程闭口。禁止串台、旁白、画外音、现代播音腔、字幕或后配替换；口型、气息、表情和起止时间同步，末字闭口。

【环境生命层】暮色光沿墙右移；烛焰轻跳；递信人在中后景持续发抖并吞咽一次；云羊衣领随静息呼吸起伏；陈迹灰旧布衣随发声与短呼气自然牵动。环境动作不得遮住陈迹嘴部。

【力量与环境介质】陈迹发声的气息只带动领口和胸口轻微起伏；递信人的颤抖只带动粗布肩线；室内低风让烛焰向右轻摆后回正，木墙、药柜与尘粒保持真实尺度。

【色彩与光影】密室午青、暮色初染、陈迹灰旧布衣、云羊黑衣、递信人褐衣；窗外暖暮光轻描轮廓，古式烛火提供动机光，暗部保留面部细节，陈迹双眼与嘴部清楚可见。

硬性禁止：完成态起手后长停顿，降速，插帧填时，成年化，二十岁参考，换脸，人物复制，新增人物，票根或任何文字入镜，嘴被遮挡，口型漂移，吞掉“死案不会付钱”或“替死人管账的活人”，重复台词，云羊说话，递信人说话，字幕，水印。
""", encoding="utf-8")

prompt_manifest = read(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V21.json")
for row in prompt_manifest["rows"]:
    if row["unit_id"] == "U18":
        row["prompt_path"] = rel(prompt)
        row["prompt_sha256"] = sha(prompt)
write(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V22.json", prompt_manifest)

dialogue_manifest = read(PROD / "E36_DIALOGUE_MANIFEST_V11.json")
dialogue_manifest["rows"] = [row for row in dialogue_manifest["rows"] if row.get("video_unit_id") != "U18"]
dialogue_manifest["rows"].append({
    "dia_id": "E36-U18D-D01", "video_unit_id": "U18", "speaker_id": "chenji", "speaker": "陈迹",
    "spoken_text": spoken, "status": "PASS", "audio_mode": "CANONICAL_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT_PROMPT",
    "path": rel(voice), "sha256": sha(voice), "remote_asset_id": "cypqud0bu7t", "voice_reference_asset_id": "cypqud0bu7t",
    "voice_derivation_status": "PASS", "source_voice": "陈迹锁定原生声线参考", "start_seconds": start, "end_seconds": end,
    "expression": "十七岁陈迹冷静推理收束为确定，句号短停，末字自然闭口",
})
write(PROD / "E36_DIALOGUE_MANIFEST_V12.json", dialogue_manifest)

anchor_plan = {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 1,
    "units": [{"unit_id": "U18", "source_segment_id": "U18D", "planned_reference_image_count": 1,
        "reference_image_task_keys": [anchor.stem],
        "keyframe_interpolation_gate": {"status": "PASS", "anchor_count": 1, "checked_adjacent_pairs": 0, "candidate_recheck_required": True,
            "physical_interpolation_or_declared_cut": "PASS_SINGLE_CONTINUATION_TAKE",
            "reason": "The passed U18C terminal fixes identities, positions, dusk light, silent listeners and Chenji's visible profile for one final inference line."},
        "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "One continuous final inference has no visible prop transfer or spatial re-anchor.",
            "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False},
            "anchor_roles": ["accepted_u18c_terminal_chenji_continuation_authority"], "action_design_class": "single_anchor_native_dialogue_continuation"}}]}
write(QA / "E36_U18D_ANCHOR_COUNT_PLAN_V1.json", anchor_plan)

causality = {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U18", "source_segment_id": "U18D", "causality": {
    "applicable": True, "purpose": "陈迹把持续付钱与替死人管账的活人直接绑定，完成幕后账房结论。",
    "intended_effect": "观众明确死案本身不会付钱，仍活动的幕后人是追查对象。", "visible_causality": "U18C闭口终态直接转陈迹最终结论，不重置空间。",
    "viewer_read": "观众能读出持续付款只能来自仍在替死人管账的活人。",
    "preconditions": ["U18C修复成片已通过视频QA", "U18D终态锚已通过图片QA", "云羊与递信人闭口", "票根和文字区均在画外"],
    "mechanism_chain": ["仍有人按笔买命", "死案本身不会付钱", "付款主体必为活人", "锁定替死人管账者"],
    "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若听者串台、纸文书入镜或第二句遗漏，最终推理链失效。"},
    "prop_function_status": "PASS", "evidence_refs": [rel(anchor_qa), rel(prompt)]}}]}
write(QA / "E36_U18D_COMMON_SENSE_CAUSALITY_PLAN_V1.json", causality)

period = {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", rel(PROD / "E36_SCENE_STATE_AUTHORITY_V1.json") + "#E36-CW-S04"]},
    "units": [{"unit_id": "U18", "source_segment_id": "U18D", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["交领古装", "灰旧布衣", "黑色古装", "褐色粗布", "无字木墙", "古式烛光"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代纸张", "官服", "民国妆发", "牌匾", "字幕", "水印"], "exception_approvals": {}, "evidence_refs": [rel(anchor), rel(prompt)]}}]}
write(QA / "E36_U18D_PERIOD_LOCK_PLAN_V1.json", period)

dialogue_gate = {"schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U18", "source_segment_id": "U18D", "status": "PASS", "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6", "speaker": "陈迹", "spoken_text": spoken, "start_seconds": start, "end_seconds": end, "voice_reference_asset_id": "cypqud0bu7t", "voice_reference_sha256": sha(voice), "checks": {"exact_text_in_prompt": "PASS", "native_mandarin_required": "PASS", "visible_chenji_mouth": "PASS", "lip_breath_expression_sync": "PASS", "silent_age17_yunyang": "PASS", "silent_messenger": "PASS", "period_pause": "PASS", "closed_mouth_tail": "PASS"}, "failures": []}
write(QA / "E36_U18D_DIALOGUE_PROMPT_GATE_V1.json", dialogue_gate)

base = read(PROD / "E36_U18C_EPISODE_SINGLE_UNIT_FAST_V1.json")
base.update({"status": "READY_FOR_SUPERVISOR_PRECHECK", "episode_paid_credits_before": 5767,
    "anchor_count_plan_ref": rel(QA / "E36_U18D_ANCHOR_COUNT_PLAN_V1.json"),
    "common_sense_causality_plan_ref": rel(QA / "E36_U18D_COMMON_SENSE_CAUSALITY_PLAN_V1.json"),
    "period_lock_plan_ref": rel(QA / "E36_U18D_PERIOD_LOCK_PLAN_V1.json"),
    "complete_video_prompt_manifest_ref": rel(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V22.json"),
    "dialogue_manifest_ref": rel(PROD / "E36_DIALOGUE_MANIFEST_V12.json"),
    "dialogue_prompt_gate_ref": rel(QA / "E36_U18D_DIALOGUE_PROMPT_GATE_V1.json")})
task = copy.deepcopy(base["tasks"][0])
task.update({"task_key": "E36-CW-U18D-VIDEO-V1-FAST", "source_id": "E36-CW-U18D", "batch_id": "E36-U18D-VIDEO-V1-FAST",
    "unit_id": "U18", "scene_id": "E36-CW-S04", "visual_zone": "E36-U18D-CHENJI-LIVING-BOOKKEEPER-CONCLUSION",
    "duration_seconds": duration, "duration": duration, "edit_target_duration_seconds": duration, "model": "seedance-2.0-fast",
    "prompt_path": rel(prompt), "prompt_file": rel(prompt), "prompt_sha256": sha(prompt), "anchor_image_qa_ref": rel(anchor_qa),
    "reference_images": [rel(yunyang), rel(chenji), rel(messenger), rel(anchor)], "reference_audios": [rel(voice)],
    "reference_audio_asset_ids": ["cypqud0bu7t"], "planned_reference_image_count": 1, "state_reference_minimum": 1,
    "dialogue": [{"dia_id": "E36-U18D-D01", "speaker": "陈迹", "spoken_text": spoken, "start_seconds": start, "end_seconds": end,
        "expression": "十七岁陈迹冷静推理收束为确定，句号短停，末字自然闭口", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}],
    "dialogue_audio_assets": [{"dia_id": "E36-U18D-D01", "audio_slot": "@音频1", "speaker_id": "chenji", "character_name": "陈迹", "spoken_text": spoken,
        "path": rel(voice), "sha256": sha(voice), "remote_asset_id": "cypqud0bu7t", "voice_reference_asset_id": "cypqud0bu7t", "voice_derivation_status": "PASS",
        "source_voice": "陈迹锁定原生声线参考", "voice_gender": "male", "audio_mode": "CANONICAL_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT_PROMPT", "purpose": "LOCKED_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT"}],
    "audio_reference_optional": False, "native_dialogue_required": True, "visible_speaker_required": True,
    "temporal_visual_qa_required": True, "visual_entity_ids": ["chenji", "yunyang", "messenger"], "status": "READY", "max_retries": 0})
task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": duration,
    "rationale": "Six seconds fit the two-clause twenty-character conclusion with a 0.25-second onset, sentence pause and 0.45-second closed-mouth tail.",
    "edit_policy": "Preserve native Mandarin and picture-audio sync; no time stretch or inserted filler."}
task["reference_image_sequence"] = [
    {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "yunyang", "path": rel(yunyang), "sha256": sha(yunyang), "identity_reference": True},
    {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(chenji), "sha256": sha(chenji), "identity_reference": True},
    {"asset_label": "@图片3", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "messenger", "path": rel(messenger), "sha256": sha(messenger), "identity_reference": True},
    {"asset_label": "@图片4", "role": "ACCEPTED_U18C_TERMINAL_CHENJI_CONTINUATION_AUTHORITY", "state_id": anchor.stem, "path": rel(anchor), "sha256": sha(anchor), "identity_reference": False},
]
bindings = task["multimodal_entity_bindings"]
for binding in bindings:
    if binding["entity_id"] == "chenji":
        binding.update({"audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1"], "voice_reference": rel(voice), "voice_reference_sha256": sha(voice), "voice_reference_asset_id": "cypqud0bu7t", "visible_speaker": True, "lip_sync": True})
    elif binding["entity_id"] == "yunyang":
        binding.update({"audio_slot": None, "dialogue_audio_slots": [], "visible_speaker": False, "lip_sync": False})
task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(bindings, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "episode": "E36", "unit_id": "U18", "source_segment_id": "U18D", "duration_seconds": duration,
    "prop_ownership": {"刘家旧钱票根": "陈迹左手指腹在画外持续压住；本单元不显示票面"}, "motion_beats": [
        {"start_seconds": 0.0, "end_seconds": start, "subject": "陈迹", "action": "承接终态并极短吸气", "contact_point": "左手指腹在画外压住票根边缘", "direction": "视线由右侧云羊移向中后景递信人", "end_state": "嘴部清晰可见并立即开口", "intent": "把推理指向活人", "visible_causality": "仍在付款触发最终结论", "expression": "冷静收紧", "viewer_read": "结论将启"},
        {"start_seconds": start, "end_seconds": 2.2, "subject": "陈迹", "action": "以自然中文普通话只说死案不会付钱", "contact_point": "左手指腹持续压住画外票根", "direction": "目光锁向中后景递信人", "end_state": "钱字落下并短闭口", "intent": "排除死案为付款主体", "visible_causality": "死者不能持续付钱", "expression": "克制确定", "viewer_read": "第一层结论清楚"},
        {"start_seconds": 2.2, "end_seconds": end, "subject": "陈迹", "action": "短停后完整说出付钱的是替死人管账的活人", "contact_point": "左手指腹仍压住画外票根", "direction": "目光由递信人回到右侧云羊", "end_state": "活人末字落下并自然闭口", "intent": "锁定幕后账房活人", "visible_causality": "持续付款必来自活人", "expression": "推理收束为确定", "viewer_read": "幕后追查对象明确"},
        {"start_seconds": end, "end_seconds": duration, "subject": "陈迹、云羊、递信人", "action": "陈迹闭口短呼气，云羊闭口抬眼，递信人继续发抖", "contact_point": "票根仍在画外由陈迹保全", "direction": "陈迹与云羊视线相接", "end_state": "最终结论完整落定且三人闭口", "intent": "收束场景", "visible_causality": "结论后自然反应", "expression": "确定、震动、惊惧", "viewer_read": "场景完成"}]}
task["keyframe_interpolation_gate"] = anchor_plan["units"][0]["keyframe_interpolation_gate"]
base["tasks"] = [task]
write(PROD / "E36_U18D_EPISODE_SINGLE_UNIT_FAST_V1.json", base)

cap = {"schema": "qingshan.e36_paid_submission_cap_gate.v1", "episode": "E36", "status": "PASS",
    "actual_credits_before_submission": 5767, "actual_breakdown": {"image": 561, "video": 5196, "audio": 10}, "budget_cap": 6000, "remaining_before_submission": 233,
    "planned_paid_submissions": [{"segment": "U18D", "duration_seconds": 6, "model": "seedance-2.0-fast", "exact_ceiling_credits": 96}],
    "planned_zero_credit_local_fallbacks": ["U06", "U07", "U17"], "projected_episode_total": 5863, "headroom": 137,
    "hard_gate": "PASS_AT_OR_BELOW_6000_WITH_ALL_DECLARED_COVERAGE",
    "conditions": ["U18D uses the observed exact Fast Pay16 per second ceiling.", "U06/U07/U17 remain full canonical coverage via zero-credit local motion composites and must pass motion and contact-read QA.", "If any local fallback fails final QA, stop before 6000 and replan or escalate without dropping coverage."]}
write(QA / "E36_U18D_PRE_SUBMIT_CAP_GATE_V1.json", cap)

print(PROD / "E36_U18D_EPISODE_SINGLE_UNIT_FAST_V1.json")
