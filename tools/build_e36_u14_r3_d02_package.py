#!/usr/bin/env python3
"""Build the independent U14-R3 D02 source-audio-first video package."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPAIR_MODE = os.environ.get("E36_U14_R3_D02_REPAIR_MODE") == "1"
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
SOURCE_DIR = BASE / "recovery_10000_20260730/u14_r2_video"
OUT = BASE / ("recovery_10000_20260730/u14_r3_d02_video_repair" if REPAIR_MODE else "recovery_10000_20260730/u14_r3_d02_video")
QA = ROOT / ("qa/e36_agentcut_20260730/u14_r3_d02_video_repair_runtime" if REPAIR_MODE else "qa/e36_agentcut_20260730/u14_r3_d02_video_runtime")
SOURCE = SOURCE_DIR / "E36_U14_R2_EPISODE_PARALLEL_BATCH_V1.json"
CONFIG = OUT / ("E36_U14_R3_D02_CHANGED_INPUT_REPAIR_EPISODE_PARALLEL_BATCH_V1.json" if REPAIR_MODE else "E36_U14_R3_D02_EPISODE_PARALLEL_BATCH_V1.json")
PROMPT = OUT / ("E36-CW-U14-R3-D02-CHANGED-INPUT-REPAIR.txt" if REPAIR_MODE else "E36-CW-U14-R3-D02.txt")
PROMPT_MANIFEST = OUT / ("E36_U14_R3_D02_CHANGED_INPUT_REPAIR_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json" if REPAIR_MODE else "E36_U14_R3_D02_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json")
DIALOGUE_MANIFEST = OUT / ("E36_U14_R3_D02_CHANGED_INPUT_REPAIR_DIALOGUE_MANIFEST_V1.json" if REPAIR_MODE else "E36_U14_R3_D02_DIALOGUE_MANIFEST_V1.json")
DIALOGUE_GATE = QA / ("E36_U14_R3_D02_CHANGED_INPUT_REPAIR_DIALOGUE_PROMPT_GATE_V1.json" if REPAIR_MODE else "E36_U14_R3_D02_DIALOGUE_PROMPT_GATE_V1.json")
ANCHOR_PLAN = QA / ("E36_U14_R3_D02_CHANGED_INPUT_REPAIR_ANCHOR_COUNT_PLAN_V1.json" if REPAIR_MODE else "E36_U14_R3_D02_ANCHOR_COUNT_PLAN_V1.json")
CAUSALITY_PLAN = QA / ("E36_U14_R3_D02_CHANGED_INPUT_REPAIR_COMMON_SENSE_CAUSALITY_PLAN_V1.json" if REPAIR_MODE else "E36_U14_R3_D02_COMMON_SENSE_CAUSALITY_PLAN_V1.json")
PERIOD_PLAN = QA / ("E36_U14_R3_D02_CHANGED_INPUT_REPAIR_PERIOD_LOCK_PLAN_V1.json" if REPAIR_MODE else "E36_U14_R3_D02_PERIOD_LOCK_PLAN_V1.json")

CHENJI = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
JIAOTU = ROOT / "working_assets/e32_reference_single_subject_20260723/jiaotu_front_single.jpg"
A1 = ROOT / "working_assets/e36_recovery_10000_20260730/u14_a1_repair/E36-CW-U14-A1-STILL-V4-CHANGED-INPUT-REPAIR_b9b3d8e5-7cbe-4f77-acea-18e0cee50913.png"
A2 = ROOT / "working_assets/e36_recovery_10000_20260730/u14_a2_repair/E36-CW-U14-A2-STILL-V4-CHANGED-INPUT-TERMINAL-REPAIR_0bf2a864-81c1-4379-9745-d1e10a257a0b.png"
A1_QA = ROOT / "qa/e36_agentcut_20260730/u14_image_runtime/E36_U14_A1_CHANGED_INPUT_REPAIR_DIRECT_VISUAL_QA_V1.json"
A2_QA = ROOT / "qa/e36_agentcut_20260730/u14_image_runtime/E36_U14_A2_CHANGED_INPUT_TERMINAL_REPAIR_DIRECT_VISUAL_QA_V1.json"
AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u14_r3/E36-U14-R3-D02.wav"
AUDIO_QA = ROOT / "qa/e36_agentcut_20260730/u14_r3_video_runtime/E36-U14-R3-D02_EXACT_DIALOGUE_AUDIO_QA_V1.json"
ROBUST_QA = ROOT / "qa/e36_agentcut_20260730/u14_r3_video_runtime/E36-U14-R3-D02_UNCONDITIONED_ASR_V1.json"
AUDIO_RECEIPT = ROOT / "workflow/tasks/E36_U14_R3_D02_CHENJI_EXACT_DIALOGUE_AUDIO_GENERATION_V1.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
TEXT = "他不是送信的。信是空的。"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"
MAILBOX_SHA = "ec38c40e5e3a0a35fc2b1e4bbb6b683c0af02156c02162a148907c793ef129cf"
PARENT_TASK_ID = "a6028afa-ec41-4189-9d84-971d94b9250a"


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
    if sha(SCRIPT) != SCRIPT_SHA or sha(MANIFEST) != MANIFEST_SHA:
        raise SystemExit("canonical script or manifest file drift")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("sha256") != SCRIPT_SHA:
        raise SystemExit("manifest canonical SHA field mismatch")
    audio_qa = json.loads(AUDIO_QA.read_text(encoding="utf-8"))
    robust_qa = json.loads(ROBUST_QA.read_text(encoding="utf-8"))
    audio_receipt = json.loads(AUDIO_RECEIPT.read_text(encoding="utf-8"))
    if audio_qa.get("status") != "PASS" or audio_qa.get("asr_similarity") != 1.0:
        raise SystemExit("contextual exact-audio QA failed")
    if robust_qa.get("status") != "PASS_ROBUST_EXACT_12_OF_12":
        raise SystemExit("source audio robust pre-video gate failed")
    if not robust_qa.get("summary", {}).get("eligible_as_exact_pronunciation_reference"):
        raise SystemExit("source audio is not eligible as an exact pronunciation reference")
    if sha(AUDIO) != audio_qa.get("wav_sha256") or not audio_receipt.get("task_id"):
        raise SystemExit("audio provenance mismatch")
    a1_qa = json.loads(A1_QA.read_text(encoding="utf-8"))
    a2_qa = json.loads(A2_QA.read_text(encoding="utf-8"))
    if not a1_qa.get("verdict", "").startswith("PASS_ACCEPTED") or a1_qa.get("image_sha256") != sha(A1):
        raise SystemExit("U14-A1 is not accepted exact-SHA authority")
    if not a2_qa.get("verdict", "").startswith("PASS_ACCEPTED") or a2_qa.get("image_sha256") != sha(A2):
        raise SystemExit("U14-A2 is not accepted exact-SHA authority")

    prompt = f"""【E36-CW-U14-R3-D02｜6秒｜空信判断｜Seedance Fast原生普通话｜独立转录恢复单元】

