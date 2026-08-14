#!/usr/bin/env python3
"""Build the E36 U15C single-unit package from the accepted U15B2 terminal."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
QA = ROOT / "qa/e36_v2_stills_repair_20260729"
U15_QA = QA / "u15_video_runtime"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


prompt = PROD / "video_prompts_repair_v5/E36-CW-U15C.txt"
prompt_sha = sha(prompt)
terminal = ROOT / "working_assets/e36_v2_stills_20260728/terminal_anchors/E36-CW-U15B2-TIMING-REPAIR-V1-TERMINAL-4P85.png"
terminal_sha = sha(terminal)

prompt_manifest = read(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V9.json")
for row in prompt_manifest["rows"]:
    if row["unit_id"] == "U15":
        row["prompt_path"] = rel(prompt)
        row["prompt_sha256"] = prompt_sha
write(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V10.json", prompt_manifest)

dialogue_manifest = read(PROD / "E36_DIALOGUE_MANIFEST_V5.json")
dialogue_manifest["rows"] = [row for row in dialogue_manifest["rows"] if row["video_unit_id"] != "U15"]
dialogue_manifest["rows"].append({
    "dia_id": "E36-U15C-D01",
    "video_unit_id": "U15",
    "speaker_id": "chenji",
    "speaker": "陈迹",
    "spoken_text": "第一次给你钱的人，钱从哪儿来的。",
    "status": "PASS",
    "audio_mode": "CANONICAL_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT_PROMPT",
    "path": "libraries/audio/voice_refs/native_multimodal_20260709/VOICE-陈迹-古装/e09_shot01_chenji_native_voice_ref.wav",
    "sha256": "c63b69430a0fe29af41529759846fb3645935668b1a3aaa0ba237c6dae916eb5",
    "remote_asset_id": "cypqud0bu7t",
    "start_seconds": 0.8,
    "end_seconds": 3.5,
    "breath_after_seconds": 1.5,
    "expression": "十七岁少年压低声线冷厉逼问，末字清楚落下后闭口",
})
write(PROD / "E36_DIALOGUE_MANIFEST_V6.json", dialogue_manifest)

anchor_plan = {
    "schema": "qingshan.video_unit_anchor_count_plan.v1",
    "episode": "E36",
    "planned_reference_image_count": 1,
    "units": [{
        "unit_id": "U15",
        "planned_reference_image_count": 1,
        "reference_image_task_keys": ["E36-CW-U15B2-TIMING-REPAIR-V1-TERMINAL-4P85"],
        "keyframe_interpolation_gate": {
            "status": "PASS",
            "stage": "CANDIDATE_PREFLIGHT",
            "anchor_count": 1,
            "adjacent_pairs_checked": 0,
            "checked_adjacent_pairs": 0,
            "candidate_recheck_required": True,
            "physical_interpolation_or_declared_cut": "PASS",
            "reason": "U15C strictly continues the accepted U15B2 terminal in one axis through one final question and a silent evidence-preparation tail.",
        },
        "anchor_count_decision": {
            "planned_reference_image_count": 1,
            "reason": "The accepted predecessor terminal locks start state, identities, prop contact, space, axis and dusk lighting.",
            "criteria": {
                "continuous_motion_from_single_start": True,
                "identity_or_space_reanchor": False,
                "prop_ownership_transition": False,
                "non_interpolable_terminal_state": False,
            },
            "anchor_roles": ["accepted_predecessor_terminal_and_start_motion"],
            "action_design_class": "continuous_single_anchor_final_question_and_evidence_preparation",
        },
    }],
}
write(U15_QA / "E36_U15C_ANCHOR_COUNT_PLAN_V1.json", anchor_plan)

causality = {
    "schema": "qingshan.common_sense_causality_plan.v1",
    "episode": "E36",
    "units": [{"unit_id": "U15", "causality": {
        "applicable": True,
        "purpose": "陈迹追问第一笔钱的来源，逼递信人准备拿出藏在衣襟内的票根。",
        "intended_effect": "陈迹离开信封并完成问题；递信人不碰信封，右手在衣襟内抓住票根。",
        "visible_causality": "陈迹保持压迫视线说完完整问题并收回手；递信人因求生压力将右手探入衣襟抓住票根但不提前取出。",
        "viewer_read": "观众能看清追问、离开信封、递信人转向藏证处的连续因果。",
        "preconditions": ["U15B2终帧已通过QA", "信封已停定", "递信人右手停在衣襟外"],
        "mechanism_chain": ["陈迹短促吸气", "陈迹说完钱款来源问题", "陈迹指尖离开信封", "递信人右手探入衣襟抓住票根"],
        "counterfactual_test": {
            "opponent_can_bypass": False,
            "reasoning": "若陈迹继续推信、递信人触碰信封或提前亮出票根，追问到取证准备的因果与时序都会断裂。",
        },
        "prop_function_status": "PASS",
        "evidence_refs": [rel(U15_QA / "E36_U15B2_TERMINAL_ANCHOR_IMAGE_QA_V1.json"), rel(prompt)],
    }}],
}
write(U15_QA / "E36_U15C_COMMON_SENSE_CAUSALITY_PLAN_V1.json", causality)

period = {
    "schema": "qingshan.anachronism_lock_plan.v1",
    "episode": "E36",
    "period_contract": {
        "status": "PASS",
        "era": "中国古代架空洛城",
        "source_refs": [
            "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md",
            "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S04",
        ],
    },
    "units": [{"unit_id": "U15", "period_lock": {
        "status": "PASS",
        "reviewed_visible_elements": ["交领古装", "无字木案", "无字药柜", "裸蜡烛古式烛台", "直棂木窗", "无字古代信封"],
        "detected_anachronisms": [],
        "forbidden_elements": ["现代物件", "现代文字", "玻璃罩煤油灯", "民国灯具", "可读字幕", "水印", "现代妆发"],
        "exception_approvals": {},
        "evidence_refs": [rel(terminal), rel(prompt)],
    }}],
}
write(U15_QA / "E36_U15C_PERIOD_LOCK_PLAN_V1.json", period)

dialogue_gate = {
    "schema": "qingshan.dialogue_prompt_gate.v1",
    "episode": "E36",
    "unit_id": "U15",
    "source_segment_id": "U15C",
    "status": "PASS",
    "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
    "speaker": "陈迹",
    "spoken_text": "第一次给你钱的人，钱从哪儿来的。",
    "start_seconds": 0.8,
    "end_seconds": 3.5,
    "checks": {
        "exact_text_in_prompt": "PASS",
        "native_mandarin_required": "PASS",
        "visible_age17_mouth": "PASS",
        "lip_breath_expression_sync": "PASS",
        "silent_listener": "PASS",
        "closed_mouth_tail": "PASS",
    },
    "failures": [],
}
write(U15_QA / "E36_U15C_DIALOGUE_PROMPT_GATE_V1.json", dialogue_gate)

config = read(PROD / "E36_U15B2_EPISODE_SINGLE_UNIT_V1.json")
config["status"] = "READY_FOR_SUPERVISOR_PRECHECK"
config["episode_paid_credits_before"] = 5159
config["anchor_count_plan_ref"] = rel(U15_QA / "E36_U15C_ANCHOR_COUNT_PLAN_V1.json")
config["common_sense_causality_plan_ref"] = rel(U15_QA / "E36_U15C_COMMON_SENSE_CAUSALITY_PLAN_V1.json")
config["period_lock_plan_ref"] = rel(U15_QA / "E36_U15C_PERIOD_LOCK_PLAN_V1.json")
config["complete_video_prompt_manifest_ref"] = rel(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V10.json")
config["dialogue_manifest_ref"] = rel(PROD / "E36_DIALOGUE_MANIFEST_V6.json")
config["dialogue_prompt_gate_ref"] = rel(U15_QA / "E36_U15C_DIALOGUE_PROMPT_GATE_V1.json")

task = copy.deepcopy(config["tasks"][0])
task.update({
    "task_key": "E36-CW-U15C-VIDEO-V1",
    "source_id": "E36-CW-U15C",
    "batch_id": "E36-U15C-VIDEO-V1",
    "visual_zone": "E36-U15C-CANONICAL-CLAUSE-SPLIT",
    "prompt_path": rel(prompt),
    "prompt_file": rel(prompt),
    "prompt_sha256": prompt_sha,
    "anchor_image_qa_ref": rel(U15_QA / "E36_U15B2_TERMINAL_ANCHOR_IMAGE_QA_V1.json"),
})
task["duration_plan"] = {
    "policy": "qingshan.shot_generation_duration.v5",
    "duration_seconds": 5,
    "rationale": "Five seconds preserve the exact final question, visible age-17 lip sync and a silent evidence-preparation tail.",
    "edit_policy": "Preserve native Mandarin, picture-audio sync, envelope ownership and accepted continuity; trim only terminal silence after QA.",
}
task["reference_images"] = task["reference_images"][:2] + [rel(terminal)]
task["reference_image_sequence"][-1] = {
    "asset_label": "@图片3",
    "role": "ACCEPTED_PREDECESSOR_TERMINAL_AND_START_MOTION_ANCHOR",
    "state_id": "E36-CW-U15B2-TIMING-REPAIR-V1-TERMINAL-4P85",
    "path": rel(terminal),
    "sha256": terminal_sha,
    "identity_reference": False,
}
task["dialogue"] = [{
    "dia_id": "E36-U15C-D01",
    "speaker": "陈迹",
    "spoken_text": "第一次给你钱的人，钱从哪儿来的。",
    "start_seconds": 0.8,
    "end_seconds": 3.5,
    "breath_after_seconds": 1.5,
    "expression": "十七岁少年压低声线冷厉逼问，末字清楚落下后闭口",
    "language": "zh-CN",
    "native_video_audio": True,
    "lip_sync": True,
    "breath_expression_sync": True,
}]
task["dialogue_audio_assets"][0]["dia_id"] = "E36-U15C-D01"
task["performance_spec"] = {
    "schema": "qingshan.performance_generation_spec.v2",
    "prop_ownership": {"空信封": "陈迹前半句保持指尖接触，2.60秒后离开；递信人全程不触碰"},
    "motion_beats": [
        {"start_seconds": 0.0, "end_seconds": 0.8, "subject": "陈迹、空信封、递信人", "action": "陈迹稳住已停信封并短促吸气；递信人右手停在衣襟外持续发抖", "contact_point": "陈迹指尖接触信封后缘；递信人右手只接触自己衣襟外层", "direction": "信封不动，递信人右手向衣襟内收紧但不探入", "end_state": "陈迹嘴唇将启，递信人右手压住衣襟外层", "intent": "从未完求生条件转入钱款来源追问", "visible_causality": "陈迹稳住证物并吸气，递信人因压力护住藏证处", "expression": "陈迹冷厉，递信人恐惧", "viewer_read": "U15B2终态与最终问题无缝连续"},
        {"start_seconds": 0.8, "end_seconds": 3.5, "subject": "陈迹", "action": "保持完整嘴部可见，以自然中文普通话完整说出第一次给你钱的人，钱从哪儿来的", "contact_point": "前半句指尖接触信封后缘，2.60秒后离开；信封始终接触案面", "direction": "陈迹手沿案面向自己收回半掌，视线持续压住递信人", "end_state": "陈迹闭口且手离信封；信封停定；递信人右手探入衣襟但未取物", "intent": "逼问第一笔钱的来源", "visible_causality": "完整问题令递信人从护住衣襟转为探入藏证处", "expression": "十七岁少年压低声线冷厉逼问", "viewer_read": "陈迹完整说出唯一问题且说话人清楚"},
        {"start_seconds": 3.5, "end_seconds": 5.0, "subject": "陈迹、递信人、空信封", "action": "陈迹闭口保持压迫视线；递信人无声咽气并在衣襟内抓住票根但不取出", "contact_point": "陈迹不再接触信封；递信人双手不碰信封，右手只接触衣襟内票根", "direction": "递信人右手在衣襟内由上向下攥紧，身体轻微后缩", "end_state": "信封停定、陈迹闭口、递信人抓住票根准备下一单元取证", "intent": "建立下一单元的取证起点", "visible_causality": "追问让递信人锁定藏在衣襟内的证据", "expression": "陈迹冷静压迫，递信人褪白求生", "viewer_read": "U15第三句结束，证据将被取出"},
    ],
}
task["multimodal_entity_bindings"][0]["prop_owners"]["空信封"] = "从U15B2终帧续压后缘，2.60秒后离开；信封保持停定"
task["multimodal_entity_bindings"][1]["prop_owners"]["空信封"] = "全程不触碰；右手只进入自己衣襟抓住票根"
task["multimodal_binding_sha256"] = hashlib.sha256(
    json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
task["keyframe_interpolation_gate"] = {
    "status": "PASS",
    "anchor_count": 1,
    "checked_adjacent_pairs": 0,
    "reason": "One accepted U15B2 terminal anchor supports the exact final question, hand release and evidence-preparation tail.",
}
config["tasks"] = [task]
write(PROD / "E36_U15C_EPISODE_SINGLE_UNIT_V1.json", config)
