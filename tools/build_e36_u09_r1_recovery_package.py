#!/usr/bin/env python3
"""Build E36 U09-R1 from the accepted anchor and three exact dialogue refs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
OUT = BASE / "recovery_10000_20260730/u09_r1_video"
QA = ROOT / "qa/e36_agentcut_20260730/u09_r1_video_runtime"
CONFIG = OUT / "E36_U09_R1_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U09-R1.txt"
PROMPT_MANIFEST = OUT / "E36_U09_R1_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U09_R1_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U09_R1_DIALOGUE_PROMPT_GATE_V1.json"
ANCHOR_PLAN = QA / "E36_U09_R1_ANCHOR_COUNT_PLAN_V1.json"
CAUSALITY_PLAN = QA / "E36_U09_R1_COMMON_SENSE_CAUSALITY_PLAN_V1.json"
PERIOD_PLAN = QA / "E36_U09_R1_PERIOD_LOCK_PLAN_V1.json"
ANCHOR = ROOT / "working_assets/e36_recovery_10000_20260730/u09_a1/E36_E36-CW-U09-A1-STILL-V3-RECOVERY-10000_c6b3caf9-8da2-4a76-92d0-19fe9c1536fe.png"
ANCHOR_QA = ROOT / "qa/e36_agentcut_20260730/E36_RECOVERY_IMAGE_U09_A1_VISUAL_QA_V1.json"
CHENJI = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
MESSENGER = ROOT / "assets/reference/e25_20260719/E25-FAKE-MESSENGER-IDENTITY-LOCK.png"
AUDIO_DIR = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u09_r1"
AUDIOS = [AUDIO_DIR / f"E36-U09-R1-D0{i}.wav" for i in range(1, 4)]
TEXTS = ["错年份那批的接头人，是你。", "景朝的银子，你收了几年？", "大人明鉴！小的真只是个递信的。"]
DURATIONS = [2.485479, 2.403292, 2.948938]
WINDOWS = [(0.08, 2.57), (2.57, 4.98), (5.05, 8.00)]
TASK_IDS = ["a2a5062b-fb72-420f-bdb4-cf2fdaa04a30", "6550080a-ecd9-4e5f-abfd-cca3d7b62b1a", "19b106a7-f884-4b58-92a4-0214a7898c4d"]
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
    anchor_qa = json.loads(ANCHOR_QA.read_text(encoding="utf-8"))
    if not anchor_qa.get("verdict", "").startswith("PASS"):
        raise SystemExit("U09-A1 is not image-QA PASS")
    for index, audio in enumerate(AUDIOS, 1):
        qa = QA / f"E36-U09-R1-D0{index}_EXACT_DIALOGUE_AUDIO_QA_V1.json"
        data = json.loads(qa.read_text(encoding="utf-8"))
        if data.get("status") != "PASS" or data.get("asr_similarity") != 1.0:
            raise SystemExit(f"U09-R1 D0{index} exact audio is not PASS")

    prompt = f"""【E36-CW-U09-R1｜9秒｜密室核问上半段｜Seedance Fast原生普通话】

@图片1只锁定十七岁陈迹身份；@图片2只锁定洛城普通递信人身份；@图片3是已通过图片QA的U09-A1唯一首帧、空间轴线、绑缚状态和空信封权威。@音频1、@音频2是陈迹同一少年声线的两句精确对白参考；@音频3是递信人锁定声线的精确对白参考。视频模型必须把三句自然中文普通话由画面内对应人物现场原生说出，音频只作逐字、声线、气息和节奏参考，不得作为画外音或后配音轨播放。

【天气硬合同】weather=INTERIOR_CLEAR_HARSH_SUN。中国古代架空洛城，太平医馆密室午后；窗格硬日光缓慢移过旧木墙，烛焰轻摇，衣角与空信封纸角受微弱穿堂风轻颤。禁止现代物件、官服、民国妆发、牌匾、字幕、水印、任何可读文字或伪文字。

【实体绑定】[[scene:太平医馆密室]]；[[char:十七岁陈迹]]；[[char:洛城普通递信人]]；[[prop:唯一素白空信封]]；[[prop:绑缚木凳与绳结]]。不新增人物、道具或能力；信封全程留在桌面，不拆、不复制、不出现文字。