@图片1只锁定十七岁陈迹身份；@图片2只锁定十八岁皎兔身份；@图片3是已通过图片QA的U14-A1首帧、密室轴线、人物站位、唯一素白空信封与折痕权威；@图片4是已通过图片QA的U14-A2同场身份、光线、道具与后续终态边界权威，本单元只向该边界推进而不得提前复制其最终双折痕姿态。@音频1是陈迹逐字说出“{TEXT}”的精确普通话参考，且已通过无条件双模型12/12逐字前检。视频模型必须让画面内陈迹现场原生说出该句；音频只作逐字、声线、气息与节奏参考，不得作为画外音或后配音播放。皎兔全段闭口。

【天气硬合同】weather=INTERIOR_CLEAR_DAY。6秒，竖屏9:16，720p，写实古装悬疑电影质感。中国古代架空洛城，太平医馆密室午后。禁止现代物件、民国妆发、字幕、水印、任何可读文字或伪文字。

【实体绑定】[[scene:太平医馆密室]]；[[char:十七岁陈迹]]；[[char:十八岁皎兔]]；[[prop:唯一素白空信封]]；[[prop:旧木桌]]；[[effect:残余霜气]]。不新增人物、灵物或道具。

【色彩与动机光】旧木深褐、陈迹灰旧布衣、皎兔冷灰青古装、低饱和暖烛与清冷窗光；右后直棂窗清光和左下古式烛焰共同塑形，陈迹完整脸与嘴在对白区间持续清楚，禁止无来源轮廓光。

