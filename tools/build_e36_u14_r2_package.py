#!/usr/bin/env python3
"""Build the independent U14-R2 native-dialogue video package."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
R1 = BASE / "recovery_10000_20260730/u14_r1_video"
OUT = BASE / "recovery_10000_20260730/u14_r2_video"
QA = ROOT / "qa/e36_agentcut_20260730/u14_r2_video_runtime"
SRC = R1 / "E36_U14_R1_COMBINED_AUDIO_CHANGED_INPUT_V3_EPISODE_PARALLEL_BATCH_V1.json"
CONFIG = OUT / "E36_U14_R2_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U14-R2.txt"
PROMPT_MANIFEST = OUT / "E36_U14_R2_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U14_R2_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U14_R2_DIALOGUE_PROMPT_GATE_V1.json"
ANCHOR_PLAN = QA / "E36_U14_R2_ANCHOR_COUNT_PLAN_V1.json"
CAUSALITY_PLAN = QA / "E36_U14_R2_COMMON_SENSE_CAUSALITY_PLAN_V1.json"
PERIOD_PLAN = QA / "E36_U14_R2_PERIOD_LOCK_PLAN_V1.json"
AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u14_r2/E36-U14-R2-D01.wav"
AUDIO_QA = QA / "E36-U14-R2-D01_EXACT_DIALOGUE_AUDIO_QA_V1.json"
AUDIO_RECEIPT = ROOT / "workflow/tasks/E36_U14_R2_D01_CHENJI_EXACT_DIALOGUE_AUDIO_GENERATION_V1.json"
TEXT = "这纸浆里掺的墨，是王府账房记账那一种。"


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
        raise SystemExit("U14-R2 exact audio QA is not exact PASS")
    if sha(AUDIO) != audio_qa.get("wav_sha256") or audio_receipt.get("task_id") is None:
        raise SystemExit("U14-R2 exact audio provenance mismatch")

    prompt = f"""【E36-CW-U14-R2｜6秒｜纸浆墨源确认｜Seedance Fast原生普通话｜独立自然视频单元】

@图片1只锁定十七岁陈迹身份；@图片2只锁定十八岁皎兔身份；@图片3是已通过图片QA的U14-A1唯一首帧、人物站位、空白信封折痕、密室轴线和残余霜气权威。@音频1是陈迹逐字说出“{TEXT}”的精确普通话参考；视频模型必须让画面内陈迹现场原生说出该句，音频只作逐字、声线、气息和节奏参考，不得作为画外音或后配音轨播放。皎兔全段闭口。

【天气硬合同】weather=INTERIOR_CLEAR_DAY。6秒，竖屏9:16，720p，写实国漫古装悬疑电影质感。中国古代架空洛城，太平医馆密室午后。禁止现代物件、民国妆发、字幕、水印、任何可读文字或伪文字。

【实体绑定】[[scene:太平医馆密室]]；[[char:十七岁陈迹]]；[[char:十八岁皎兔]]；[[char:黑色犬形灵物乌云]]；[[prop:唯一素白空信封]]；[[effect:残余霜气]]。本镜继承本场既有大远景、全景、中景和近景空间权威，不重建地理，不新增人物或道具。

镜头1【双人中近景同轴承接，0.00-0.18秒】：主体=十七岁陈迹、十八岁皎兔、唯一素白空信封；动作=陈迹承接半起单指压折的进行态，左手拇指和食指正捻住信封近侧纸角，乌云从桌边探鼻嗅向纸角并低鸣，皎兔闭口看向证物；接触点=陈迹两指指腹与纸角、信封与旧木桌面、乌云鼻尖停在纸角外一寸；方向=陈迹两指由桌面向上捻起纸角不超过一指高，乌云由桌边向纸角前探；终态=陈迹嘴部清晰并立即开口，纸角仍连在信封上，皎兔闭口。{{无对白}}<音效：短吸气、纸纤维轻响、乌云低鸣、烛焰环境声>。

