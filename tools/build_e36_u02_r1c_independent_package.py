#!/usr/bin/env python3
"""Build E36 U02-R1C as an independent exact-dialogue continuation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
SOURCE_DIR = BASE / "recovery_10000_20260730/u02_r1b_video"
SOURCE = SOURCE_DIR / "E36_U02_R1B_EPISODE_PARALLEL_BATCH_V1.json"
OUT = BASE / "recovery_10000_20260730/u02_r1c_video"
QA = ROOT / "qa/e36_agentcut_20260730/u02_r1c_video_runtime"
CONFIG = OUT / "E36_U02_R1C_INDEPENDENT_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U02-R1C-INDEPENDENT.txt"
PROMPT_MANIFEST = OUT / "E36_U02_R1C_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U02_R1C_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U02_R1C_DIALOGUE_PROMPT_GATE_V1.json"
ANCHOR_PLAN = QA / "E36_U02_R1C_ANCHOR_COUNT_PLAN_V1.json"
CAUSALITY_PLAN = QA / "E36_U02_R1C_COMMON_SENSE_CAUSALITY_PLAN_V1.json"
PERIOD_PLAN = QA / "E36_U02_R1C_PERIOD_LOCK_PLAN_V1.json"

CHENJI = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
YUNYANG = ROOT / "assets/reference/e36_20260729/characters/CHAR-yunyang-age17-canonical-v1-20260729.png"
ANCHOR = ROOT / "qa/e36_agentcut_20260730/u02_r1_video_runtime/E36-CW-U02-R1A2-SELECTED-SOURCE-NATIVE-NATURAL-PAUSE-V2_terminal_2p30.jpg"
ANCHOR_QA = ROOT / "qa/e36_agentcut_20260730/u02_r1_video_runtime/E36_U02_R1A2_TERMINAL_ANCHOR_IMAGE_QA_V2.json"
AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u02_r1/E36-U02-R1-D03.wav"
AUDIO_QA = ROOT / "qa/e36_agentcut_20260730/u02_r1_video_runtime/E36-U02-R1-D03_EXACT_DIALOGUE_AUDIO_QA_V1.json"
AUDIO_RECEIPT = ROOT / "workflow/tasks/E36_U02_R1_D03_CHENJI_EXACT_DIALOGUE_AUDIO_GENERATION_V1.json"
TEXT = "伤一个，咱们就是劫法场的钦犯。人，只能从刀下换走。"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"
MAILBOX_SHA = "e312167d86b7c7ad46335034259c9a1ed3b2099af739573488cbc1293a61be14"
VOICE_ASSET_ID = "cypqud0bu7t"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    audio_qa = json.loads(AUDIO_QA.read_text(encoding="utf-8"))
    audio_receipt = json.loads(AUDIO_RECEIPT.read_text(encoding="utf-8"))
    anchor_qa = json.loads(ANCHOR_QA.read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json").read_text(encoding="utf-8"))
    if sha(ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md") != SCRIPT_SHA:
        raise SystemExit("canonical script SHA drift")
    if manifest.get("sha256") != SCRIPT_SHA:
        raise SystemExit("manifest does not bind the canonical script")
    if sha(ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json") != MANIFEST_SHA:
        raise SystemExit("manifest file SHA drift")
    if audio_qa.get("status") != "PASS" or audio_qa.get("asr_similarity") != 1.0:
        raise SystemExit("D03 exact audio is not ASR1.0 PASS")
    if sha(AUDIO) != audio_qa.get("wav_sha256") or audio_receipt.get("spoken_text") != TEXT:
        raise SystemExit("D03 exact audio provenance mismatch")
    if anchor_qa.get("verdict") != "PASS_CONTINUATION_AUTHORITY" or sha(ANCHOR) != anchor_qa.get("asset_sha256"):
        raise SystemExit("R1A2 terminal anchor is not accepted exact-SHA authority")

    prompt = f"""【E36-CW-U02-R1C｜8秒｜刀下换人｜Seedance Fast原生普通话｜独立转录恢复单元】

@图片1只锁定十七岁陈迹身份；@图片2只锁定十七岁云羊身份；@图片3是已通过图片QA的U02-R1A2终态，锁定洛城西市刑台、人群、木柱、人物站位与云羊腰后唯一空白折纸。@音频1是陈迹逐字说出“{TEXT}”的精确普通话参考；视频模型必须让画面内陈迹现场原生说出该句，只作逐字、声线、气息和节奏参考，不得作为画外音或后配音播放。云羊全段闭口。

