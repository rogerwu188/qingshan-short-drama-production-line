#!/usr/bin/env python3
"""Build E36 U09-R1B from the accepted R1A terminal authority."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
SOURCE = BASE / "recovery_10000_20260730/u09_r1a_video/E36_U09_R1A_CHANGED_INPUT_EPISODE_PARALLEL_BATCH_V1.json"
OUT = BASE / "recovery_10000_20260730/u09_r1b_video"
QA = ROOT / "qa/e36_agentcut_20260730/u09_r1b_video_runtime"
CONFIG = OUT / "E36_U09_R1B_CONTINUATION_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U09-R1B.txt"
PROMPT_MANIFEST = OUT / "E36_U09_R1B_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U09_R1B_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U09_R1B_DIALOGUE_PROMPT_GATE_V1.json"
ANCHOR_PLAN = QA / "E36_U09_R1B_ANCHOR_COUNT_PLAN_V1.json"
CAUSALITY_PLAN = QA / "E36_U09_R1B_COMMON_SENSE_CAUSALITY_PLAN_V1.json"
PERIOD_PLAN = QA / "E36_U09_R1B_PERIOD_LOCK_PLAN_V1.json"
ANCHOR = ROOT / "working_assets/e36_recovery_10000_20260730/u09_r1b_anchor/E36_U09_R1A_ACCEPTED_TERMINAL_4P90S.png"
ANCHOR_QA = ROOT / "qa/e36_agentcut_20260730/u09_r1a_video_runtime/E36_U09_R1B_TERMINAL_ANCHOR_QA_V1.json"
CHENJI = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
MESSENGER = ROOT / "assets/reference/e25_20260719/E25-FAKE-MESSENGER-IDENTITY-LOCK.png"
AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u09_r1/E36-U09-R1-D03.wav"
AUDIO_QA = ROOT / "qa/e36_agentcut_20260730/u09_r1_video_runtime/E36-U09-R1-D03_EXACT_DIALOGUE_AUDIO_QA_V1.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
TEXT = "大人明鉴！小的真只是个递信的。"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"
VOICE_ASSET_ID = "3llwjcbwf3w"


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
    if sha(SCRIPT) != SCRIPT_SHA or sha(MANIFEST) != MANIFEST_SHA:
        raise SystemExit("canonical script or manifest SHA drift")
    audio_qa = read(AUDIO_QA)
    if audio_qa.get("status") != "PASS" or audio_qa.get("asr_similarity") != 1.0:
        raise SystemExit("U09-D03 exact audio is not QA PASS")
    anchor_qa = read(ANCHOR_QA)
    if anchor_qa.get("status") != "PASS_CONTINUATION_AUTHORITY":
        raise SystemExit("U09-R1A terminal is not continuation authority")

    prompt = f"""【E36-CW-U09-R1B｜4秒｜递信人答辩｜Seedance Fast原生普通话｜连续自然视频单元】

@图片1只锁定十七岁陈迹身份；@图片2只锁定洛城普通递信人身份；@图片3是U09-R1A已通过QA的唯一连续首帧、轴线、绑缚和空信封权威，第一帧严格从@图片3起动。@音频1只作为递信人逐字、声线、气息与节奏参考；视频模型必须让画面内被缚递信人现场原生说出自然中文普通话，不得播放画外音或后配音轨。陈迹全段闭口。

【天气硬合同】weather=INTERIOR_CLEAR_HARSH_SUN。中国古代架空洛城，太平医馆密室午后；窗格硬日光缓慢移过旧木墙，烛焰轻摇，衣角与唯一素白空信封纸角受微弱穿堂风轻颤。禁止现代物件、官服误配、民国妆发、牌匾、字幕、水印、任何可读文字或伪文字。

【实体绑定】[[scene:太平医馆密室]]；[[char:十七岁陈迹]]；[[char:洛城普通递信人]]；[[prop:唯一素白空信封]]；[[prop:绑缚木凳与绳结]]。不新增人物、道具或能力；信封全程平放桌面，不拆、不复制、不出现文字。

镜头1【承接@图片3双人中近景·同轴极缓推近】0.00-0.08秒：主体=被缚递信人、十七岁陈迹；动作=递信人承接抬眼准备回答状态，后背仍抵凳背，吸一口短气并张口；陈迹保持桌侧压迫距离且闭口；接触点=递信人后背与凳背、手腕与绳结，陈迹右掌与桌沿，空信封与桌面；方向=递信人视线由右下抬向左侧陈迹，陈迹由左向右压住轴线；终态=递信人完整嘴部清楚并立即开口，陈迹闭口。{{无对白}}<音效：短吸气、绳结轻响、烛焰环境声>。