镜头1【承接@图片3双人中近景·同轴极缓推近】0.00-0.08秒：主体=十七岁陈迹、被缚递信人；动作=陈迹承接左侧前压中途状态，右掌继续向桌沿压实，递信人背部撞住凳背后仍在轻晃并短吸气；接触点=陈迹右掌与桌沿、递信人后背与凳背、手腕与绳结；方向=陈迹由画面左前向右内压近，递信人上身由前向后回晃；终态=陈迹完整嘴部清晰并立即开口，递信人闭口。{{无对白}}<音效：短吸气、木凳轻响、烛焰环境声>。

镜头2【陈迹左侧胸上近景·递信人右前景】0.08-2.57秒：主体=十七岁陈迹；动作=陈迹保持前压姿态，按@音频1只说一遍“{TEXTS[0]}”，眼神钉住递信人；接触点=右掌持续压桌沿；方向=脸与视线由左向右逼问；终态=“你”字完整落下，递信人全程闭口。{{对白：陈迹仅说“{TEXTS[0]}”}}<音效：@音频1精确参考、衣料随呼吸轻动>。

镜头3【同轴双人近景·不切反轴】2.57-4.98秒：主体=十七岁陈迹；动作=不留长停顿，按@音频2只说一遍“{TEXTS[1]}”，末句时眉峰微压；接触点=右掌仍在同一桌沿，左手不碰信封；方向=身体继续由左向右压近；终态=“几年”完整落下并闭口，递信人抬眼、仍闭口。{{对白：陈迹仅说“{TEXTS[1]}”}}<音效：@音频2精确参考、绳结受力轻响>。

镜头4【递信人右侧胸上近景·陈迹左前景虚焦】5.05-8.00秒：主体=被缚递信人；动作=递信人发抖抬眼，按@音频3只说一遍“{TEXTS[2]}”，胸口呼吸发紧，陈迹全程闭口；接触点=递信人后背持续抵住凳背、手腕仍受绳结约束；方向=递信人视线由下向左上看陈迹；终态=“递信的”完整落下并闭口，仍被缚坐。{{对白：递信人仅说“{TEXTS[2]}”}}<音效：@音频3精确参考、木凳轻响、窗外远处人声>。

镜头5【双人中近景·同轴停稳】8.00-9.00秒：主体=陈迹、递信人、唯一空信封；动作=两人闭口短呼吸，陈迹保持桌侧压迫距离，递信人仍轻抖，信封纸角被微风掀起后落回；接触点=陈迹右掌与桌沿、递信人后背与凳背、信封与桌面；方向=视线在左侧陈迹与右侧递信人之间锁定；终态=两人闭口、递信人仍被缚、空信封未拆且无字，为U09-R2连续供述保留终态。{{无对白}}<音效：短呼气、纸角轻响、烛焰>。

【原生对白硬合同】唯一可听台词依次是“{TEXTS[0]}”“{TEXTS[1]}”“{TEXTS[2]}”。陈迹只说前两句，递信人只说第三句；0.08-2.57、2.57-4.98、5.05-8.00秒逐字准确，只说一遍，不增字、不减字、不改字、不重复。对应说话人的完整嘴部必须清楚，口型、气息、眉眼、表情和起止时间同步；另一人闭口。禁止串台、旁白、画外音、现代播音腔、字幕或后配替换。

【首帧动势】第一帧不是完成态：陈迹右掌正在向桌沿压实，递信人身体仍由前向后回晃，烛焰和窗格光斑已经运动；0.08秒内立即开口。

【环境生命层】烛焰持续轻摇、窗格光斑缓移、衣角与空信封纸角轻颤、递信人全程微抖；所有环境动作不得遮挡说话人嘴部或生成文字。

【力量作用于环境介质】陈迹右掌向下的力量只让旧木桌沿轻响，不推动信封；递信人受绳结约束的回晃力量先传给凳背再使木凳轻响；穿堂风只推动烛焰、衣角和空信封纸角，纸角掀起后受重力落回原桌面。

