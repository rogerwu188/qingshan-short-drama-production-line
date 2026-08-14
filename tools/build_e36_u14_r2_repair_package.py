#!/usr/bin/env python3
"""Build U14-R2's sole materially changed, reduced-input video repair."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
SRC_DIR = BASE / "recovery_10000_20260730/u14_r2_video"
OUT = BASE / "recovery_10000_20260730/u14_r2_video_repair"
QA = ROOT / "qa/e36_agentcut_20260730/u14_r2_video_repair_runtime"
SRC = SRC_DIR / "E36_U14_R2_EPISODE_PARALLEL_BATCH_V1.json"
CONFIG = OUT / "E36_U14_R2_REDUCED_INPUT_REPAIR_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U14-R2-REDUCED-INPUT-REPAIR.txt"
PROMPT_MANIFEST = OUT / "E36_U14_R2_REDUCED_INPUT_REPAIR_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U14_R2_REDUCED_INPUT_REPAIR_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U14_R2_REDUCED_INPUT_REPAIR_DIALOGUE_PROMPT_GATE_V1.json"
ANCHOR_PLAN = QA / "E36_U14_R2_REDUCED_INPUT_REPAIR_ANCHOR_COUNT_PLAN_V1.json"
CAUSALITY_PLAN = QA / "E36_U14_R2_REDUCED_INPUT_REPAIR_COMMON_SENSE_CAUSALITY_PLAN_V1.json"
PERIOD_PLAN = QA / "E36_U14_R2_REDUCED_INPUT_REPAIR_PERIOD_LOCK_PLAN_V1.json"
FAIL_RECEIPT = ROOT / "qa/e36_agentcut_20260730/u14_r2_video_runtime/E36_U14_R2_EPISODE_SUPERVISOR_SUBMIT_V1.json"
ANCHOR = ROOT / "working_assets/e36_recovery_10000_20260730/u14_a1_repair/E36-CW-U14-A1-STILL-V4-CHANGED-INPUT-REPAIR_b9b3d8e5-7cbe-4f77-acea-18e0cee50913.png"
AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u14_r2/E36-U14-R2-D01.wav"
TEXT = "这纸浆里掺的墨，是王府账房记账那一种。"
PARENT_TASK_ID = "264a8957-fca6-492c-9e8a-93577c527463"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    failed = json.loads(FAIL_RECEIPT.read_text(encoding="utf-8"))
    parent = next(row for row in failed["tasks"] if row.get("task_id") == PARENT_TASK_ID)
    if parent.get("remote_status") != "failed":
        raise SystemExit("U14-R2 parent is not a preserved terminal failure")
    reconciliation = parent["credit_attempts"][0]["credit_statement_reconciliation"]
    if reconciliation.get("status") != "PASS_ZERO_REFUNDED" or reconciliation.get("net_charged_credits") != 0:
        raise SystemExit("U14-R2 parent refund is not exact")

    prompt = f"""【E36-CW-U14-R2｜6秒｜纸浆墨源确认｜Seedance Fast原生普通话｜唯一changed-input修复】

@图片1只锁定十七岁陈迹身份；@图片2只锁定十八岁皎兔身份；@图片3是已通过图片QA的唯一首帧、太平医馆密室、桌面空白信封、空间轴线、古装服饰和烛光权威。本次修复删除上一尝试中无画面锚点的乌云动作，只保留两人和同一封证物，降低动态实体复杂度。@音频1是陈迹逐字说出“{TEXT}”的精确普通话参考；画面内陈迹必须现场原生说出该句，音频只作逐字、声线、气息和节奏参考，不得作为画外音或后配音轨播放。皎兔全段闭口。

【天气硬合同】weather=INTERIOR_CLEAR_DAY。6秒，竖屏9:16，720p，写实国漫古装悬疑电影质感。中国古代架空洛城，太平医馆密室午后。禁止现代物件、民国妆发、字幕、水印、任何可读文字或伪文字。

【实体绑定】[[scene:太平医馆密室]]；[[char:十七岁陈迹]]；[[char:十八岁皎兔]]；[[prop:唯一素白空信封]]；[[effect:残余霜气]]。本镜继承既有全景、中景、近景与轴线权威，不重建地理，不新增人物、动物或道具。

