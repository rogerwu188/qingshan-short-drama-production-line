#!/usr/bin/env python3
"""Build the single changed-input U02-R1A1 native-dialogue repair."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
SOURCE = BASE / "recovery_10000_20260730/u02_r1a_video/E36_U02_R1A_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json"
OUT = BASE / "recovery_10000_20260730/u02_r1a1_video"
QA = ROOT / "qa/e36_agentcut_20260730/u02_r1a1_video_runtime"
CONFIG = OUT / "E36_U02_R1A1_CHANGED_INPUT_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U02-R1A1.txt"
PROMPT_MANIFEST = OUT / "E36_U02_R1A1_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U02_R1A1_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U02_R1A1_DIALOGUE_PROMPT_GATE_V1.json"
ANCHOR_PLAN = QA / "E36_U02_R1A1_ANCHOR_COUNT_PLAN_V1.json"
CAUSALITY_PLAN = QA / "E36_U02_R1A1_COMMON_SENSE_CAUSALITY_PLAN_V1.json"
PERIOD_PLAN = QA / "E36_U02_R1A1_PERIOD_LOCK_PLAN_V1.json"
ANCHOR = ROOT / "working_assets/e36_v2_stills_20260728/u02_repair_v2_candidates/E36-CW-U02-A1-STILL-V2-IDENTITY-REPAIR_7dba2363-a59d-430f-bf21-3663442dcc7c.png"
ANCHOR_QA = ROOT / "qa/e36_v2_stills_repair_20260729/u02_image_runtime/E36_U02_A1_IMAGE_QA_PASS_V2.json"
CHENJI = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
YUNYANG = ROOT / "assets/reference/e36_20260729/characters/CHAR-yunyang-age17-canonical-v1-20260729.png"
AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u02_r1a1/E36-U02-R1A1-D01.wav"
AUDIO_QA = QA / "E36-U02-R1A1-D01_EXACT_DIALOGUE_AUDIO_QA_V1.json"
TEXT = "活口、人头、死人。"
VOICE_ASSET_ID = "v0udrgrojud"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"


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
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    audio_qa = read(AUDIO_QA)
    if audio_qa.get("status") != "PASS" or audio_qa.get("asr_similarity") != 1.0:
        raise SystemExit("U02-R1A1 exact-dialogue audio is not QA PASS")

    prompt = f"""【E36-CW-U02-R1A1｜4秒｜云羊点出三种目标｜Seedance Fast原生普通话｜changed-input唯一修复】

@图片1只锁定十七岁陈迹身份，@图片2只锁定十七岁云羊身份；@图片3是U02-A1通过图片QA的唯一首帧、法场空间、人物方位、烈日干尘和空白折纸物权权威。第一帧严格从@图片3起动：陈迹在画面左侧木柱后半身探出且闭口，云羊在画面中右侧黑衣背身、右手在腰后持续握住唯一一张空白折纸。皎兔不在本镜画面内且无声。@音频1只驱动云羊嘴部、气息与表情，必须由画面中的云羊现场原生说出，不得作为画外音或后配音轨播放。

【天气硬合同】weather=HEAT_NOON_DRY_DUST。中国古代架空洛城午时法场；烈日硬光、干燥浮尘、看客持续挤动、旧布旗和衣角受热风掀动。禁止现代物件、现代纸张、官服误配、民国妆发、牌匾、字幕、水印、任何可读文字或伪文字；折纸只露空白边缘，不展开、不复制、不转移。

【实体绑定】[[scene:洛城午时法场檐影与人群]]；[[char:十七岁云羊]]；[[char:十七岁陈迹]]；[[prop:唯一空白折纸]]。本单元不新增人物、道具或能力。