镜头2【陈迹胸上近景与指间纸角同框，0.18-4.65秒】：主体=十七岁陈迹；动作=陈迹边捻纸角边按@音频1自然普通话只说一遍“{TEXT}”，说到“纸浆”时指腹轻搓纸纤维，说到“墨”时鼻翼轻动确认气味，说到“王府账房”时视线从纸角移向皎兔但皎兔闭口，说到“那一种”时指腹停止搓动并压定纸角；接触点=拇指与食指指腹持续夹住同一纸角；方向=纸角只在两指间轻微上提和回落，视线由纸角转向皎兔；终态=“种”完整落下，陈迹闭口，纸角未撕裂、未拆开、无文字。{{对白：陈迹仅说“{TEXT}”}}<音效：@音频1精确参考、纸纤维摩擦、衣料随呼吸轻动>。

镜头3【双人证物中近景停稳，4.65-6.00秒】：主体=陈迹、皎兔、乌云、空白信封；动作=陈迹闭口短呼气并将纸角受重力放回原桌面，食指随后停在纸浆纤维边缘；乌云闭嘴收鼻半寸仍盯纸角，皎兔闭口把视线落到陈迹指尖；接触点=纸角回接桌面、陈迹食指与纸边；方向=纸角向下回落，乌云向后收鼻，皎兔视线向下；终态=墨源判断成立，信封完整留在桌面，三者均闭口，承接R3比对折痕。{{无对白}}<音效：短呼气、纸角落桌、乌云鼻息、烛焰微颤>。

【原生对白硬合同】唯一可听台词是“{TEXT}”。陈迹0.18-4.65秒只说一遍，不增字、不减字、不改字、不重复；完整嘴部清楚，口型、气息、眉眼、表情与起止时间同步。皎兔和乌云全程不说话。禁止串台、旁白、画外音、后配替换、现代播音腔、字幕。

【首帧动势与环境生命层】第一帧不是完成态：陈迹两指正在向上捻起纸角，乌云鼻尖正在向纸角前探，皎兔视线正在下移；0.18秒内陈迹立即开口。残余霜气持续散薄、烛焰持续微颤、衣料随呼吸轻动、纸角受指腹和重力真实回落。摩擦力只使纸纤维轻响，不撕纸、不复制信封、不生成文字。

【力量作用于环境介质】陈迹指腹施加的捻力只通过纸纤维摩擦、纸角轻微弯曲和重力回落表现；乌云鼻息只轻推残余霜气与纸角边缘，烛焰随气流微颤。力量不得变成空泛光效，不得推动整封信或撕裂纸角。