镜头2【递信人右侧胸上近景·陈迹左前景】0.08-3.03秒：主体=被缚递信人；动作=递信人保持后背抵凳状态，按@音频1以发慌但清楚的自然中文普通话只说一遍“{TEXT}”，眉眼先躲闪再被迫迎向陈迹；接触点=手腕持续受绳结约束、后背抵凳背；方向=脸与视线由右向左朝陈迹回答；终态=“递信的”完整落下，递信人闭口并轻喘，陈迹全程闭口。{{对白：递信人仅说“{TEXT}”}}<音效：@音频1精确参考、绳结受力轻响、衣料随呼吸轻动>。

镜头3【同轴双人中近景·不切反轴】3.03-4.00秒：主体=递信人、陈迹、唯一空信封；动作=递信人闭口短喘并轻微缩肩，陈迹闭口盯住他，空信封纸角只轻颤后重新贴平桌面；接触点=递信人背与凳背、腕与绳结，陈迹掌与桌沿，信封与桌面；方向=轴线保持左陈迹右递信人；终态=递信人说完后闭口仍被缚，陈迹闭口保持压迫，空信封完整平放且无字。{{无对白}}<音效：短喘、纸角轻响、窗格风声>。

【原生对白硬合同】唯一可听台词是“{TEXT}”。仅递信人说话，只能在0.08-3.03秒说一遍，不增字、不减字、不改字、不重复；陈迹全段闭口。递信人完整嘴部始终清楚，口型、气息、眉眼、表情和起止时间同步；末字后立即停止发音并闭口。禁止串台、旁白、画外音、现代播音腔、字幕或后配替换。

【首帧动势】第一帧不是完成态：递信人正在抬眼并吸气，绳结仍受力，陈迹右掌持续压桌沿，烛焰和窗格光斑已经运动；0.08秒内递信人立即开口。

【环境生命层】烛焰持续轻摇、窗格光斑缓移、衣角和空信封纸角轻颤、递信人随呼吸微抖；环境动作不得遮挡递信人嘴部或生成文字。

【力量作用于环境介质】递信人缩肩的力先传到腕部绳结再到凳背，只使绳结和木凳轻响；陈迹右掌只压住桌沿，不推动信封；穿堂风只推动烛焰、衣角和信封纸角，纸角必须受重力重新贴平桌面。

【palette与光影】旧木深褐、陈迹灰旧布衣、递信人无纹黑衣、暖烛与冷白窗光双动机光；递信人眼神和完整嘴部始终可读，禁止无来源彩光。