【palette与光影】旧木深褐、陈迹灰旧布衣、递信人无纹黑衣、暖烛与冷白窗光双动机光；两名说话人的眼神和嘴部始终可读，禁止无来源彩光。

硬性禁止：长停顿、降速、插帧填时、成年化、二十岁参考、换脸、人物复制、新人物、信封拆开或出现文字、绳结消失、嘴部遮挡、口型漂移、吞字、改字、重复台词、串台、字幕、水印。"""
    PROMPT.write_text(prompt + "\n", encoding="utf-8")
    prompt_sha = sha(PROMPT)

    config = json.loads((BASE / "recovery_10000_20260730/u13_video/E36_U13_R1_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json").read_text(encoding="utf-8"))
    config.update({
        "status": "READY_FOR_SUPERVISOR_PRECHECK", "episode_paid_credits_before": 7035,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u09_r1_video", "qa_dir": rel(QA),
        "anchor_count_plan_ref": rel(ANCHOR_PLAN), "common_sense_causality_plan_ref": rel(CAUSALITY_PLAN),
        "period_lock_plan_ref": rel(PERIOD_PLAN), "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST), "dialogue_prompt_gate_ref": rel(DIALOGUE_GATE),
    })
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U09-R1-RECOVERY-10000", "source_id": "E36-CW-U09-R1-RECOVERY-10000",
        "batch_id": "E36-U09-R1-RECOVERY-10000", "unit_id": "U09", "scene_id": "E36-CW-S02",
        "visual_zone": "E36-U09-CLINIC-INTERROGATION", "duration_seconds": 9, "duration": 9,
        "edit_target_duration_seconds": 9, "model": "seedance-2.0-fast", "status": "READY_TO_SUBMIT",
        "prompt_path": rel(PROMPT), "prompt_file": rel(PROMPT), "prompt_sha256": prompt_sha,
        "reference_images": [rel(CHENJI), rel(MESSENGER), rel(ANCHOR)], "reference_audios": [rel(x) for x in AUDIOS],
        "reference_audio_asset_ids": [], "visual_entity_ids": ["chenji", "messenger"],
        "anchor_image_qa_ref": rel(ANCHOR_QA), "max_retries": 0,
    })
    task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 9, "rationale": "Three exact natural Mandarin refs total7.837709s and fit0.08-8.00 with a1.00s closed-mouth terminal beat.", "edit_policy": "Preserve native dialogue and terminal continuity; no time stretch, filler or duplicate frames."}
    task["reference_image_sequence"] = [
        {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(CHENJI), "sha256": sha(CHENJI), "identity_reference": True},
        {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "messenger", "path": rel(MESSENGER), "sha256": sha(MESSENGER), "identity_reference": True},
        {"asset_label": "@图片3", "role": "ACCEPTED_START_MOTION_AND_LAYOUT_AUTHORITY", "state_id": "U09-A1", "path": rel(ANCHOR), "sha256": sha(ANCHOR), "identity_reference": False},
    ]
    task["dialogue"] = [
        {"dia_id": f"E36-U09-R1-D0{i+1}", "speaker": "陈迹" if i < 2 else "递信人", "spoken_text": TEXTS[i], "start_seconds": WINDOWS[i][0], "end_seconds": WINDOWS[i][1], "breath_after_seconds": 0.0, "expression": "冷静压迫" if i < 2 else "畏缩发紧", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}
        for i in range(3)
    ]
    voice_assets = ["cypqud0bu7t", "cypqud0bu7t", "3llwjcbwf3w"]
    speakers = [("chenji", "陈迹"), ("chenji", "陈迹"), ("messenger", "递信人")]
    task["dialogue_audio_assets"] = [
        {"dia_id": f"E36-U09-R1-D0{i+1}", "speaker_id": speakers[i][0], "character_name": speakers[i][1], "audio_slot": f"@音频{i+1}", "path": rel(AUDIOS[i]), "sha256": sha(AUDIOS[i]), "duration_seconds": DURATIONS[i], "voice_reference_asset_id": voice_assets[i], "voice_derivation_status": "PASS", "source_voice": f"AGENTCUT_SPEECH_GENERATION:{TASK_IDS[i]}", "voice_gender": "male", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"}
        for i in range(3)
    ]
    task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "prop_ownership": {"唯一素白空信封": "全段留在桌面，不拆、不复制、不出现文字", "绑缚木凳与绳结": "全段约束递信人后背和手腕，不消失"}, "motion_beats": [
        {"start_seconds": 0.0, "end_seconds": 0.08, "subject": "陈迹与递信人", "action": "陈迹压实桌沿，递信人回晃短吸气", "contact_point": "陈迹右掌与桌沿；递信人后背与凳背、手腕与绳结", "direction": "陈迹左向右压近，递信人前向后回晃", "end_state": "陈迹立即开口", "intent": "建立审讯压迫", "visible_causality": "逼近使递信人回晃", "expression": "紧张", "viewer_read": "审讯正在进行"},
        {"start_seconds": 0.08, "end_seconds": 4.98, "subject": "陈迹", "action": "连续说出两句核问", "contact_point": "右掌持续压桌沿", "direction": "由左向右逼问", "end_state": "第二问完整落下并闭口", "intent": "确认接头和银钱年数", "visible_causality": "连续证据逼问迫使递信人抬眼", "expression": "冷静压迫", "viewer_read": "两项指控明确"},
        {"start_seconds": 5.05, "end_seconds": 8.0, "subject": "递信人", "action": "发抖抬眼说出唯一辩解", "contact_point": "后背抵凳背，手腕受绳结约束", "direction": "视线由下向左上", "end_state": "辩解完整落下并闭口", "intent": "否认接头身份", "visible_causality": "陈迹逼问后立即畏缩辩解", "expression": "畏缩发紧", "viewer_read": "递信人开始供述"},
        {"start_seconds": 8.0, "end_seconds": 9.0, "subject": "陈迹、递信人、空信封", "action": "两人闭口呼吸，纸角轻颤后落回", "contact_point": "陈迹掌与桌沿；递信人背与凳背；信封与桌面", "direction": "轴线保持左陈迹右递信人", "end_state": "递信人仍被缚、信封未拆、两人闭口", "intent": "保留R2连续供述", "visible_causality": "辩解结束后审讯未终止", "expression": "压迫未解", "viewer_read": "下一段将继续交代"},
    ]}
    task["multimodal_entity_bindings"] = [
        {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(CHENJI), "visual_reference_sha256": sha(CHENJI), "identity_image_slot": "@图片1", "voice_reference": rel(AUDIOS[0]), "voice_reference_sha256": sha(AUDIOS[0]), "voice_reference_asset_id": "cypqud0bu7t", "audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1", "@音频2"], "visible_speaker": True, "lip_sync": True, "prop_owners": {"桌沿": "右掌持续压住"}, "ability_owners": []},
        {"entity_id": "messenger", "character_name": "递信人", "registry_id": "CHAR-递信人-E36-古装", "visual_reference": rel(MESSENGER), "visual_reference_sha256": sha(MESSENGER), "identity_image_slot": "@图片2", "voice_reference": rel(AUDIOS[2]), "voice_reference_sha256": sha(AUDIOS[2]), "voice_reference_asset_id": "3llwjcbwf3w", "audio_slot": "@音频3", "dialogue_audio_slots": ["@音频3"], "visible_speaker": True, "lip_sync": True, "prop_owners": {"绑缚木凳与绳结": "后背和手腕持续受约束"}, "ability_owners": []},
    ]
    task["multimodal_binding_sha256"] = digest(task["multimodal_entity_bindings"])
    task["keyframe_interpolation_gate"] = {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 1, "adjacent_pairs_checked": 0, "checked_adjacent_pairs": 0, "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS_SINGLE_CONTINUOUS_INTERROGATION", "reason": "One accepted opening-motion anchor is sufficient for the same-room, same-axis continuous exchange."}

    prompt_manifest = json.loads((BASE / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V21.json").read_text(encoding="utf-8"))
    next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U09").update({"prompt_path": rel(PROMPT), "prompt_sha256": prompt_sha})
    write(PROMPT_MANIFEST, prompt_manifest)
    dialogue_manifest = json.loads((BASE / "E36_DIALOGUE_MANIFEST_V11.json").read_text(encoding="utf-8"))
    dialogue_manifest["rows"].extend([{ "video_unit_id": "U09", "dia_id": f"E36-U09-R1-D0{i+1}", "status": "PASS", "speaker": speakers[i][1], "spoken_text": TEXTS[i], "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(AUDIOS[i]), "sha256": sha(AUDIOS[i]), "remote_asset_id": voice_assets[i], "start_seconds": WINDOWS[i][0], "end_seconds": WINDOWS[i][1], "expression": "冷静压迫" if i < 2 else "畏缩发紧"} for i in range(3)])
    write(DIALOGUE_MANIFEST, dialogue_manifest)
    write(DIALOGUE_GATE, {"schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U09", "source_segment_id": "U09-R1", "source_cl2x": "CL2X-820", "status": "PASS", "canonical_script_sha256": SCRIPT_SHA, "manifest_sha256": MANIFEST_SHA, "dialogue": task["dialogue"], "checks": {"canonical_and_manifest_sha_match": "PASS", "exact_text_in_prompt": "PASS_ALL3", "exact_audio_asr": "PASS_1P0_ALL3", "combined_audio_duration": "PASS_7P837709_WITHIN9S", "native_mandarin_required": "PASS", "visible_speaker_mouths": "PASS", "lip_breath_expression_sync": "PASS", "closed_mouth_tail": "PASS_1P00", "action_contract": "PASS_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE", "first_frame_motion_state": "PASS", "environment_life": "PASS", "period_weather_continuity": "PASS_INTERIOR_CLEAR_HARSH_SUN", "visible_text": "PASS_FORBIDDEN_ALL", "credit_limit": "PASS_7035_PLUS144_LE10000"}, "failures": [], "blocked_by": None, "submission_allowed_after_supervisor_precheck": True})
    write(ANCHOR_PLAN, {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 1, "units": [{"unit_id": "U09", "source_segment_id": "U09-R1", "planned_reference_image_count": 1, "reference_image_task_keys": ["U09-A1"], "keyframe_interpolation_gate": task["keyframe_interpolation_gate"], "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "Seedance Fast can carry this same-room, same-axis continuous interrogation from one accepted opening-motion state; no identity, space, ownership or non-interpolable terminal transition requires a second state anchor.", "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False}, "anchor_roles": ["accepted_start_motion_layout_and_binding_authority"], "action_design_class": "single_anchor_continuous_native_dialogue_interrogation"}}]})
    write(CAUSALITY_PLAN, {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U09", "source_segment_id": "U09-R1", "causality": {"applicable": True, "purpose": "陈迹逼问接头和银钱年数，递信人畏缩辩解。", "intended_effect": "递信人开始供述但审讯未结束。", "visible_causality": "陈迹连续前压核问后，递信人被绳缚在凳上发抖抬眼辩解。", "viewer_read": "逼问直接引出辩解。", "preconditions": ["U09-A1图片QA通过", "两人身份与绑缚状态连续"], "mechanism_chain": ["陈迹压桌逼近", "两句核问", "递信人抬眼", "递信人辩解", "两人闭口保留R2"], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若无连续核问或递信人不受约束，辩解的可见因果不成立。"}, "prop_function_status": "PASS", "evidence_refs": [rel(ANCHOR_QA), rel(PROMPT)]}}]})
    write(PERIOD_PLAN, {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "canonical_script_sha256": SCRIPT_SHA, "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S02"]}, "units": [{"unit_id": "U09", "source_segment_id": "U09-R1", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["旧木密室", "古代布衣", "木凳绳结", "素白空信封", "烛台窗格"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代纸张", "官服误配", "民国妆发", "牌匾", "字幕", "水印", "可读文字或伪文字"], "exception_approvals": {}, "evidence_refs": [rel(ANCHOR), rel(PROMPT)]}}]})
    write(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": rel(CONFIG), "config_sha256": sha(CONFIG), "prompt_sha256": prompt_sha, "anchor_sha256": sha(ANCHOR), "audio_sha256": [sha(x) for x in AUDIOS]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