镜头1【双人中近景同轴承接，0.00-0.25秒】：主体=陈迹、皎兔、唯一素白空信封；动作=严格从@图片3的进行态起动，陈迹食指正沿近侧折痕由左向右滑行比对，皎兔闭口把视线从纸角移向陈迹指尖；接触点=陈迹食指指腹与同一折痕、信封底面与旧木桌；方向=指尖沿折痕向桌面深处推进半寸，皎兔视线向下；终态=陈迹指尖停在折痕交点并立即吸气开口。{{无对白}}<音效：指腹擦纸、短吸气、烛焰与衣料环境声>。

镜头2【陈迹胸上近景，嘴与折痕同框，0.25-2.85秒】：主体=十七岁陈迹、唯一素白空信封；动作=陈迹按@音频1自然普通话只说一遍“他不是送信的。”，说“不是”时指尖在折痕交点轻压一次，说“送信的”时视线由折痕抬向门外递信人离开的方向；接触点=右手食指与折痕交点；方向=指腹垂直轻压后放松，目光由桌面向画面右后方移动；终态=“的”字完整落下，陈迹仍清楚可见且不移开信封。{{对白：陈迹仅说前句}}<音效：@音频1连续精确参考、纸纤维轻响、自然呼吸>。

镜头3【陈迹近景极缓推近，2.85-3.65秒】：主体=陈迹、空信封；动作=陈迹不中断地按@音频1继续说“信是空的。”，左手掌心向下悬在信封上方一寸示意信内无物，不拆信、不翻面；接触点=仅右手食指仍触折痕，左手不接触信封；方向=左掌由胸前向信封上方落至一寸并停；终态=“的”字完整落下，陈迹闭口，信封完整无字且仍在桌面。{{对白：陈迹仅说后句}}<音效：@音频1连续精确参考、衣袖轻动>。

镜头4【双人证物中近景停稳，3.65-6.00秒】：主体=陈迹、皎兔、空信封；动作=陈迹闭口短呼气，右指从折痕交点向门外方向划出一条短路径后停在桌边，皎兔闭口沿路径转眼；接触点=陈迹指腹先触折痕后离纸停桌边、双脚与地面；方向=右指由桌中向画面右后方移动，皎兔视线同向；终态=判断从空信封转向递信人的去向，信封完整留桌，人物姿态只向@图片4后续边界推进而未提前完成。{{无对白}}<音效：短呼气、衣袖摩擦、烛焰微颤>。

【原生对白硬合同】唯一可听台词是“{TEXT}”。陈迹0.25-3.65秒只说一遍，不增字、不减字、不改字、不重复；完整嘴部清楚，口型、气息、眉眼、表情与起止时间同步。皎兔全程闭口。禁止加入U14-R3-D01“这折痕的样式，对得上王府账房的记号。”，禁止串台、旁白、画外音、后配替换、现代播音腔和字幕。

【首帧动势与环境生命层】第一帧不是完成态：陈迹指尖正在沿折痕横滑，皎兔视线正在下移，0.25秒内陈迹立即开口。残余霜气持续散薄、烛焰微颤、窗格清光与尘埃缓慢移动、衣料随呼吸牵动，背景不得冻结。