【天气硬合同】weather=HEAT_NOON_DRY_DUST。8秒，竖屏9:16，720p，写实古装悬疑动作电影质感。中国古代架空洛城，西市刑台正午。禁止现代物件、民国妆发、字幕、水印、任何可读文字或伪文字。

【色彩与动机光】土黄尘雾、灰旧布衣、黑色短打、被正午硬日光晒白的木台与屋檐深影；陈迹完整脸和嘴在0.20-6.10秒持续清楚，光只来自高位烈日和屋檐反光。

【实体绑定】[[scene:洛城西市刑台外围]]；[[char:十七岁陈迹]]；[[char:十七岁云羊]]；[[prop:云羊腰后唯一空白折纸]]；[[prop:木柱与人群护栏]]。不新增主角、灵物、兵器或书写道具。

镜头1【同轴双人中近景承接，0.00-0.20秒】：主体=陈迹、云羊、移动人群；动作=严格从@图片3起动，陈迹从左侧木柱后继续探出半步并抬起左手靠近云羊右上臂，云羊在中景闭口转头；接触点=陈迹前脚与尘地、云羊右手与腰后空白折纸；方向=陈迹由画面左后向右前靠近云羊；终态=陈迹嘴部清楚并立即开口，左掌尚未碰到云羊。{{无对白}}<音效：人群脚步、木台吱响、风卷干尘、短吸气>。

镜头2【双人胸上近景稳定跟随左移，0.20-3.55秒】：主体=陈迹、云羊；动作=陈迹按@音频1自然普通话说“伤一个，咱们就是劫法场的钦犯。”，同时左掌压住云羊右上臂把他从官差方向轻拉回屋檐阴影；接触点=陈迹左掌与云羊右上臂衣料；方向=云羊重心由画面右前退向左后木柱；终态=“钦犯”二字落下，云羊已退回半步、仍闭口且双手不碰官差。{{对白：陈迹只说前半句}}<音效：@音频1精确参考、衣料受力、脚底擦尘、人群低声>。

镜头3【双人胸上近景缓慢横移，3.55-6.10秒】：主体=陈迹、云羊、远处刑台刃架；动作=陈迹不中断地继续说“人，只能从刀下换走。”，左掌从云羊上臂滑到肩后稳定他，右手食指沿人群缝隙指向刑台刃架下方的囚位；接触点=陈迹左掌与云羊肩后衣料、右手食指悬空指向远处；方向=左掌向左后稳定云羊，右手由胸前向画面右上刑台伸出；终态=“走”字完整落下，陈迹闭口，云羊顺着指向看向刑台，双方均未碰官差或兵器。{{对白：陈迹只继续说完后半句}}<音效：@音频1连续精确参考、远处绳索轻响、风尘与呼吸>。

镜头4【双人观察位中近景停稳，6.10-8.00秒】：主体=陈迹、云羊、人群、远处官差；动作=陈迹闭口收回右手，左掌离开云羊肩后；云羊闭口把重心压低，两人借横移人群遮住身形并观察囚位；接触点=两人鞋底与尘地、云羊右手持续压住腰后折纸；方向=陈迹右手由外向胸侧收回，两人视线由官差移至囚位；终态=两人闭口藏在人群和木柱后，官差无人受伤，救人路径锁定在刀下囚位，折纸仍唯一且无字。{{无对白}}<音效：闭口呼气、人群横移、旗布与风尘环境声>。

【原生对白硬合同】唯一可听台词是“{TEXT}”。陈迹0.20-6.10秒只说一遍，不增字、不减字、不改字、不重复；完整嘴部清楚，口型、气息、眉眼、表情与起止时间同步。云羊全程闭口。禁止串台、旁白、画外音、后配替换、现代播音腔、字幕。

【首帧动势与环境生命层】第一帧不是完成态：陈迹正在从柱后探出、前脚压尘、左手正抬向云羊上臂；云羊正在回头。人群持续横移、旗布被热风拉动、干尘掠过脚踝、远处官差巡动、衣料随呼吸牵动，背景不得冻结。