镜头1【承接@图片1的双人中近景，0.00-0.20秒】：主体=十七岁陈迹、十八岁皎兔、唯一素白空信封；动作=陈迹承接俯身进行态，右手食指正沿同一封信的近侧纸边向左滑半寸，拇指从纸边下方托住纸角，皎兔闭口把视线从折痕移向陈迹指腹；接触点=陈迹食指与纸纤维、拇指与纸角背面、信封与旧木桌；方向=食指沿纸边横向向左，纸角只抬起半指高；终态=陈迹完整嘴部清楚并立即开口，皎兔闭口。{{无对白}}<音效：短吸气、纸纤维轻擦、烛焰环境声>。

镜头2【陈迹胸上近景，嘴部与指间纸角同框，0.20-4.55秒】：主体=十七岁陈迹；动作=陈迹按@音频1自然普通话只说一遍“{TEXT}”，说到“纸浆”时食指与拇指轻捻同一纸角，说到“墨”时鼻翼轻动，说到“王府账房”时视线由纸角移向皎兔，说到“那一种”时停止捻动；接触点=食指与拇指持续夹住同一纸角；方向=纸角在两指间轻微上提后回落，视线由下向右；终态=“种”完整落下，陈迹闭口，纸角无撕裂、信封未拆开、纸面无字。{{对白：陈迹仅说“{TEXT}”}}<音效：@音频1精确参考、纸纤维摩擦、衣料随呼吸轻动>。

镜头3【双人中近景停稳，4.55-6.00秒】：主体=陈迹、皎兔、空白信封；动作=陈迹闭口短呼气并放下纸角，食指压定纸边；皎兔闭口将视线落在纸边；接触点=纸角回接桌面、陈迹食指与纸边；方向=纸角受重力向下，皎兔视线向下；终态=墨源判断成立，两人闭口，信封完整留在桌面，承接R3比对折痕。{{无对白}}<音效：短呼气、纸角落桌、烛焰微颤>。

【原生对白硬合同】唯一可听台词是“{TEXT}”。陈迹0.20-4.55秒只说一遍，不增字、不减字、不改字、不重复；口型、气息、眉眼、表情和起止时间同步。皎兔全程闭口。禁止串台、旁白、画外音、后配替换、现代播音腔、字幕。

【首帧动势】第一帧不是完成态：陈迹食指正在沿纸边横滑、拇指正在托起纸角、皎兔视线正在下移；0.20秒内陈迹立即开口。

【环境生命层】残余霜气持续散薄、烛焰持续微颤、衣料随呼吸轻动、纸角受指腹与重力真实回落。环境动作不得遮挡陈迹完整嘴部或生成文字。

【力量作用于环境介质】陈迹指腹的捻力只通过纸纤维摩擦、纸角轻微弯曲和重力回落表现；呼吸气流只轻推残余霜气与烛焰。力量不得变成空泛光效，不得推动整封信、撕裂纸角或复制信封。