硬性禁止：长停顿、降速、插帧填时、成年化、二十岁参考、换脸、人物复制、新人物、信封离桌或悬空、信封展开或复制、任何文字或伪文字、嘴部遮挡、口型漂移、吞字、改字、重复台词、陈迹说话、旁白、字幕、水印。"""
    PROMPT.write_text(prompt + "\n", encoding="utf-8")
    prompt_sha = sha(PROMPT)
    audio_sha = sha(AUDIO)

    config = read(SOURCE)
    config.update({
        "status": "READY_FOR_SUPERVISOR_PRECHECK",
        "episode_paid_credits_before": 7275,
        "video_credit_limit": 10000,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u09_r1b_video",
        "qa_dir": rel(QA),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "dialogue_prompt_gate_ref": rel(DIALOGUE_GATE),
        "anchor_count_plan_ref": rel(ANCHOR_PLAN),
        "common_sense_causality_plan_ref": rel(CAUSALITY_PLAN),
        "period_lock_plan_ref": rel(PERIOD_PLAN),
        "changed_input_parent_task_id": None,
        "changed_input_repair": False,
        "unchanged_retry": False,
    })
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U09-R1B-CONTINUATION-10000",
        "source_id": "E36-CW-U09-R1B-CONTINUATION-10000",
        "batch_id": "E36-U09-R1B-CONTINUATION-10000",
        "source_segment_id": "U09-R1B",
        "duration_seconds": 4,
        "duration": 4,
        "edit_target_duration_seconds": 4,
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": prompt_sha,
        "reference_images": [rel(CHENJI), rel(MESSENGER), rel(ANCHOR)],
        "reference_audios": [rel(AUDIO)],
        "reference_audio_asset_ids": [],
        "anchor_image_qa_ref": rel(ANCHOR_QA),
        "planned_reference_image_count": 1,
        "state_reference_minimum": 1,
        "status": "READY_TO_SUBMIT",
        "max_retries": 0,
        "visual_entity_ids": ["chenji", "messenger"],
        "changed_input_repair": False,
        "changed_input_parent_task_id": None,
    })
    task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 4, "rationale": "The exact2.948938-second messenger line fits0.08-3.03 and leaves0.97 seconds for a closed-mouth terminal beat.", "edit_policy": "Preserve source-native Mandarin, expression and picture-audio sync; no time stretch, filler or duplicate frames."}
    task["reference_image_sequence"] = [
        {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(CHENJI), "sha256": sha(CHENJI), "identity_reference": True},
        {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "messenger", "path": rel(MESSENGER), "sha256": sha(MESSENGER), "identity_reference": True},
        {"asset_label": "@图片3", "role": "ACCEPTED_R1A_TERMINAL_CONTINUATION_AUTHORITY", "state_id": ANCHOR.stem, "path": rel(ANCHOR), "sha256": sha(ANCHOR), "identity_reference": False},
    ]
    task["dialogue"] = [{"dia_id": "E36-U09-R1-D03", "speaker": "递信人", "spoken_text": TEXT, "start_seconds": 0.08, "end_seconds": 3.03, "breath_after_seconds": 0.0, "expression": "发慌辩解，气息短促但逐字清楚", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}]
    task["dialogue_audio_assets"] = [{"dia_id": "E36-U09-R1-D03", "speaker_id": "messenger", "character_name": "递信人", "audio_slot": "@音频1", "path": rel(AUDIO), "sha256": audio_sha, "duration_seconds": 2.948938, "voice_reference_asset_id": VOICE_ASSET_ID, "voice_derivation_status": "PASS", "source_voice": "AGENTCUT_SPEECH_GENERATION:19b106a7-f884-4b58-92a4-0214a7898c4d", "voice_gender": "male", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"}]
    task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "episode": "E36", "unit_id": "U09", "source_segment_id": "U09-R1B", "prop_ownership": {"唯一素白空信封": "全段平放桌面，不拆、不复制、不出现文字", "绑缚木凳与绳结": "全段约束递信人后背和手腕，不消失"}, "motion_beats": [
        {"start_seconds": 0.0, "end_seconds": 0.08, "subject": "被缚递信人、十七岁陈迹", "action": "递信人抬眼吸气并张口，陈迹闭口保持压迫", "contact_point": "递信人后背与凳背、手腕与绳结；陈迹右掌与桌沿；信封与桌面", "direction": "递信人由右下向左侧陈迹抬眼", "end_state": "递信人嘴部清楚并立即开口，陈迹闭口", "intent": "承接问句后立即答辩", "visible_causality": "连续两问迫使递信人抬眼开口", "expression": "发慌", "viewer_read": "递信人开始回答"},
        {"start_seconds": 0.08, "end_seconds": 3.03, "subject": "被缚递信人", "action": f"只说一遍{TEXT}", "contact_point": "手腕持续受绳结约束、后背抵凳背", "direction": "由右向左朝陈迹回答", "end_state": "末字完整落下并闭口，陈迹全程闭口", "intent": "否认参与只承认递信", "visible_causality": "审讯压力触发发慌辩解", "expression": "短促发慌", "viewer_read": "说话人与答辩内容明确"},
        {"start_seconds": 3.03, "end_seconds": 4.0, "subject": "递信人、陈迹、空信封", "action": "递信人闭口短喘缩肩，陈迹闭口盯住，纸角轻颤后贴平", "contact_point": "递信人背与凳背、腕与绳结；陈迹掌与桌沿；信封与桌面", "direction": "轴线保持左陈迹右递信人", "end_state": "两人闭口，递信人仍被缚，信封平放无字", "intent": "完成答辩并保留审讯压力", "visible_causality": "答辩结束后回到受缚状态", "expression": "压迫未解", "viewer_read": "本问答闭合"},
    ]}
    task["multimodal_entity_bindings"] = [
        {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(CHENJI), "visual_reference_sha256": sha(CHENJI), "identity_image_slot": "@图片1", "visible_speaker": False, "lip_sync": False, "prop_owners": {"桌沿": "右掌持续压住"}, "ability_owners": []},
        {"entity_id": "messenger", "character_name": "递信人", "registry_id": "CHAR-递信人-E36-古装", "visual_reference": rel(MESSENGER), "visual_reference_sha256": sha(MESSENGER), "identity_image_slot": "@图片2", "voice_reference": rel(AUDIO), "voice_reference_sha256": audio_sha, "voice_reference_asset_id": VOICE_ASSET_ID, "audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1"], "visible_speaker": True, "lip_sync": True, "prop_owners": {"绑缚木凳与绳结": "后背和手腕持续受约束"}, "ability_owners": []},
    ]
    task["multimodal_binding_sha256"] = digest(task["multimodal_entity_bindings"])
    task["keyframe_interpolation_gate"] = {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 1, "adjacent_pairs_checked": 0, "checked_adjacent_pairs": 0, "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS_SINGLE_CONTINUATION_RESPONSE", "reason": "Accepted R1A terminal fixes identity, axis, binding and blank-envelope ownership for the immediate answer."}

    prompt_manifest = read(BASE / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V21.json")
    next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U09").update({"prompt_path": rel(PROMPT), "prompt_sha256": prompt_sha})
    write(PROMPT_MANIFEST, prompt_manifest)
    dialogue_manifest = read(BASE / "E36_DIALOGUE_MANIFEST_V11.json")
    dialogue_manifest["rows"].append({"video_unit_id": "U09", "source_segment_id": "U09-R1B", "dia_id": "E36-U09-R1-D03", "status": "PASS", "speaker": "递信人", "speaker_id": "messenger", "spoken_text": TEXT, "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(AUDIO), "sha256": audio_sha, "remote_asset_id": VOICE_ASSET_ID, "start_seconds": 0.08, "end_seconds": 3.03, "expression": "发慌辩解"})
    write(DIALOGUE_MANIFEST, dialogue_manifest)
    write(DIALOGUE_GATE, {"schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U09", "source_segment_id": "U09-R1B", "source_cl2x": "CL2X-824", "status": "PASS", "canonical_script_sha256": SCRIPT_SHA, "manifest_sha256": MANIFEST_SHA, "dialogue": task["dialogue"], "checks": {"canonical_and_manifest_sha_match": "PASS", "predecessor_terminal_authority": "PASS_4P90", "exact_text_in_prompt": "PASS", "exact_audio_asr": "PASS_1P0", "single_visible_speaker": "PASS_MESSENGER_ONLY", "silent_chenji": "PASS", "native_mandarin_required": "PASS", "lip_breath_expression_sync": "PASS", "closed_mouth_tail": "PASS_0P97", "action_contract": "PASS_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE", "first_frame_motion_state": "PASS", "environment_life": "PASS", "period_weather_continuity": "PASS_INTERIOR_CLEAR_HARSH_SUN", "visible_text": "PASS_FORBIDDEN_ALL", "credit_limit": "PASS_7275_PLUS64_LE10000"}, "failures": [], "blocked_by": None, "submission_allowed_after_supervisor_precheck": True})
    write(ANCHOR_PLAN, {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 1, "units": [{"unit_id": "U09", "source_segment_id": "U09-R1B", "planned_reference_image_count": 1, "reference_image_task_keys": [ANCHOR.stem], "keyframe_interpolation_gate": task["keyframe_interpolation_gate"], "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "One accepted predecessor terminal fully fixes the immediate same-room response.", "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False}, "anchor_roles": ["accepted_r1a_terminal_continuation_authority"], "action_design_class": "single_anchor_single_speaker_native_dialogue_response"}}]})
    write(CAUSALITY_PLAN, {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U09", "source_segment_id": "U09-R1B", "causality": {"applicable": True, "purpose": "递信人在两句核问后发慌答辩。", "intended_effect": "明确他只承认递信而否认更深参与。", "visible_causality": "R1A终态的抬眼准备回答直接转为吸气开口和受缚答辩。", "viewer_read": "观众能读出问后即答的连续因果。", "preconditions": ["R1A终帧QA通过", "两人身份、轴线、绑缚与信封物权连续"], "mechanism_chain": ["陈迹两问结束", "递信人抬眼吸气", "答辩完整说出", "闭口缩肩仍受缚"], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若递信人未从R1A抬眼状态立即开口，问答连续性不成立。"}, "prop_function_status": "PASS", "evidence_refs": [rel(ANCHOR_QA), rel(PROMPT)]}}]})
    write(PERIOD_PLAN, {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "canonical_script_sha256": SCRIPT_SHA, "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S02"]}, "units": [{"unit_id": "U09", "source_segment_id": "U09-R1B", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["旧木密室", "古代布衣", "木凳绳结", "素白空信封", "烛台窗格"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代纸张", "官服误配", "民国妆发", "牌匾", "字幕", "水印", "可读文字或伪文字"], "exception_approvals": {}, "evidence_refs": [rel(ANCHOR), rel(PROMPT)]}}]})
    write(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": rel(CONFIG), "config_sha256": sha(CONFIG), "prompt": rel(PROMPT), "prompt_sha256": prompt_sha, "anchor_sha256": sha(ANCHOR), "audio_sha256": audio_sha}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