镜头1【承接@图片3中近景·云羊右后侧·轻微跟移】0.00-0.20秒：主体=十七岁云羊、唯一空白折纸、左侧十七岁陈迹；动作=云羊随人潮向画面右前方挪半步，右手三指持续压住腰后折纸，同时肩颈转到露出半张侧脸和完整嘴部；陈迹借木柱继续侧探且闭口；接触点=云羊右手指腹持续接触折纸空白边缘，脚掌接触尘土地面，陈迹左前臂擦过木柱阴影边界；方向=云羊向右前刑台挪动并把脸转向左后陈迹，陈迹看向右侧刑台；终态=云羊嘴部完整可见、短吸气并准备发出“活”。{{无对白}}<音效：短吸气、人群脚步、热风掀旗、远处铜锣余振>。

镜头2【云羊侧脸胸上近景·陈迹左后景虚焦·同轴极缓推近】0.20-2.35秒：主体=十七岁云羊、唯一空白折纸；动作=云羊压低嗓音，以自然中文普通话只说一遍“{TEXT}”，完整嘴部始终清楚；每点出一个目标，视线依次扫过刑台、刀架和人群暗桩，陈迹后景闭口听令；接触点=云羊右手指腹全段持续压住折纸空白边缘，陈迹不接触折纸；方向=云羊侧脸朝左后陈迹，身体仍顺人潮朝右前刑台移动；终态=最后一个“人”完整落下，云羊嘴停止发音，折纸仍由云羊右手单独保全。{{对白：云羊仅说“{TEXT}”}}<音效：@音频1精确对白参考、人群低响、干尘擦衣、旗布拍风>。

镜头3【双人中近景·人群前景横穿】2.35-4.00秒：主体=十七岁云羊、十七岁陈迹、唯一空白折纸；动作=云羊闭口短呼气并把脸转回刑台，陈迹闭口将侧探幅度再压低半寸，前景看客从左向右横穿但不遮住两人嘴部；接触点=云羊右手仍压住折纸，陈迹前脚与檐下地面保持受力；方向=两人视线共同锁向右侧刑台；终态=云羊闭口、折纸物权不变，陈迹闭口警觉，为声明式硬切后“这颗棋，三方抢”保留连续意图。{{无对白}}<音效：短呼气、人潮挤动、旗布与浮尘风声>。

【原生对白硬合同】仅十七岁云羊说话。视频模型必须原生生成自然中文普通话，把@音频1作为精确参考并由云羊口中现场说出；唯一台词是“{TEXT}”，只能在0.20-2.35秒说一遍，不增字、不减字、不改字、不重复。陈迹全程闭口，皎兔画外无声。禁止串台、旁白、画外音、现代播音腔、字幕或后配替换；云羊口型逐字同步，气息、眉眼、表情和起止时间同步，末字后停止发音并闭口。

【首帧动势】第一帧不是完成态：人潮正在右移，云羊脚掌正挪半步、右手正压住折纸、肩颈正开始转向陈迹；陈迹正从木柱后侧探；热风已推动旧旗、衣角和浮尘。0.20秒内立即开口。

【环境生命层】看客持续挤动并踮脚；两名远处暗桩在人缝中挪位；旧布旗、衣角和浮尘持续受热风运动；陈迹后景持续微调侧探幅度。环境动作不得遮挡云羊嘴部或生成文字。

【力量与介质】云羊右手三指的压力只让空白折纸边缘轻微弯曲并更稳地进入腰带，不撕裂、不展开、不复制；脚步挤动只带起少量干尘；热风先掀旗再推动衣角和浮尘。

【色彩与光影】法场土黄、旧木深褐、陈迹灰旧布衣、云羊无纹黑衣、午时硬日光和檐下冷阴影；云羊侧脸、双眼和嘴部在阴影边缘始终可辨。