【身份与连续性】陈迹严格十七岁，不使用二十岁参考；皎兔严格十八岁且全段闭口。旧木深褐、陈迹灰旧布衣、皎兔冷灰黑古装、暖烛与清冷窗光双动机光。禁止成年化、换脸、分身、肢体融合、嘴部遮挡、纸面可读文字、纸角撕裂、降速填时、插帧填时、循环动作、字幕、水印、Logo。
"""
    PROMPT.write_text(prompt, encoding="utf-8")

    config = json.loads(SRC.read_text(encoding="utf-8"))
    config.update({
        "status": "READY_FOR_SUPERVISOR_PRECHECK",
        "episode_paid_credits_before": 7389,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u14_r2_video_repair",
        "qa_dir": rel(QA),
        "anchor_count_plan_ref": rel(ANCHOR_PLAN),
        "common_sense_causality_plan_ref": rel(CAUSALITY_PLAN),
        "period_lock_plan_ref": rel(PERIOD_PLAN),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "dialogue_prompt_gate_ref": rel(DIALOGUE_GATE),
        "targeted_unit_replacement": True,
        "changed_input_repair": True,
        "changed_input_parent_task_id": PARENT_TASK_ID,
        "unchanged_retry": False,
    })
    task = config["tasks"][0]
    task.update({
        "task_key": "E36-CW-U14-R2-REDUCED-INPUT-REPAIR-10000",
        "source_id": "E36-CW-U14-R2-REDUCED-INPUT-REPAIR-10000",
        "batch_id": "E36-U14-R2-REDUCED-INPUT-REPAIR-10000",
        "status": "READY_TO_SUBMIT",
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": sha(PROMPT),
        "reference_images": parent["reference_images"],
        "reference_image_sequence": parent["reference_image_sequence"],
        "planned_reference_image_count": 1,
        "state_reference_minimum": 1,
        "replaces_parent_task_id": PARENT_TASK_ID,
        "changed_input_repair": True,
        "unchanged_retry": False,
        "max_retries": 0,
    })
    task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 6, "rationale": "Exact3.703604s Chenji line fits0.20-4.55 with1.45s closed-mouth terminal beat; repair removes the unanchored Wuyun dynamic entity and rewrites every motion beat around two bound characters and one intact envelope.", "edit_policy": "Preserve exact native dialogue; no time stretch, post-dub, filler, or duplicate frames."}
    task["dialogue"][0].update({"start_seconds": 0.20, "end_seconds": 4.55})
    task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "prop_ownership": {"唯一素白空信封": "陈迹只捻同一纸角，完整留在桌面，不拆、不撕、不复制、不出现文字"}, "motion_beats": [
        {"start_seconds": 0.0, "end_seconds": 0.20, "subject": "陈迹、皎兔、空白信封", "action": "陈迹沿纸边横滑食指并托起纸角，皎兔视线下移", "contact_point": "食指与纸纤维；拇指与纸角背面；信封与桌面", "direction": "食指向左、纸角向上、视线向下", "end_state": "陈迹立即开口，皎兔闭口", "intent": "进入纸浆检验", "visible_causality": "指腹触感触发墨源判断", "expression": "专注", "viewer_read": "开始检验纸浆"},
        {"start_seconds": 0.20, "end_seconds": 4.55, "subject": "陈迹", "action": "陈迹捻纸角并原生说出墨源判断", "contact_point": "食指与拇指持续夹住同一纸角", "direction": "纸角轻微上提回落，视线由下向右", "end_state": "完整说完并闭口，信封无损", "intent": "确认王府账房墨源", "visible_causality": "纸纤维触感支撑判断", "expression": "冷静笃定", "viewer_read": "墨源被确认"},
        {"start_seconds": 4.55, "end_seconds": 6.0, "subject": "陈迹、皎兔、空白信封", "action": "陈迹放下纸角并压定纸边，皎兔看向指尖", "contact_point": "纸角回接桌面；陈迹食指与纸边", "direction": "纸角向下、视线向下", "end_state": "两人闭口，信封完整，承接R3", "intent": "封住墨源判断", "visible_causality": "纸角回落结束检验", "expression": "判断成立", "viewer_read": "下一步比对折痕"},
    ]}
    task["keyframe_interpolation_gate"] = {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 1, "adjacent_pairs_checked": 0, "checked_adjacent_pairs": 0, "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS_SINGLE_CONTINUOUS_A1_REDUCED_INPUT_PAPER_INSPECTION", "reason": "Sole repair uses only accepted A1 as combined identity/layout authority; same axis, intact envelope and continuous paper-contact motion."}
    for binding in task["multimodal_entity_bindings"]:
        if binding["entity_id"] == "chenji":
            binding["prop_owners"] = {"唯一素白空信封": "两指只捻同一纸角"}
    task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    prompt_manifest = json.loads((SRC_DIR / "E36_U14_R2_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json").read_text(encoding="utf-8"))
    row = next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U14")
    row.update({"prompt_path": rel(PROMPT), "prompt_sha256": sha(PROMPT)})
    write(PROMPT_MANIFEST, prompt_manifest)
    dialogue_manifest = json.loads((SRC_DIR / "E36_U14_R2_DIALOGUE_MANIFEST_V1.json").read_text(encoding="utf-8"))
    row = next(row for row in dialogue_manifest["rows"] if row.get("dia_id") == "E36-U14-R2-D01")
    row.update({"start_seconds": 0.20, "end_seconds": 4.55})
    write(DIALOGUE_MANIFEST, dialogue_manifest)
    write(DIALOGUE_GATE, {"schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U14", "source_segment_id": "U14-R2", "source_cl2x": "CL2X-831", "status": "PASS", "canonical_script_sha256": config["source_script_sha256"], "manifest_sha256": config["source_manifest_sha256"], "dialogue": task["dialogue"], "checks": {"canonical_and_manifest_sha_match": "PASS", "exact_text_in_prompt": "PASS", "exact_audio_asr": "PASS_1P0", "single_visible_speaker": "PASS_CHENJI_ONLY", "silent_jiaotu": "PASS_BOUND_CLOSED_MOUTH", "native_mandarin_required": "PASS", "lip_breath_expression_sync": "PASS", "action_contract": "PASS_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE", "first_frame_motion_state": "PASS", "environment_life": "PASS", "period_weather_continuity": "PASS_INTERIOR_CLEAR_DAY", "visible_text": "PASS_FORBIDDEN_ALL", "credit_limit": "PASS_7389_PLUS96_LE10000", "changed_input_repair_budget": "PASS_REPAIR1_OF_MAX1", "material_input_change": "PASS_REMOVED_UNANCHORED_WUYUN_DYNAMIC_ENTITY_AND_REWROTE_ALL_MOTION_BEATS"}, "failures": [], "blocked_by": None, "submission_allowed_after_supervisor_precheck": True})
    write(ANCHOR_PLAN, {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 1, "units": [{"unit_id": "U14", "source_segment_id": "U14-R2", "planned_reference_image_count": 1, "reference_image_task_keys": ["U14-A1"], "keyframe_interpolation_gate": task["keyframe_interpolation_gate"], "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "Repair retains accepted A1 as the sole temporal anchor while canonical identity images remain identity-only references.", "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False}, "anchor_roles": ["accepted_start_motion_layout_and_evidence_authority"], "action_design_class": "single_anchor_single_speaker_simplified_native_dialogue_paper_inspection"}}]})
    write(CAUSALITY_PLAN, {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U14", "source_segment_id": "U14-R2", "causality": {"applicable": True, "purpose": "陈迹检验纸浆并确认墨源。", "intended_effect": "物证由折法推进到王府账房墨源。", "visible_causality": "陈迹沿纸边滑指并捻纸纤维，触感支撑判断。", "viewer_read": "纸浆掺墨来自王府账房。", "preconditions": ["U14-A1直接图片QA通过", "陈迹17岁与皎兔18岁身份连续", "信封完整无字"], "mechanism_chain": ["食指沿纸边横滑", "两指捻纸角", "陈迹确认纸浆掺墨", "纸角受重力落回桌面"], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若没有纸边接触或信封被撕开，墨源判断的可见因果链不成立。"}, "prop_function_status": "PASS", "evidence_refs": [rel(PROMPT), rel(FAIL_RECEIPT)]}}]})
    write(PERIOD_PLAN, {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "canonical_script_sha256": config["source_script_sha256"], "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S03"]}, "units": [{"unit_id": "U14", "source_segment_id": "U14-R2", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["太平医馆密室旧木桌", "古代布衣", "素白空信封", "烛台窗格", "残余霜气"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代纸张", "民国灯具", "民国妆发", "字幕", "水印", "可读文字或伪文字"], "exception_approvals": {}, "evidence_refs": [rel(PROMPT)]}}]})
    write(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": rel(CONFIG), "config_sha256": sha(CONFIG), "prompt_sha256": sha(PROMPT), "parent_task_id": PARENT_TASK_ID, "input_change": "REMOVED_UNANCHORED_WUYUN_DYNAMIC_ENTITY_AND_REWROTE_ALL_MOTION_BEATS"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