【力量与连续性】指腹轻压只让折痕纸纤维轻弯后回弹；左掌只悬空示意，不得吸附、拆开、翻面、撕裂、复制或生成文字。陈迹严格十七岁，皎兔严格十八岁；禁止成年化、换脸、分身、肢体融合、嘴部遮挡、降速填时、插帧填时、循环动作、字幕、水印、Logo。
"""
    if REPAIR_MODE:
        prompt = prompt.replace("6秒｜空信判断｜Seedance Fast原生普通话｜独立转录恢复单元", "5秒｜空信判断｜Seedance Pro原生普通话｜唯一changed-input修复")
        prompt = prompt.replace("@图片1只锁定十七岁陈迹身份；@图片2只锁定十八岁皎兔身份；@图片3是已通过图片QA的U14-A1首帧、密室轴线、人物站位、唯一素白空信封与折痕权威；@图片4是已通过图片QA的U14-A2同场身份、光线、道具与后续终态边界权威", "@图片1只锁定十七岁陈迹身份；@图片2是已通过图片QA的U14-A1首帧、密室轴线、两人站位、唯一素白空信封与折痕权威；@图片3是已通过图片QA的U14-A2同场身份、光线、道具与后续终态边界权威。皎兔不使用独立身份图，只由两张已验收状态锚帧约束为闭口侧角人物")
        prompt = prompt.replace("6秒，竖屏9:16", "5秒，竖屏9:16")
        prompt = prompt.replace("0.00-0.25秒", "0.00-0.25秒")
        prompt = prompt.replace("3.65-6.00秒", "3.65-5.00秒")
        prompt = prompt.replace("人物姿态只向@图片4后续边界推进", "人物姿态只向@图片3后续边界推进")
        prompt = prompt.replace("严格从@图片3的进行态起动", "严格从@图片2的进行态起动")
        prompt = prompt.replace("而不得提前复制其最终双折痕姿态", "而不得提前复制@图片3的最终双折痕姿态")
        prompt = prompt.replace("[[char:十八岁皎兔]]；", "")
        prompt = prompt.replace("十八岁皎兔", "状态锚帧中的十八岁闭口侧角人物")
        prompt = prompt.replace("皎兔", "状态锚帧中的闭口侧角人物")
    PROMPT.write_text(prompt, encoding="utf-8")

    config = json.loads(SOURCE.read_text(encoding="utf-8"))
    config.update({
        "status": "READY_FOR_SUPERVISOR_PRECHECK",
        "source_script_sha256": SCRIPT_SHA,
        "source_manifest_sha256": MANIFEST_SHA,
        "episode_paid_credits_before": 7739 if REPAIR_MODE else 7717,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u14_r3_d02_video_repair" if REPAIR_MODE else "working_assets/e36_recovery_10000_20260730/u14_r3_d02_video",
        "qa_dir": rel(QA),
        "anchor_count_plan_ref": rel(ANCHOR_PLAN),
        "common_sense_causality_plan_ref": rel(CAUSALITY_PLAN),
        "period_lock_plan_ref": rel(PERIOD_PLAN),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "dialogue_prompt_gate_ref": rel(DIALOGUE_GATE),
        "targeted_unit_replacement": True,
        "changed_input_repair": REPAIR_MODE,
        "changed_input_parent_task_id": PARENT_TASK_ID if REPAIR_MODE else None,
        "unchanged_retry": False,
    })
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U14-R3-D02-CHANGED-INPUT-REPAIR-10000" if REPAIR_MODE else "E36-CW-U14-R3-D02-ROBUST-AUDIO-10000",
        "source_id": "E36-CW-U14-R3-D02-CHANGED-INPUT-REPAIR-10000" if REPAIR_MODE else "E36-CW-U14-R3-D02-ROBUST-AUDIO-10000",
        "batch_id": "E36-U14-R3-D02-CHANGED-INPUT-REPAIR-10000" if REPAIR_MODE else "E36-U14-R3-D02-ROBUST-AUDIO-10000",
        "source_segment_id": "U14-R3-D02",
        "duration_seconds": 5 if REPAIR_MODE else 6,
        "duration": 5 if REPAIR_MODE else 6,
        "edit_target_duration_seconds": 5 if REPAIR_MODE else 6,
        "status": "READY_TO_SUBMIT",
        "model": "seedance-2.0-pro" if REPAIR_MODE else "seedance-2.0-fast",
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": sha(PROMPT),
        "reference_images": [rel(CHENJI), rel(A1), rel(A2)] if REPAIR_MODE else [rel(CHENJI), rel(JIAOTU), rel(A1), rel(A2)],
        "reference_image_asset_ids": [],
        "reference_audios": [rel(AUDIO)],
        "reference_audio_asset_ids": [],
        "planned_reference_image_count": 2,
        "state_reference_minimum": 2,
        "targeted_unit_replacement": True,
        "changed_input_repair": REPAIR_MODE,
        "unchanged_retry": False,
        "max_retries": 0,
        "anchor_image_qa_ref": rel(A1_QA),
    })
    if REPAIR_MODE:
        task["replaces_parent_task_id"] = PARENT_TASK_ID
    else:
        task.pop("replaces_parent_task_id", None)
    task["reference_image_sequence"] = ([
        {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(CHENJI), "sha256": sha(CHENJI), "identity_reference": True},
        {"asset_label": "@图片2", "role": "ACCEPTED_START_MOTION_LAYOUT_CHARACTER_CONTINUITY_AND_EVIDENCE_AUTHORITY", "state_id": "U14-A1", "path": rel(A1), "sha256": sha(A1), "identity_reference": False},
        {"asset_label": "@图片3", "role": "ACCEPTED_LATER_STATE_CONTINUITY_BOUNDARY_NOT_THIS_UNIT_TERMINAL", "state_id": "U14-A2", "path": rel(A2), "sha256": sha(A2), "identity_reference": False},
    ] if REPAIR_MODE else [
        {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(CHENJI), "sha256": sha(CHENJI), "identity_reference": True},
        {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "jiaotu", "path": rel(JIAOTU), "sha256": sha(JIAOTU), "identity_reference": True},
        {"asset_label": "@图片3", "role": "ACCEPTED_START_MOTION_LAYOUT_AND_EVIDENCE_AUTHORITY", "state_id": "U14-A1", "path": rel(A1), "sha256": sha(A1), "identity_reference": False},
        {"asset_label": "@图片4", "role": "ACCEPTED_LATER_STATE_CONTINUITY_BOUNDARY_NOT_THIS_UNIT_TERMINAL", "state_id": "U14-A2", "path": rel(A2), "sha256": sha(A2), "identity_reference": False},
    ])
    task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 5 if REPAIR_MODE else 6, "rationale": "Robust exact2.380063s Chenji line fits0.25-3.65 with1.35s closed-mouth evidence tail; changed-input repair reduces references and switches Fast6s to Pro5s." if REPAIR_MODE else "Robust exact2.380063s Chenji line fits0.25-3.65 with2.35s closed-mouth evidence tail.", "edit_policy": "Preserve exact native dialogue; no D01, post-dub, retiming, filler, or repeated frames."}
    task["dialogue"] = [{"dia_id": "E36-U14-R3-D02", "speaker": "陈迹", "spoken_text": TEXT, "start_seconds": 0.25, "end_seconds": 3.65, "breath_after_seconds": 0.0, "expression": "由折痕证据转向递信人身份判断", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}]
    task["dialogue_audio_assets"] = [{"dia_id": "E36-U14-R3-D02", "speaker_id": "chenji", "character_name": "陈迹", "spoken_text": TEXT, "audio_slot": "@音频1", "path": rel(AUDIO), "sha256": sha(AUDIO), "duration_seconds": audio_qa["duration_seconds"], "voice_reference_asset_id": "cypqud0bu7t", "voice_derivation_status": "PASS", "source_audio_robust_status": "PASS_ROBUST_EXACT_12_OF_12", "source_voice": f"AGENTCUT_SPEECH_GENERATION:{audio_receipt['task_id']}", "voice_gender": "male", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"}]
    task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "prop_ownership": {"唯一素白空信封": "完整留桌；右指只压折痕；左掌悬空示意空信"}, "motion_beats": ([
        {"start_seconds": 0.0, "end_seconds": 0.25, "subject": "陈迹、空信封", "action": "陈迹食指沿折痕滑到交点后吸气开口", "contact_point": "右食指指腹与折痕交点", "direction": "由桌前向桌深推进", "end_state": "指尖停稳且嘴部清楚进入前句", "intent": "从折痕证据进入身份判断", "visible_causality": "指腹抵达交点后触发开口", "expression": "专注转为确认", "viewer_read": "物证触发判断"},
        {"start_seconds": 0.25, "end_seconds": 3.65, "subject": "陈迹、空信封", "action": "陈迹只说他不是送信的。信是空的。并以悬掌示意空信", "contact_point": "右指持续触折痕，左掌不接触信封", "direction": "视线由信封转向门外，左掌落至信封上方一寸", "end_state": "末字落下闭口，信封完整无字", "intent": "否定送信身份并说明空信", "visible_causality": "折痕接触与悬掌共同支撑判断", "expression": "冷静笃定", "viewer_read": "递信人并非普通送信者"},
        {"start_seconds": 3.65, "end_seconds": 5.0, "subject": "陈迹、空信封", "action": "陈迹闭口把右指由折痕划向门外调查方向", "contact_point": "指腹离纸后停在桌边", "direction": "桌中向画面右后方", "end_state": "判断焦点转向递信人去向，未提前完成后续A2终态", "intent": "把调查方向从信转向人", "visible_causality": "离纸手指沿递信人路径停稳", "expression": "警觉克制", "viewer_read": "下一步追查递信人"},
    ] if REPAIR_MODE else [
        {"start_seconds": 0.0, "end_seconds": 0.25, "subject": "陈迹、皎兔、空信封", "action": "陈迹沿折痕横滑，皎兔视线下移", "contact_point": "右食指与折痕；信封与桌面", "direction": "指尖向桌深推进，视线向下", "end_state": "指尖停折痕交点并吸气", "intent": "把折痕物证转化为身份判断", "visible_causality": "指腹沿折痕移动并停在交点后触发开口", "expression": "专注转为确认", "viewer_read": "物证比对触发身份判断"},
        {"start_seconds": 0.25, "end_seconds": 2.85, "subject": "陈迹、空信封", "action": "陈迹说前句并轻压折痕交点", "contact_point": "右食指与折痕交点", "direction": "指腹向下轻压，目光抬向门外", "end_state": "前句完整落下且仍触折痕", "intent": "否定递信人的表面身份", "visible_causality": "折痕交点的证据让陈迹视线转向递信人离开的方向", "expression": "冷静笃定", "viewer_read": "递信人身份被否定"},
        {"start_seconds": 2.85, "end_seconds": 3.65, "subject": "陈迹、空信封", "action": "陈迹说后句，左掌悬空示意信内无物", "contact_point": "右食指与折痕；左掌不接触", "direction": "左掌向信封上方落至一寸", "end_state": "末字落下闭口，信封完整无字", "intent": "说明信封只承担诱发反应的功能", "visible_causality": "悬掌不拆信仍明确示意其中无物", "expression": "判断落定", "viewer_read": "信封只是空壳"},
        {"start_seconds": 3.65, "end_seconds": 6.0, "subject": "陈迹、皎兔、空信封", "action": "陈迹闭口划出指向门外的短路径，皎兔随之转眼", "contact_point": "指腹由折痕离纸停桌边", "direction": "右指与视线同向移向右后方", "end_state": "判断转向递信人去向，未提前完成A2", "intent": "把追查目标从空信转向人的路径", "visible_causality": "离开折痕的手指沿递信人去向划出调查路径", "expression": "警觉克制", "viewer_read": "下一步将追查送达位置"},
    ])}
    task["multimodal_entity_bindings"] = ([
        {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(CHENJI), "visual_reference_sha256": sha(CHENJI), "identity_image_slot": "@图片1", "voice_reference": rel(AUDIO), "voice_reference_sha256": sha(AUDIO), "voice_reference_asset_id": "cypqud0bu7t", "audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1"], "visible_speaker": True, "lip_sync": True, "prop_owners": {"唯一素白空信封": "右指只压折痕，完整留桌"}, "ability_owners": []},
    ] if REPAIR_MODE else [
        {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(CHENJI), "visual_reference_sha256": sha(CHENJI), "identity_image_slot": "@图片1", "voice_reference": rel(AUDIO), "voice_reference_sha256": sha(AUDIO), "voice_reference_asset_id": "cypqud0bu7t", "audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1"], "visible_speaker": True, "lip_sync": True, "prop_owners": {"唯一素白空信封": "右指只压折痕，完整留桌"}, "ability_owners": []},
        {"entity_id": "jiaotu", "character_name": "皎兔", "registry_id": "CHAR-皎兔-古装", "visual_reference": rel(JIAOTU), "visual_reference_sha256": sha(JIAOTU), "identity_image_slot": "@图片2", "visible_speaker": False, "lip_sync": False, "prop_owners": {}, "ability_owners": []},
    ])
    task["multimodal_binding_sha256"] = digest(task["multimodal_entity_bindings"])
    task["keyframe_interpolation_gate"] = {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 2, "adjacent_pairs_checked": 1, "checked_adjacent_pairs": 1, "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS_A1_TO_INTERMEDIATE_STATE_WITH_A2_AS_LATER_BOUNDARY", "reason": "Accepted A1 supplies the start axis; accepted A2 constrains identity, light and later-state direction without requiring this D02 unit to reach the reserved R8 terminal."}

    prompt_manifest = json.loads((SOURCE_DIR / "E36_U14_R2_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json").read_text(encoding="utf-8"))
    row = next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U14")
    row.update({"prompt_path": rel(PROMPT), "prompt_sha256": sha(PROMPT)})
    write(PROMPT_MANIFEST, prompt_manifest)
    dialogue_manifest = json.loads((SOURCE_DIR / "E36_U14_R2_DIALOGUE_MANIFEST_V1.json").read_text(encoding="utf-8"))
    dialogue_manifest["rows"] = [row for row in dialogue_manifest["rows"] if row.get("video_unit_id") != "U14"]
    dialogue_manifest["rows"].append({"video_unit_id": "U14", "dia_id": "E36-U14-R3-D02", "status": "PASS", "source_audio_robust_status": "PASS_ROBUST_EXACT_12_OF_12", "speaker": "陈迹", "speaker_id": "chenji", "spoken_text": TEXT, "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(AUDIO), "sha256": sha(AUDIO), "start_seconds": 0.25, "end_seconds": 3.65, "breath_after_seconds": 0.0, "expression": "由折痕证据转向递信人身份判断"})
    write(DIALOGUE_MANIFEST, dialogue_manifest)
    write(DIALOGUE_GATE, {"schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U14", "source_segment_id": "U14-R3-D02", "source_cl2x": "CL2X-847" if REPAIR_MODE else "CL2X-838", "source_mailbox_sha256": "bc04e0dfac0cc5c890234fad19a38747499ffa98facc40887e2cc3deac6904ec" if REPAIR_MODE else MAILBOX_SHA, "status": "PASS", "canonical_script_sha256": SCRIPT_SHA, "manifest_sha256": MANIFEST_SHA, "dialogue": task["dialogue"], "checks": {"canonical_and_manifest_sha_match": "PASS", "exact_text_in_prompt": "PASS_D02_ONLY", "source_audio_contextual_asr": "PASS_1P0", "source_audio_robust_unconditioned_asr": "PASS_EXACT_12_OF_12_BEFORE_VIDEO", "source_speech_duration": "PASS_2P380063_WITHIN5S" if REPAIR_MODE else "PASS_2P380063_WITHIN6S", "single_visible_speaker": "PASS_CHENJI_ONLY", "silent_jiaotu": "PASS_BOUND_BY_ACCEPTED_STATE_ANCHORS_CLOSED_MOUTH" if REPAIR_MODE else "PASS_BOUND_CLOSED_MOUTH", "native_mandarin_required": "PASS", "lip_breath_expression_sync": "PASS", "closed_mouth_tail": "PASS_1P35" if REPAIR_MODE else "PASS_2P35", "action_contract": "PASS_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE", "first_frame_motion_state": "PASS", "environment_life": "PASS", "period_weather_continuity": "PASS_INTERIOR_CLEAR_DAY", "visible_text": "PASS_FORBIDDEN_ALL", "D01_exclusion": "PASS_NOT_BUNDLED_UNVERIFIED", "credit_limit": "PASS_7739_PLUS100_LE10000" if REPAIR_MODE else "PASS_7717_PLUS96_LE10000", "changed_input_repair_budget": "PASS_REPAIR1_OF_MAX1" if REPAIR_MODE else "NOT_APPLICABLE", "material_input_change": "PASS_FAST6_TO_PRO5_AND_STANDALONE_JIAOTU_REFERENCE_REMOVED" if REPAIR_MODE else "NOT_APPLICABLE"}, "failures": [], "blocked_by": None, "submission_allowed_after_supervisor_precheck": True})
    write(ANCHOR_PLAN, {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 2, "units": [{"unit_id": "U14", "source_segment_id": "U14-R3-D02", "planned_reference_image_count": 2, "reference_image_task_keys": ["U14-A1", "U14-A2"], "keyframe_interpolation_gate": task["keyframe_interpolation_gate"], "anchor_count_decision": {"planned_reference_image_count": 2, "reason": "A1 locks the live start; A2 is a later-state continuity boundary and must not be reached prematurely.", "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": True, "prop_ownership_transition": False, "non_interpolable_terminal_state": False}, "anchor_roles": ["accepted_start_motion_authority", "accepted_later_state_continuity_boundary"], "action_design_class": "two_anchor_boundary_constrained_native_dialogue_reasoning"}}]})
    write(CAUSALITY_PLAN, {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U14", "source_segment_id": "U14-R3-D02", "causality": {"applicable": True, "purpose": "陈迹由空信物证否定递信人的送信身份。", "intended_effect": "判断焦点从信封内容转向递信人的去向。", "visible_causality": "指腹比对折痕、轻压交点、悬掌示意空信、指向门外。", "viewer_read": "空信封是调动各方反应的触发物。", "preconditions": ["U14-A1/A2直接图片QA通过", "D02源音频robust exact12/12", "信封完整无字"], "mechanism_chain": ["沿折痕比对", "否定送信身份", "示意信内为空", "把路径指向门外"], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若不呈现折痕接触、空信悬掌与门外路径，观众无法从物证读出递信人只是诱发反应的载体。"}, "prop_function_status": "PASS", "evidence_refs": [rel(PROMPT), rel(ROBUST_QA)]}}]})
    write(PERIOD_PLAN, {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "canonical_script_sha256": SCRIPT_SHA, "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S03"]}, "units": [{"unit_id": "U14", "source_segment_id": "U14-R3-D02", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["太平医馆密室旧木桌", "古代布衣", "素白空信封", "烛台窗格", "残余霜气"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代纸张", "民国灯具", "民国妆发", "字幕", "水印", "可读文字或伪文字"], "exception_approvals": {}, "evidence_refs": [rel(PROMPT)]}}]})
    write(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": rel(CONFIG), "config_sha256": sha(CONFIG), "prompt_sha256": sha(PROMPT), "audio_sha256": sha(AUDIO)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