【力量作用于环境介质】左掌压上臂先使衣料起褶，再让云羊重心退回半步；滑到肩后时手掌与衣料持续贴合，不穿模、不吸附。右手只悬空指向刑台，不触碰官差、刀刃或护栏。禁止肢体融合、瞬移、复制和武器凭空出现。

【身份与连续性】陈迹严格十七岁灰袍，云羊严格十七岁黑衣；沿用@图片3同一屋檐、木柱、人群与刑台轴线。云羊腰后唯一空白折纸全段不展开、不复制、不转移、无字。不得成年化、换脸、分身、同脸复制、嘴部遮挡。禁止降速填时、插帧填时、循环动作、字幕、水印、Logo。
"""
    PROMPT.write_text(prompt, encoding="utf-8")
    prompt_sha = sha(PROMPT)
    audio_sha = sha(AUDIO)
    anchor_sha = sha(ANCHOR)

    config = json.loads(SOURCE.read_text(encoding="utf-8"))
    config.update({
        "status": "READY_TO_SUBMIT",
        "episode_paid_credits_before": 7585,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u02_r1c_video",
        "qa_dir": rel(QA),
        "anchor_count_plan_ref": rel(ANCHOR_PLAN),
        "common_sense_causality_plan_ref": rel(CAUSALITY_PLAN),
        "period_lock_plan_ref": rel(PERIOD_PLAN),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "dialogue_prompt_gate_ref": rel(DIALOGUE_GATE),
    })
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U02-R1C-INDEPENDENT-10000",
        "source_id": "E36-CW-U02-R1C-INDEPENDENT-10000",
        "batch_id": "E36-U02-R1C-INDEPENDENT-10000",
        "source_segment_id": "U02-R1C",
        "visual_zone": "E36-U02-EXECUTION-SQUARE-KNIFE-EXTRACTION",
        "duration_seconds": 8,
        "duration": 8,
        "edit_target_duration_seconds": 8,
        "status": "READY_TO_SUBMIT",
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": prompt_sha,
        "reference_images": [rel(CHENJI), rel(YUNYANG), rel(ANCHOR)],
        "reference_image_asset_ids": ["r3rjxeppfq", "dhcauzvcq9t", "p334y6fcx3"],
        "reference_audios": [rel(AUDIO)],
        "reference_audio_asset_ids": ["yqcpvz4ampf"],
        "planned_reference_image_count": 1,
        "state_reference_minimum": 1,
        "changed_input_repair": False,
        "changed_input_parent_task_id": None,
        "changed_input_reason": "Independent canonical D03 recovery unit; not a retry of U02-R1B D02.",
        "unchanged_retry": False,
        "max_retries": 0,
        "anchor_image_qa_ref": rel(ANCHOR_QA),
    })
    task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 8, "rationale": "Exact5.793417s Chenji sentence fits0.20-6.10 with1.90s closed-mouth tactical tail.", "edit_policy": "Preserve exact native sentence and continuous pull-back/point/observe action; no retiming, post-dub, filler or repeated frames."}
    task["reference_image_sequence"] = [
        {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(CHENJI), "sha256": sha(CHENJI), "identity_reference": True},
        {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "yunyang", "path": rel(YUNYANG), "sha256": sha(YUNYANG), "identity_reference": True},
        {"asset_label": "@图片3", "role": "ACCEPTED_R1A2_TERMINAL_CONTINUATION_ANCHOR", "state_id": "U02-R1A2-TERMINAL", "path": rel(ANCHOR), "sha256": anchor_sha, "identity_reference": False},
    ]
    task["dialogue"] = [{"dia_id": "E36-U02-R1-D03", "speaker": "陈迹", "spoken_text": TEXT, "start_seconds": 0.20, "end_seconds": 6.10, "breath_after_seconds": 0.0, "expression": "十七岁陈迹克制划定不伤官差的底线并指出刀下换人路径", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}]
    task["dialogue_audio_assets"] = [{"dia_id": "E36-U02-R1-D03", "speaker_id": "chenji", "character_name": "陈迹", "spoken_text": TEXT, "audio_slot": "@音频1", "path": rel(AUDIO), "sha256": audio_sha, "duration_seconds": audio_qa["duration_seconds"], "voice_reference_asset_id": VOICE_ASSET_ID, "voice_derivation_status": "PASS", "source_voice": f"AGENTCUT_SPEECH_GENERATION:{audio_receipt['task_id']}", "voice_gender": "male", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"}]
    beats = [
        {"start_seconds": 0.0, "end_seconds": 0.20, "subject": "陈迹、云羊、移动人群", "action": "陈迹从柱后探出半步并抬左手靠近云羊上臂", "contact_point": "陈迹前脚与尘地；云羊右手与腰后折纸", "direction": "陈迹由左后向右前靠近", "end_state": "陈迹嘴部清楚，左掌尚未接触", "intent": "隐蔽制止", "visible_causality": "人群横移提供掩护", "expression": "警觉克制", "viewer_read": "陈迹即将划定底线"},
        {"start_seconds": 0.20, "end_seconds": 3.55, "subject": "陈迹、云羊", "action": "陈迹说前半句并压住云羊右上臂将其轻拉回阴影", "contact_point": "陈迹左掌与云羊右上臂衣料", "direction": "云羊重心由右前退向左后木柱", "end_state": "云羊退回半步且不碰官差", "intent": "防止伤官差", "visible_causality": "口头底线伴随撤回动作", "expression": "低声坚决", "viewer_read": "行动约束产生后果"},
        {"start_seconds": 3.55, "end_seconds": 6.10, "subject": "陈迹、云羊、远处刑台刃架", "action": "陈迹说完后半句，左掌稳定云羊肩后，右手指向刀下囚位", "contact_point": "左掌与云羊肩后衣料；右手悬空", "direction": "左掌向左后稳定，右手向右上刑台伸出", "end_state": "陈迹闭口，云羊看向囚位，双方不碰官差兵器", "intent": "指出换人路径", "visible_causality": "刀下囚位对应救人方案", "expression": "冷静决断", "viewer_read": "救人路径锁定"},
        {"start_seconds": 6.10, "end_seconds": 8.0, "subject": "陈迹、云羊、人群", "action": "陈迹收手离开云羊肩后，两人借人群遮住身形观察囚位", "contact_point": "两人鞋底与尘地；云羊右手压腰后折纸", "direction": "右手收向胸侧，视线由官差移至囚位", "end_state": "两人闭口隐蔽、官差安全、折纸唯一无字", "intent": "形成行动终态", "visible_causality": "路线判断后进入观察位", "expression": "克制警觉", "viewer_read": "即将从刀下救人"},
    ]
    task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "episode": "E36", "unit_id": "U02", "source_segment_id": "U02-R1C", "prop_ownership": {"云羊腰后唯一空白折纸": "全段仅云羊右手压住腰后，不展开、不复制、不转移"}, "motion_beats": beats}
    task["multimodal_entity_bindings"] = [
        {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(CHENJI), "visual_reference_sha256": sha(CHENJI), "identity_image_slot": "@图片1", "visible_speaker": True, "lip_sync": True, "voice_reference": rel(AUDIO), "voice_reference_sha256": audio_sha, "voice_reference_asset_id": VOICE_ASSET_ID, "audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1"], "prop_owners": {}, "ability_owners": []},
        {"entity_id": "yunyang", "character_name": "云羊", "registry_id": "CHAR-云羊-古装", "visual_reference": rel(YUNYANG), "visual_reference_sha256": sha(YUNYANG), "identity_image_slot": "@图片2", "visible_speaker": False, "lip_sync": False, "prop_owners": {"云羊腰后唯一空白折纸": "云羊右手持续压住"}, "ability_owners": []},
    ]
    task["multimodal_binding_sha256"] = digest(task["multimodal_entity_bindings"])
    task["keyframe_interpolation_gate"] = {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 1, "adjacent_pairs_checked": 0, "checked_adjacent_pairs": 0, "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS_SINGLE_CONTINUATION_TAKE", "reason": "Accepted R1A2 terminal fixes the execution-square axis and both identities; all new motion is a continuous pull-back, point and settle chain."}

    prompt_manifest = json.loads((SOURCE_DIR / "E36_U02_R1B_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json").read_text(encoding="utf-8"))
    next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U02").update({"prompt_path": rel(PROMPT), "prompt_sha256": prompt_sha})
    write(PROMPT_MANIFEST, prompt_manifest)
    dialogue_manifest = json.loads((SOURCE_DIR / "E36_U02_R1B_DIALOGUE_MANIFEST_V1.json").read_text(encoding="utf-8"))
    dialogue_manifest["rows"] = [row for row in dialogue_manifest["rows"] if row.get("video_unit_id") != "U02"]
    dialogue_manifest["rows"].append({"video_unit_id": "U02", "source_segment_id": "U02-R1C", "dia_id": "E36-U02-R1-D03", "status": "PASS", "speaker_id": "chenji", "speaker": "陈迹", "spoken_text": TEXT, "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(AUDIO), "sha256": audio_sha, "remote_asset_id": VOICE_ASSET_ID, "voice_reference_asset_id": VOICE_ASSET_ID, "start_seconds": 0.20, "end_seconds": 6.10, "expression": "克制划定底线并指出刀下换人路径"})
    write(DIALOGUE_MANIFEST, dialogue_manifest)
    write(DIALOGUE_GATE, {"schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U02", "source_segment_id": "U02-R1C", "source_cl2x": "CL2X-836", "source_mailbox_sha256": MAILBOX_SHA, "status": "PASS", "canonical_script_sha256": SCRIPT_SHA, "manifest_sha256": MANIFEST_SHA, "dialogue": task["dialogue"], "checks": {"canonical_and_manifest_sha_match": "PASS", "exact_text_in_prompt": "PASS", "exact_audio_asr": "PASS_1P0", "source_speech_duration": "PASS_5P793417_WITHIN8S", "single_visible_speaker": "PASS_CHENJI_ONLY", "silent_yunyang": "PASS_BOUND_CLOSED_MOUTH", "native_mandarin_required": "PASS", "lip_breath_expression_sync": "PASS", "closed_mouth_tail": "PASS_1P90", "action_contract": "PASS_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE", "first_frame_motion_state": "PASS", "environment_life": "PASS", "period_weather_continuity": "PASS_HEAT_NOON_DRY_DUST", "visible_text": "PASS_FORBIDDEN_ALL", "credit_limit": "PASS_7585_PLUS128_LE10000", "independent_lane": "PASS_NOT_U02_R1B_REPLAY"}, "failures": [], "blocked_by": None, "submission_allowed_after_supervisor_precheck": True})
    write(ANCHOR_PLAN, {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 1, "units": [{"unit_id": "U02", "source_segment_id": "U02-R1C", "planned_reference_image_count": 1, "reference_image_task_keys": ["U02-R1A2-TERMINAL"], "keyframe_interpolation_gate": task["keyframe_interpolation_gate"], "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "One accepted continuation anchor fixes the axis for a continuous action without ownership transition.", "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False}, "anchor_roles": ["accepted_r1a2_terminal_continuation_authority"], "action_design_class": "single_anchor_exact_dialogue_tactical_continuation"}}]})
    write(CAUSALITY_PLAN, {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U02", "source_segment_id": "U02-R1C", "causality": {"applicable": True, "purpose": "陈迹制止伤害官差并指出从刀下换人的救法。", "intended_effect": "云羊退回掩护位并把注意力转向囚位。", "visible_causality": "左掌压上臂拉回、滑到肩后稳定、右手指向囚位、两人藏回人群。", "viewer_read": "他们不是冲撞官差，而是准备在行刑瞬间换人。", "preconditions": ["R1A2终态图片QA通过", "陈迹云羊均17岁", "官差与刑台轴线沿用"], "mechanism_chain": ["陈迹接近", "左掌拉回云羊", "右手指明囚位", "两人进入观察位"], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若没有拉回和指向，台词的底线与行动路径没有可见结果。"}, "prop_function_status": "PASS", "evidence_refs": [rel(PROMPT), rel(ANCHOR_QA), rel(AUDIO_QA)]}}]})
    write(PERIOD_PLAN, {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "canonical_script_sha256": SCRIPT_SHA, "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", f"{config['scene_contract_ref']}#E36-CW-S01"]}, "units": [{"unit_id": "U02", "source_segment_id": "U02-R1C", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["西市木质刑台", "古代交领布衣", "木柱护栏", "官差古装", "唯一空白折纸"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代文字", "民国服装", "现代武器"], "exception_approvals": {}, "evidence_refs": [rel(ANCHOR), rel(PROMPT)]}}]})
    write(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": rel(CONFIG), "config_sha256": sha(CONFIG), "prompt": rel(PROMPT), "prompt_sha256": prompt_sha, "audio_sha256": audio_sha, "anchor_sha256": anchor_sha}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