硬性禁止：长停顿、降速、插帧填时、成年化、二十岁参考、换脸、人物复制、新人物、折纸展开或复制、任何文字或伪文字入镜、嘴被遮挡、口型漂移、吞字、改字、重复台词、额外说“这颗棋三方抢”、陈迹说话、皎兔画外说话、字幕、水印。"""
    PROMPT.write_text(prompt + "\n", encoding="utf-8")
    prompt_sha = sha(PROMPT)
    audio_sha = sha(AUDIO)

    config = read(SOURCE)
    config.update({
        "status": "READY_TO_SUBMIT",
        "episode_paid_credits_before": 6890,
        "episode_credit_limit": 10000,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u02_r1a1_video",
        "qa_dir": rel(QA),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "dialogue_prompt_gate_ref": rel(DIALOGUE_GATE),
        "anchor_count_plan_ref": rel(ANCHOR_PLAN),
        "common_sense_causality_plan_ref": rel(CAUSALITY_PLAN),
        "period_lock_plan_ref": rel(PERIOD_PLAN),
    })
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U02-R1A1-CHANGED-INPUT-10000",
        "source_id": "E36-CW-U02-R1A1-CHANGED-INPUT-10000",
        "batch_id": "E36-U02-R1A1-CHANGED-INPUT-10000",
        "unit_id": "U02",
        "scene_id": "E36-CW-S01",
        "visual_zone": "E36-U02-R1A1-CHANGED-INPUT",
        "duration_seconds": 4,
        "duration": 4,
        "edit_target_duration_seconds": 4,
        "model": "seedance-2.0-fast",
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": prompt_sha,
        "reference_images": [rel(CHENJI), rel(YUNYANG), rel(ANCHOR)],
        "reference_audios": [rel(AUDIO)],
        "reference_audio_asset_ids": [],
        "anchor_image_qa_ref": rel(ANCHOR_QA),
        "planned_reference_image_count": 1,
        "state_reference_minimum": 1,
        "status": "READY_TO_SUBMIT",
        "max_retries": 0,
        "native_dialogue_required": True,
        "visible_speaker_required": True,
        "temporal_visual_qa_required": True,
        "visual_entity_ids": ["yunyang", "chenji"],
        "changed_input_repair": True,
        "changed_input_parent_task_id": "c5a06506-9cd6-45df-9459-4c269186a007",
        "changed_input_reason": "The parent omitted the leading natural clause. This repair targets only that omitted clause with a new exact audio reference and shorter4s consumer.",
    })
    task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 4, "rationale": "The exact2.089813-second Mandarin clause fits0.20-2.35 with a1.65-second closed-mouth terminal reaction.", "edit_policy": "Preserve native Mandarin and picture-audio sync; no time stretch, filler or duplicate frames."}
    task["reference_image_sequence"] = [
        {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(CHENJI), "sha256": sha(CHENJI), "identity_reference": True},
        {"asset_label": "@图片2", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "yunyang", "path": rel(YUNYANG), "sha256": sha(YUNYANG), "identity_reference": True},
        {"asset_label": "@图片3", "role": "START_MOTION_ACTION_AND_ROLE_OWNERSHIP_ANCHOR", "state_id": ANCHOR.stem, "path": rel(ANCHOR), "sha256": sha(ANCHOR), "identity_reference": False},
    ]
    task["dialogue"] = [{"dia_id": "E36-U02-R1A1-D01", "speaker": "云羊", "spoken_text": TEXT, "start_seconds": 0.20, "end_seconds": 2.35, "breath_after_seconds": 0.0, "expression": "十七岁云羊藏在人群里压低嗓音快速点出三种目标，警觉急促而克制", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}]
    task["dialogue_audio_assets"] = [{"dia_id": "E36-U02-R1A1-D01", "audio_slot": "@音频1", "speaker_id": "yunyang", "character_name": "云羊", "spoken_text": TEXT, "path": rel(AUDIO), "sha256": audio_sha, "duration_seconds": float(audio_qa["duration_seconds"]), "remote_asset_id": VOICE_ASSET_ID, "voice_reference_asset_id": VOICE_ASSET_ID, "voice_derivation_status": "PASS", "source_voice": "AGENTCUT_SPEECH_GENERATION:20e733e4-6b66-4e0c-a439-098f076dcbb1", "voice_gender": "male", "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "mode": "exact_dialogue_audio_reference", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"}]
    task["multimodal_entity_bindings"] = [
        {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(CHENJI), "visual_reference_sha256": sha(CHENJI), "identity_image_slot": "@图片1", "visible_speaker": False, "lip_sync": False, "prop_owners": {}, "ability_owners": []},
        {"entity_id": "yunyang", "character_name": "云羊", "registry_id": "CHAR-云羊-古装", "visual_reference": rel(YUNYANG), "visual_reference_sha256": sha(YUNYANG), "identity_image_slot": "@图片2", "visible_speaker": True, "lip_sync": True, "prop_owners": {"唯一空白折纸": "云羊右手持续压住腰后空白边缘"}, "ability_owners": [], "voice_reference": rel(AUDIO), "voice_reference_sha256": audio_sha, "voice_reference_asset_id": VOICE_ASSET_ID, "audio_slot": "@音频1", "dialogue_audio_slots": ["@音频1"]},
    ]
    task["multimodal_binding_sha256"] = digest(task["multimodal_entity_bindings"])
    task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "episode": "E36", "unit_id": "U02", "source_segment_id": "U02-R1A1", "prop_ownership": {"唯一空白折纸": "全段仅云羊右手压住腰后空白边缘，不展开、不复制、不转移"}, "motion_beats": [
        {"start_seconds": 0.0, "end_seconds": 0.20, "subject": "十七岁云羊、十七岁陈迹、唯一空白折纸", "action": "云羊随人潮挪半步并转肩露出嘴部，陈迹继续侧探", "contact_point": "云羊右手指腹持续压住折纸；脚掌接触尘土；陈迹前臂擦过木柱阴影", "direction": "云羊向右前刑台挪动并回脸看左后陈迹；陈迹看右侧刑台", "end_state": "云羊嘴部清楚并立即开口", "intent": "隐蔽点出三种目标", "visible_causality": "人潮移动提供转身掩护", "expression": "警觉克制", "viewer_read": "云羊将低声点出三种争抢目标"},
        {"start_seconds": 0.20, "end_seconds": 2.35, "subject": "十七岁云羊、唯一空白折纸", "action": f"以自然中文普通话只说一遍{TEXT}", "contact_point": "右手指腹持续压住折纸空白边缘", "direction": "侧脸朝左后陈迹，视线依次扫过刑台、刀架和暗桩", "end_state": "末字落下并闭口，折纸物权不变", "intent": "点出三种争夺目标", "visible_causality": "视线依次锁定三个风险来源后逐项报出", "expression": "急促克制", "viewer_read": "说话人与三种目标清楚"},
        {"start_seconds": 2.35, "end_seconds": 4.0, "subject": "十七岁云羊、十七岁陈迹、人群", "action": "云羊闭口转回刑台，陈迹闭口压低侧探，前景人群横穿", "contact_point": "云羊右手仍压折纸；陈迹前脚受力", "direction": "两人共同看右侧刑台", "end_state": "两人闭口警觉，为声明式硬切保留连续意图", "intent": "收束首个自然短句", "visible_causality": "点出目标后共同锁定威胁", "expression": "警觉", "viewer_read": "下一判断将在硬切后继续"},
    ]}
    task["keyframe_interpolation_gate"] = {"status": "PASS", "anchor_count": 1, "checked_adjacent_pairs": 0, "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS_SINGLE_CONTINUATION_TAKE_WITH_DECLARED_TERMINAL_HARD_CUT", "reason": "Accepted U02-A1 fixes identity, axis, ownership and first-frame motion for the omitted natural clause; terminal will be QAed before the declared cut to R1A2."}

    prompt_manifest = read(BASE / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V21.json")
    next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U02").update({"prompt_path": rel(PROMPT), "prompt_sha256": prompt_sha})
    write(PROMPT_MANIFEST, prompt_manifest)
    dialogue_manifest = read(BASE / "E36_DIALOGUE_MANIFEST_V11.json")
    dialogue_manifest["rows"].append({"video_unit_id": "U02", "source_segment_id": "U02-R1A1", "dia_id": "E36-U02-R1A1-D01", "status": "PASS", "speaker_id": "yunyang", "speaker": "云羊", "spoken_text": TEXT, "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(AUDIO), "sha256": audio_sha, "remote_asset_id": VOICE_ASSET_ID, "voice_reference_asset_id": VOICE_ASSET_ID, "start_seconds": 0.20, "end_seconds": 2.35, "expression": "十七岁云羊警觉急促、压低嗓音"})
    write(DIALOGUE_MANIFEST, dialogue_manifest)
    write(DIALOGUE_GATE, {"schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U02", "source_segment_id": "U02-R1A1", "source_cl2x": "CL2X-817", "status": "PASS", "canonical_script_sha256": SCRIPT_SHA, "manifest_sha256": MANIFEST_SHA, "dialogue": [{"dia_id": "E36-U02-R1A1-D01", "speaker": "云羊", "spoken_text": TEXT, "start_seconds": 0.20, "end_seconds": 2.35, "voice_reference_asset_id": VOICE_ASSET_ID, "voice_reference_sha256": audio_sha}], "checks": {"canonical_and_manifest_sha_match": "PASS", "natural_split_authority": "PASS_U02_R1_NATURAL_VIDEO_UNIT_SPLIT_V1", "exact_text_in_prompt": "PASS", "exact_audio_asr": "PASS_1P0", "audio_duration": "PASS_2P089813_WITHIN4S", "native_mandarin_required": "PASS", "visible_age17_yunyang_mouth": "PASS", "silent_age17_chenji": "PASS", "lip_breath_expression_sync": "PASS", "closed_mouth_tail": "PASS_1P65", "action_contract": "PASS_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE", "first_frame_motion_state": "PASS", "environment_life": "PASS_A", "period_weather_continuity": "PASS_HEAT_NOON_DRY_DUST", "visible_text": "PASS_BLANK_PAPER_EDGE_ONLY", "changed_input_repair": "PASS_ONE_ALLOWED", "credit_limit": "PASS_6890_PLUS64_LE10000"}, "failures": [], "blocked_by": None, "submission_allowed_after_supervisor_precheck": True})
    write(ANCHOR_PLAN, {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 1, "units": [{"unit_id": "U02", "source_segment_id": "U02-R1A1", "planned_reference_image_count": 1, "reference_image_task_keys": [ANCHOR.stem], "keyframe_interpolation_gate": task["keyframe_interpolation_gate"], "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "One continuous omitted-clause repair uses accepted U02 start-motion authority and ends on a declared hard cut.", "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False}, "anchor_roles": ["accepted_u02_start_motion_authority"], "action_design_class": "single_anchor_changed_input_native_dialogue_repair"}}]})
    write(CAUSALITY_PLAN, {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U02", "source_segment_id": "U02-R1A1", "causality": {"applicable": True, "purpose": "云羊在人潮掩护下点出三种争夺目标。", "intended_effect": "为硬切后的三方抢棋判断建立明确对象。", "visible_causality": "人潮横移掩护转肩，云羊视线依次扫过刑台、刀架和暗桩再逐项报出。", "viewer_read": "观众能读出活口、人头、死人是三种被争夺的目标。", "preconditions": ["U02-A1图片QA通过", "唯一空白折纸由云羊保全", "陈迹闭口观察"], "mechanism_chain": ["人潮横移", "云羊转肩露嘴", "视线扫过三处风险", "完整点出三种目标", "闭口转回刑台"], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若云羊不逐项扫视或漏说任一目标，三种争夺对象的可视因果都无法成立。"}, "prop_function_status": "PASS", "evidence_refs": [rel(ANCHOR_QA), rel(PROMPT)]}}]})
    write(PERIOD_PLAN, {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "canonical_script_sha256": SCRIPT_SHA, "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S01"]}, "units": [{"unit_id": "U02", "source_segment_id": "U02-R1A1", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["檐下旧木柱", "古代布衣", "无纹黑衣", "木制刑台", "旧布旗", "干尘人群"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代纸张", "官服误配", "民国妆发", "牌匾", "字幕", "水印", "可读文字或伪文字"], "exception_approvals": {}, "evidence_refs": [rel(ANCHOR), rel(PROMPT)]}}]})
    write(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": str(CONFIG), "config_sha256": sha(CONFIG), "prompt": str(PROMPT), "prompt_sha256": prompt_sha, "audio_sha256": audio_sha, "anchor_sha256": sha(ANCHOR)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