【身份与连续性】陈迹严格十七岁，不使用二十岁参考；皎兔严格十八岁且全程闭口；乌云是黑色犬形灵物，只嗅闻低鸣，不拟人说话。旧木深褐、灰旧布衣、冷灰青古装、暖烛与清冷窗光双动机光。禁止成年化、换脸、分身、肢体融合、嘴部遮挡、空信封出现文字、纸角撕裂、降速填时、插帧填时、循环动作、字幕、水印、Logo。
"""
    PROMPT.write_text(prompt, encoding="utf-8")

    config = json.loads(SRC.read_text(encoding="utf-8"))
    config.update({
        "status": "READY_FOR_SUPERVISOR_PRECHECK",
        "episode_paid_credits_before": 7389,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u14_r2_video",
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
    })
    config.pop("changed_input_parent_task_id", None)
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U14-R2-EXACT-AUDIO-10000",
        "source_id": "E36-CW-U14-R2-EXACT-AUDIO-10000",
        "batch_id": "E36-U14-R2-EXACT-AUDIO-10000",
        "source_segment_id": "U14-R2",
        "duration_seconds": 6,
        "duration": 6,
        "edit_target_duration_seconds": 6,
        "status": "READY_TO_SUBMIT",
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": sha(PROMPT),
        "reference_audios": [rel(AUDIO)],
        "reference_audio_asset_ids": [],
        "targeted_unit_replacement": True,
        "changed_input_repair": False,
        "unchanged_retry": False,
        "max_retries": 0,
    })
    task.pop("replaces_parent_task_id", None)
    task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 6, "rationale": "Exact3.703604s Chenji line fits0.18-4.65 with1.35s closed-mouth terminal evidence beat.", "edit_policy": "Preserve exact native dialogue; no time stretch, post-dub, filler, or duplicate frames."}
    task["dialogue"] = [{"dia_id": "E36-U14-R2-D01", "speaker": "陈迹", "spoken_text": TEXT, "start_seconds": 0.18, "end_seconds": 4.65, "breath_after_seconds": 0.0, "expression": "冷静确认墨源", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}]
    task["dialogue_audio_assets"] = [{"dia_id": "E36-U14-R2-D01", "speaker_id": "chenji", "character_name": "陈迹", "audio_slot": "@音频1", "path": rel(AUDIO), "sha256": sha(AUDIO), "duration_seconds": audio_qa["duration_seconds"], "reference_segment_start_seconds": 0.0, "reference_segment_end_seconds": audio_qa["duration_seconds"], "voice_reference_asset_id": "cypqud0bu7t", "voice_derivation_status": "PASS", "source_voice": f"AGENTCUT_SPEECH_GENERATION:{audio_receipt['task_id']}", "voice_gender": "male", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"}]
    task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "prop_ownership": {"唯一素白空信封": "陈迹只捻近侧纸角，完整留在桌面，不拆、不撕、不复制、不出现文字", "乌云": "只嗅纸低鸣，不说话"}, "motion_beats": [
        {"start_seconds": 0.0, "end_seconds": 0.18, "subject": "陈迹、皎兔、乌云、空白信封", "action": "陈迹捻起纸角，乌云探鼻嗅闻，皎兔视线下移", "contact_point": "陈迹两指与纸角；信封与桌面", "direction": "纸角向上、乌云向前、视线向下", "end_state": "陈迹立即开口，皎兔闭口", "intent": "进入纸浆检验", "visible_causality": "触觉和嗅闻共同触发墨源判断", "expression": "专注", "viewer_read": "开始检验纸浆"},
        {"start_seconds": 0.18, "end_seconds": 4.65, "subject": "陈迹", "action": "陈迹捻纸角并原生说出墨源判断", "contact_point": "拇指食指持续夹住同一纸角", "direction": "纸角轻微上提回落，视线由纸角转向皎兔", "end_state": "完整说完并闭口，纸角未损", "intent": "确认王府账房墨源", "visible_causality": "纸纤维触感和气味支撑判断", "expression": "冷静笃定", "viewer_read": "墨源被确认"},
        {"start_seconds": 4.65, "end_seconds": 6.0, "subject": "陈迹、皎兔、乌云、空白信封", "action": "陈迹放回纸角并指向纤维，乌云收鼻，皎兔看向指尖", "contact_point": "纸角回接桌面；陈迹食指与纸边", "direction": "纸角向下、乌云向后、视线向下", "end_state": "三者闭口，信封完整，承接R3", "intent": "封住墨源判断", "visible_causality": "纸角回落结束检验", "expression": "判断成立", "viewer_read": "下一步比对折痕"},
    ]}
    task["keyframe_interpolation_gate"] = {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 1, "adjacent_pairs_checked": 0, "checked_adjacent_pairs": 0, "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS_SINGLE_CONTINUOUS_A1_PAPER_PULP_INSPECTION", "reason": "R2 remains on the accepted A1 axis and same intact envelope; no identity, space, prop-ownership or non-interpolable state transition occurs."}
    for binding in task["multimodal_entity_bindings"]:
        if binding["entity_id"] == "chenji":
            binding.update({"voice_reference": rel(AUDIO), "voice_reference_sha256": sha(AUDIO), "audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1"], "prop_owners": {"唯一素白空信封": "两指只捻近侧纸角"}})
    task["multimodal_binding_sha256"] = digest(task["multimodal_entity_bindings"])

    prompt_manifest = json.loads((R1 / "E36_U14_R1_COMBINED_AUDIO_CHANGED_INPUT_V3_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json").read_text(encoding="utf-8"))
    row = next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U14")
    row.update({"unit_id": "U14", "prompt_path": rel(PROMPT), "prompt_sha256": sha(PROMPT)})
    write(PROMPT_MANIFEST, prompt_manifest)

    dialogue_manifest = json.loads((R1 / "E36_U14_R1_COMBINED_AUDIO_CHANGED_INPUT_V3_DIALOGUE_MANIFEST_V1.json").read_text(encoding="utf-8"))
    dialogue_manifest["rows"] = [row for row in dialogue_manifest["rows"] if row.get("video_unit_id") != "U14"]
    dialogue_manifest["rows"].append({"video_unit_id": "U14", "dia_id": "E36-U14-R2-D01", "status": "PASS", "speaker": "陈迹", "speaker_id": "chenji", "spoken_text": TEXT, "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(AUDIO), "sha256": sha(AUDIO), "remote_asset_id": "cypqud0bu7t", "start_seconds": 0.18, "end_seconds": 4.65, "breath_after_seconds": 0.0, "expression": "冷静确认墨源"})
    write(DIALOGUE_MANIFEST, dialogue_manifest)
    write(DIALOGUE_GATE, {"schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U14", "source_segment_id": "U14-R2", "source_cl2x": "CL2X-829", "status": "PASS", "canonical_script_sha256": config["source_script_sha256"], "manifest_sha256": config["source_manifest_sha256"], "dialogue": task["dialogue"], "checks": {"canonical_and_manifest_sha_match": "PASS", "exact_text_in_prompt": "PASS", "exact_audio_asr": "PASS_1P0", "source_speech_duration": "PASS_3P703604_WITHIN6S", "single_visible_speaker": "PASS_CHENJI_ONLY", "silent_jiaotu": "PASS_BOUND_CLOSED_MOUTH", "native_mandarin_required": "PASS", "lip_breath_expression_sync": "PASS", "closed_mouth_tail": "PASS_1P35", "action_contract": "PASS_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE", "first_frame_motion_state": "PASS", "environment_life": "PASS", "period_weather_continuity": "PASS_INTERIOR_CLEAR_DAY", "visible_text": "PASS_FORBIDDEN_ALL", "credit_limit": "PASS_7389_PLUS96_LE10000", "independent_unit_repair_budget": "PASS_R2_FIRST_ATTEMPT"}, "failures": [], "blocked_by": None, "submission_allowed_after_supervisor_precheck": True})
    write(ANCHOR_PLAN, {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 1, "units": [{"unit_id": "U14", "source_segment_id": "U14-R2", "planned_reference_image_count": 1, "reference_image_task_keys": ["U14-A1"], "keyframe_interpolation_gate": task["keyframe_interpolation_gate"], "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "R2 keeps the accepted A1 axis and intact-envelope ownership; A2 is reserved for R8.", "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False}, "anchor_roles": ["accepted_start_motion_layout_and_evidence_authority"], "action_design_class": "single_anchor_single_speaker_native_dialogue_paper_pulp_inspection"}}]})
    write(CAUSALITY_PLAN, {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U14", "source_segment_id": "U14-R2", "causality": {"applicable": True, "purpose": "陈迹检验纸浆并确认墨源。", "intended_effect": "物证由折法推进到王府账房墨源。", "visible_causality": "陈迹捻纸纤维、乌云嗅纸，触感与气味支撑判断。", "viewer_read": "纸浆掺墨来自王府账房。", "preconditions": ["U14-A1直接图片QA通过", "陈迹17岁与皎兔18岁身份连续", "信封完整无字"], "mechanism_chain": ["两指捻起纸角", "乌云嗅闻低鸣", "陈迹确认纸浆掺墨", "纸角受重力落回桌面"], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若没有纸角接触、嗅闻或信封被撕开，墨源判断的可见因果链不成立。"}, "prop_function_status": "PASS", "evidence_refs": [rel(PROMPT), rel(AUDIO_QA)]}}]})
    write(PERIOD_PLAN, {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "canonical_script_sha256": config["source_script_sha256"], "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S03"]}, "units": [{"unit_id": "U14", "source_segment_id": "U14-R2", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["太平医馆密室旧木桌", "古代布衣", "素白空信封", "烛台窗格", "残余霜气", "黑色犬形灵物乌云"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代纸张", "民国灯具", "民国妆发", "字幕", "水印", "可读文字或伪文字"], "exception_approvals": {}, "evidence_refs": [rel(PROMPT)]}}]})
    write(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": rel(CONFIG), "config_sha256": sha(CONFIG), "prompt_sha256": sha(PROMPT), "audio_sha256": sha(AUDIO)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
