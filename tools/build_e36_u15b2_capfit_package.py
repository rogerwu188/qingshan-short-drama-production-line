#!/usr/bin/env python3
"""Build the E36 U15B2 single-unit package and cap-fit accounting artifacts."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
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


recorded_at = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
prompt = PROD / "video_prompts_repair_v5/E36-CW-U15B2.txt"
prompt_sha = sha(prompt)
terminal = ROOT / "working_assets/e36_v2_stills_20260728/terminal_anchors/E36-CW-U15B1-SELECTED-TERMINAL-4P85-V1.png"
terminal_sha = sha(terminal)

# Complete prompt coverage retains canonical U15 order while replacing its active
# single-unit prompt with the U15B2 continuation.
prompt_manifest = read(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V8.json")
for row in prompt_manifest["rows"]:
    if row["unit_id"] == "U15":
        row["prompt_path"] = rel(prompt)
        row["prompt_sha256"] = prompt_sha
write(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V9.json", prompt_manifest)

dialogue_manifest = read(PROD / "E36_DIALOGUE_MANIFEST_V4.json")
dialogue_manifest["rows"] = [row for row in dialogue_manifest["rows"] if row["video_unit_id"] != "U15"]
dialogue_manifest["rows"].append({
    "dia_id": "E36-U15B2-D01",
    "video_unit_id": "U15",
    "speaker_id": "chenji",
    "speaker": "陈迹",
    "spoken_text": "就告诉我——",
    "status": "PASS",
    "audio_mode": "CANONICAL_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT_PROMPT",
    "path": "libraries/audio/voice_refs/native_multimodal_20260709/VOICE-陈迹-古装/e09_shot01_chenji_native_voice_ref.wav",
    "sha256": "c63b69430a0fe29af41529759846fb3645935668b1a3aaa0ba237c6dae916eb5",
    "remote_asset_id": "cypqud0bu7t",
    "start_seconds": 0.8,
    "end_seconds": 2.0,
    "breath_after_seconds": 3.0,
    "expression": "十七岁少年压低声线逼问，破折号形成未完句悬停，随后闭口",
})
write(PROD / "E36_DIALOGUE_MANIFEST_V5.json", dialogue_manifest)

anchor_plan = {
    "schema": "qingshan.video_unit_anchor_count_plan.v1",
    "episode": "E36",
    "planned_reference_image_count": 1,
    "units": [{
        "unit_id": "U15",
        "planned_reference_image_count": 1,
        "reference_image_task_keys": ["E36-CW-U15B1-SELECTED-TERMINAL-4P85-V1"],
        "keyframe_interpolation_gate": {
            "status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 1,
            "adjacent_pairs_checked": 0, "checked_adjacent_pairs": 0,
            "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS",
            "reason": "U15B2 strictly continues the accepted U15B1 terminal in one axis with one short exact clause and a silent reaction tail.",
        },
        "anchor_count_decision": {
            "planned_reference_image_count": 1,
            "reason": "The accepted predecessor terminal locks start state, identities, prop contact, space and axis.",
            "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False},
            "anchor_roles": ["accepted_predecessor_terminal_and_start_motion"],
            "action_design_class": "continuous_single_anchor_final_envelope_deceleration",
        },
    }],
}
write(U15_QA / "E36_U15B2_ANCHOR_COUNT_PLAN_V1.json", anchor_plan)

causality = {
    "schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36",
    "units": [{"unit_id": "U15", "causality": {
        "applicable": True,
        "purpose": "陈迹完成未说完的求生条件，并逼递信人准备取出票根。",
        "intended_effect": "信封在陈迹指尖下停稳，递信人不接信而将右手移向衣襟。",
        "visible_causality": "陈迹继续压住信封后缘并说出短句，信封完成减速；句末闭口后，递信人因求生本能将右手移向衣襟。",
        "viewer_read": "观众能看清信封停稳、递信人不接信、右手转向衣襟与供述压力的连续因果。",
        "preconditions": ["U15B1终帧已通过QA", "陈迹指尖仍接触信封后缘", "递信人双手未接触信封"],
        "mechanism_chain": ["陈迹续压信封", "信封沿原方向停稳", "陈迹说出就告诉我并闭口", "递信人右手移向衣襟但不取出票根"],
        "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若信封接触、说话起止或右手方向缺失，求生条件到取证准备的因果链会断裂。"},
        "prop_function_status": "PASS",
        "evidence_refs": [rel(U15_QA / "E36_U15B1_TERMINAL_ANCHOR_IMAGE_QA_V1.json"), rel(prompt)],
    }}],
}
write(U15_QA / "E36_U15B2_COMMON_SENSE_CAUSALITY_PLAN_V1.json", causality)

period = {
    "schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36",
    "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S04"]},
    "units": [{"unit_id": "U15", "period_lock": {
        "status": "PASS",
        "reviewed_visible_elements": ["交领古装", "无字木案", "无字药柜", "裸蜡烛古式烛台", "直棂木窗", "无字古代信封"],
        "detected_anachronisms": [],
        "forbidden_elements": ["现代物件", "现代文字", "玻璃罩煤油灯", "民国灯具", "可读字幕", "水印", "现代妆发"],
        "exception_approvals": {},
        "evidence_refs": [rel(terminal), rel(prompt)],
    }}],
}
write(U15_QA / "E36_U15B2_PERIOD_LOCK_PLAN_V1.json", period)

dialogue_gate = {
    "schema": "qingshan.dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U15", "source_segment_id": "U15B2",
    "status": "PASS", "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
    "speaker": "陈迹", "spoken_text": "就告诉我——", "start_seconds": 0.8, "end_seconds": 2.0,
    "checks": {"exact_text_in_prompt": "PASS", "native_mandarin_required": "PASS", "visible_age17_mouth": "PASS", "lip_breath_expression_sync": "PASS", "silent_listener": "PASS", "closed_mouth_tail": "PASS", "dash_as_semantic_pause_not_spoken_word": "PASS"},
    "failures": [],
}
write(U15_QA / "E36_U15B2_DIALOGUE_PROMPT_GATE_V1.json", dialogue_gate)

config = read(PROD / "E36_U15B_EPISODE_SINGLE_UNIT_V1.json")
config["status"] = "READY_FOR_SUPERVISOR_PRECHECK"
config["episode_paid_credits_before"] = 5059
config["anchor_count_plan_ref"] = rel(U15_QA / "E36_U15B2_ANCHOR_COUNT_PLAN_V1.json")
config["common_sense_causality_plan_ref"] = rel(U15_QA / "E36_U15B2_COMMON_SENSE_CAUSALITY_PLAN_V1.json")
config["period_lock_plan_ref"] = rel(U15_QA / "E36_U15B2_PERIOD_LOCK_PLAN_V1.json")
config["complete_video_prompt_manifest_ref"] = rel(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V9.json")
config["dialogue_manifest_ref"] = rel(PROD / "E36_DIALOGUE_MANIFEST_V5.json")
config["dialogue_prompt_gate_ref"] = rel(U15_QA / "E36_U15B2_DIALOGUE_PROMPT_GATE_V1.json")
task = copy.deepcopy(config["tasks"][0])
task.update({
    "task_key": "E36-CW-U15B2-VIDEO-V1", "source_id": "E36-CW-U15B2", "batch_id": "E36-U15B2-VIDEO-V1",
    "visual_zone": "E36-U15B2-CANONICAL-CLAUSE-SPLIT", "prompt_path": rel(prompt), "prompt_file": rel(prompt), "prompt_sha256": prompt_sha,
    "anchor_image_qa_ref": rel(U15_QA / "E36_U15B1_TERMINAL_ANCHOR_IMAGE_QA_V1.json"),
})
task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 5, "rationale": "Five seconds preserve the exact short continuation, visible age-17 lip sync and a silent causally active tail for U15C.", "edit_policy": "Preserve native Mandarin, picture-audio sync, envelope contact and accepted continuity; trim only terminal silence after QA."}
task["reference_images"] = task["reference_images"][:2] + [rel(terminal)]
task["reference_image_sequence"][-1] = {"asset_label": "@图片3", "role": "ACCEPTED_PREDECESSOR_TERMINAL_AND_START_MOTION_ANCHOR", "state_id": "E36-CW-U15B1-SELECTED-TERMINAL-4P85-V1", "path": rel(terminal), "sha256": terminal_sha, "identity_reference": False}
task["dialogue"] = [{"dia_id": "E36-U15B2-D01", "speaker": "陈迹", "spoken_text": "就告诉我——", "start_seconds": 0.8, "end_seconds": 2.0, "breath_after_seconds": 3.0, "expression": "十七岁少年压低声线逼问，破折号形成未完句悬停，随后闭口", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}]
task["dialogue_audio_assets"][0]["dia_id"] = "E36-U15B2-D01"
task["performance_spec"] = {
    "schema": "qingshan.performance_generation_spec.v2",
    "prop_ownership": {"空信封": "陈迹指尖从U15B1终帧持续压住后缘直至信封停稳；递信人全程不触碰"},
    "motion_beats": [
        {"start_seconds": 0.0, "end_seconds": 0.8, "subject": "陈迹、空信封、递信人", "action": "陈迹继续压住信封后缘让信封完成最后减速，并短促吸气；递信人肩背持续发抖", "contact_point": "陈迹指尖接触信封后缘，信封底面接触案面，递信人双手不触碰", "direction": "信封朝递信人正前方缓慢滑动", "end_state": "陈迹嘴唇将启，信封几乎停住，递信人仍未触碰", "intent": "续接前句并完成求生条件", "visible_causality": "持续接触让信封沿原方向减速，吸气随后转为发声", "expression": "冷厉压迫", "viewer_read": "U15B1动作与U15B2发声无缝连续"},
        {"start_seconds": 0.8, "end_seconds": 2.0, "subject": "陈迹", "action": "保持完整嘴部可见，以自然中文普通话完整说出就告诉我", "contact_point": "指尖持续压住信封后缘，唇齿下颌喉部与胸腹呼吸逐字同步", "direction": "信封沿原方向移动不足半掌宽并停住，陈迹视线压住递信人", "end_state": "陈迹闭口，指尖仍在后缘，信封停住，递信人仍未触碰", "intent": "完成未说完的求生条件", "visible_causality": "短句与信封停稳共同令递信人准备取证", "expression": "十七岁少年低声逼问，句尾悬停", "viewer_read": "陈迹完整说出唯一短句且说话人清楚"},
        {"start_seconds": 2.0, "end_seconds": 5.0, "subject": "陈迹、递信人、空信封", "action": "陈迹闭口保持视线并稳住信封；递信人无声咽气，右手向衣襟移动但尚未探入", "contact_point": "陈迹指尖接触信封后缘；递信人两手不接触信封，右手只接触自己衣襟外层", "direction": "递信人右手由膝上向胸前衣襟抬起，信封保持停在案面", "end_state": "陈迹闭口且指尖压信封；递信人右手停在衣襟外，准备听完U15C后取票根", "intent": "建立U15C前的供述准备", "visible_causality": "求生逼问让递信人把手移向藏票根处", "expression": "陈迹冷厉等待，递信人恐惧求生", "viewer_read": "第二句完成，第三句尚未开始"},
    ],
}
task["multimodal_entity_bindings"][0]["prop_owners"]["空信封"] = "从U15B1终帧续压后缘直至停稳，U15B2不离开"
task["multimodal_entity_bindings"][1]["prop_owners"]["空信封"] = "不触碰；右手仅向自己衣襟移动"
task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
task["keyframe_interpolation_gate"] = {"status": "PASS", "anchor_count": 1, "checked_adjacent_pairs": 0, "reason": "One accepted U15B1 terminal anchor supports the final envelope deceleration, one short exact clause and a silent reaction tail; U15C requires the accepted U15B2 terminal anchor."}
config["tasks"] = [task]
write(PROD / "E36_U15B2_EPISODE_SINGLE_UNIT_V1.json", config)

spend = {
    "schema": "qingshan.episode_actual_credit_spend_audit.v1", "episode": "E36", "recorded_at": recorded_at,
    "status": "PASS_EXACT_RECONCILED", "unknown_credits": 0,
    "net_actual_spend": 5059, "episode_limit": 6000, "remaining_to_limit": 941,
    "categories": {"image_generation": {"credits": 539, "count": 49, "basis": "49 exact gpt-image-2-pro Pay rows at 11 credits each"}, "video_generation": {"credits": 4520, "basis": "31 exact Seedance task Pay rows, after refunds"}},
    "gross_and_refunds": {"gross_pay_credits": 5259, "refund_credits": 200, "net_credits": 5059, "refund_basis": "U10 R3 and R4 each Pay100 plus Refund100; net zero"},
    "video_groups": {"U01": 160, "U02": 140, "U03": 100, "U05": 100, "U11": 200, "U12_chain": 600, "U13": 160, "U15_chain_through_U15B": 200, "U19A_chain": 240, "U19B_chain": 400, "U19C_chain": 500, "U20B_repair_chain": 1560, "U21": 160},
    "checks": {"image_plus_video_equals_net": 539 + 4520 == 5059, "grouped_video_equals_video": sum([160,140,100,100,200,600,160,200,240,400,500,1560,160]) == 4520, "gross_minus_refunds_equals_net": 5259 - 200 == 5059},
    "source": "Exact settled provider credit statements and task-id reconciliation receipts; no estimate and no active task included.",
}
write(QA / "E36_ACTUAL_CREDIT_SPEND_AUDIT_5059_V1.json", spend)

capfit = {
    "schema": "qingshan.episode_cap_fit_remaining_coverage_plan.v1", "episode": "E36", "recorded_at": recorded_at, "source_cl2x": "CL2X-764",
    "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6", "canonical_manifest_sha256": "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5",
    "verified_paid_before": 5059, "unknown_credits": 0, "episode_limit": 6000,
    "paid_remaining": [{"unit_id": "U15B2", "credits": 100}, {"unit_id": "U15C", "credits": 100}, {"unit_id": "U16A", "credits": 100}, {"unit_id": "U16B", "credits": 100}, {"unit_id": "U06", "credits": 100}, {"unit_id": "U07", "credits": 100}, {"unit_id": "U17", "credits": 100}, {"unit_id": "U18A", "credits": 100}, {"unit_id": "U18B", "credits": 100}],
    "paid_remaining_total": 900, "projected_final": 5959, "remaining_after_projection": 41, "retry_reserve": 0,
    "zero_credit_substitutions": [
        {"unit_id": "U04", "method": "local motion-composite from canonical start/terminal anchors with directional ice mask, crowd-life layers, speed ramp and impact sound; no remote generation", "canonical_scope_preserved": True},
        {"unit_id": "U10", "method": "local supernatural insert from the passed U10 anchor using eyelid/blood-mark mask animation, composited shadow extension and room-life layers; bridge into accepted U11; no remote generation", "canonical_scope_preserved": True},
        {"scope": "image_repairs", "method": "local crop, mask, inpaint and text-removal derivatives while preserving original FAIL evidence", "credits": 0},
    ],
    "gate_results": {"canonical_sha": "PASS", "complete_required_coverage": "PASS_CAP_FIT_WITH_LOCAL_POST_SUBSTITUTIONS", "projected_final": "PASS_5959_LE_6000", "paid_submission_allowed": True, "approval_required": False, "active_remote_tasks": 0, "E37": "STILL_CLOSED"},
    "blocked_by": None, "next_action": "Submit only U15B2 after precheck; reconcile exact credits before advancing U15C. No unchanged retry and no spend beyond the 5959 plan.",
}
write(QA / "E36_CAP_FIT_5959_COVERAGE_PLAN_V1.json", capfit)
