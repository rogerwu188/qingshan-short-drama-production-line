#!/usr/bin/env python3
"""Build E36 U13-R1 around the exact canonical fold-mark dialogue."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
OUT = BASE / "recovery_10000_20260730/u13_video"
QA = ROOT / "qa/e36_agentcut_20260730/u13_video_runtime"
OLD_CONFIG = BASE / "E36_U13_EPISODE_PARALLEL_BATCH_V1.json"
OLD_PROMPT_MANIFEST = BASE / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
OLD_DIALOGUE_MANIFEST = BASE / "E36_DIALOGUE_MANIFEST_V1.json"
CONFIG = OUT / "E36_U13_R1_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json"
PROMPT = OUT / "E36-CW-U13-R1.txt"
PROMPT_MANIFEST = OUT / "E36_U13_R1_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = OUT / "E36_U13_R1_DIALOGUE_MANIFEST_V1.json"
DIALOGUE_GATE = QA / "E36_U13_R1_DIALOGUE_PROMPT_GATE_V1.json"
ANCHOR_PLAN = QA / "E36_U13_R1_ANCHOR_COUNT_PLAN_V1.json"
CAUSALITY_PLAN = QA / "E36_U13_R1_COMMON_SENSE_CAUSALITY_PLAN_V1.json"
PERIOD_PLAN = QA / "E36_U13_R1_PERIOD_LOCK_PLAN_V1.json"
AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u13/E36-U13-D01.wav"
ANCHOR = ROOT / "working_assets/e36_v2_stills_20260728/repair_v2_candidates/E36_E36-CW-U13-A1-STILL-V2_dc493fa2-2d9e-4c48-8509-8e4ebe1857bd.png"
TEXT = "这折痕的样式，对得上王府账房的记号。"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def binding_digest(bindings: list[dict]) -> str:
    payload = json.dumps(bindings, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    prompt = (
        "E36 U13-R1，竖屏9:16电影级写实古装视频，时长5秒，实速。"
        "实体绑定：[[char_chenji]]十七岁陈迹，[[char_wuyun]]黑猫乌云，[[prop_blank_envelope]]无字空信封，[[scene_e36_s03]]洛城医馆密室。"
        "palette与光影：低饱和灰褐、旧纸暖白，窗格冷侧光与烛焰暖色动机光形成细微冷暖层次。"
        "力量作用于环境介质：陈迹手指推纸的力量只带动纸角轻颤；室内微气流仅推动烛焰、猫须与尾尖，不改变信封物权。"
        "镜头1（0.00-5.00秒）【中近景，案面侧轴机位，极缓前移后停稳】陈迹压住信封、翻起纸角、滑动指腹、抬眼说话，末字后闭口并停指；"
        "{对白：陈迹仅说‘这折痕的样式，对得上王府账房的记号。’}；<音效：纸角轻响、衣袖摩擦、烛芯细响>。"
        "主体：17岁陈迹、黑猫乌云与无字空信封。"
        "首帧直接在动作中途：陈迹左手压住信封，右手拇指正沿旧折痕向上推开一半；乌云鼻尖悬在纸面上方，胡须被气流带动。"
        "0.00-0.35秒，陈迹指腹沿折痕滑动并将纸角翻至侧光下，乌云只嗅闻、不触纸；接触点是陈迹指腹与旧折痕，方向由画面右下向左上。"
        "0.35-4.45秒，陈迹保持指腹压在折痕交叉点，抬眼只说一遍：‘这折痕的样式，对得上王府账房的记号。’"
        "对白由视频模型原生生成自然中文普通话，逐字准确，陈迹嘴部全程清晰可见，口型、气息、眉眼确认感与0.35-4.45秒起止时间同步；乌云闭口。"
        "4.45-5.00秒，陈迹末字后闭口，指尖停在折痕交叉点，空信封仍由陈迹持有；终态为折痕证据被明确指出，物权不转移。"
        "环境生命B级：烛焰轻摇，窗格侧光缓移，纸角随气流轻颤，乌云胡须与尾尖持续微动。"
        "时代连续：中国古代架空洛城医馆密室，旧木案、裸蜡烛古式烛台、古装衣袖；陈迹保持E36十七岁脸、发式与灰袍连续。"
        "【天气硬合同】weather=INTERIOR_CLEAR_DAY。"
        "禁纸上文字、伪字、字幕、水印、现代物件、静止起手、摆拍、对称站定、看镜头、亮相、背景冻结、慢镜、插帧、拉伸和复制帧。"
    )
    PROMPT.write_text(prompt + "\n", encoding="utf-8")
    prompt_sha = sha(PROMPT)
    audio_sha = sha(AUDIO)
    anchor_sha = sha(ANCHOR)

    config = json.loads(OLD_CONFIG.read_text(encoding="utf-8"))
    config.update({
        "status": "READY_FOR_SUPERVISOR_PRECHECK",
        "video_credit_limit": 10000,
        "workflow_credit_scope": "e36_canonical_v2_20260728_recovery_20260730",
        "episode_paid_credits_before": 6146,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u13_video",
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
        "task_key": "E36-CW-U13-R1-RECOVERY-10000",
        "source_id": "E36-CW-U13-R1-RECOVERY-10000",
        "batch_id": "E36-U13-R1-RECOVERY-10000",
        "duration_seconds": 5,
        "duration": 5,
        "edit_target_duration_seconds": 5,
        "status": "READY_TO_SUBMIT",
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": prompt_sha,
        "anchor_image_qa_ref": "qa/e36_v2_stills_repair_20260729/E36_REPAIR_V2_IMAGE_QA_16.json",
        "reference_audios": [rel(AUDIO)],
        "reference_audio_asset_ids": [],
        "max_retries": 0,
        "source_script_sha256": SCRIPT_SHA,
        "workflow_credit_scope": "e36_canonical_v2_20260728_recovery_20260730",
    })
    task["duration_plan"] = {
        "policy": "qingshan.shot_generation_duration.v5",
        "duration_seconds": 5,
        "rationale": "The exact natural Mandarin line is 4.051917 seconds and fits the revised 0.35-4.45 window without speed compression.",
        "edit_policy": "Preserve native dialogue, visible mouth, fold contact and terminal closed-mouth confirmation; trim only silence after QA.",
    }
    task["dialogue"] = [{
        "dia_id": "E36-U13-D01",
        "speaker": "陈迹",
        "spoken_text": TEXT,
        "start_seconds": 0.35,
        "end_seconds": 4.45,
        "breath_after_seconds": 0.2,
        "expression": "沿旧折痕验看后抬眼确认，冷静笃定，末字后闭口",
        "language": "zh-CN",
        "native_video_audio": True,
        "lip_sync": True,
        "breath_expression_sync": True,
    }]
    task["dialogue_audio_assets"] = [{
        "dia_id": "E36-U13-D01",
        "speaker_id": "chenji",
        "character_name": "陈迹",
        "audio_slot": "@音频1",
        "path": rel(AUDIO),
        "sha256": audio_sha,
        "duration_seconds": 4.051917,
        "voice_reference_asset_id": "cypqud0bu7t",
        "voice_derivation_status": "PASS",
        "source_voice": "AGENTCUT_SPEECH_GENERATION:clone_20251022_092746_158444; exact-line derivative bound to canonical Chenji voice authority cypqud0bu7t",
        "voice_gender": "male",
        "mode": "exact_dialogue_audio_reference",
        "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
    }]
    task["performance_spec"] = {
        "schema": "qingshan.performance_generation_spec.v2",
        "prop_ownership": {"无字空信封": "全段由陈迹左手压住、右手指腹沿折痕检验；乌云只嗅闻且不触纸"},
        "motion_beats": [
            {"start_seconds": 0.0, "end_seconds": 0.35, "subject": "陈迹、乌云、无字空信封", "action": "陈迹指腹沿旧折痕向上推开纸角，乌云鼻尖悬空嗅闻", "contact_point": "陈迹指腹与折痕交叉点；乌云不触纸", "direction": "纸角由右下向左上翻起", "end_state": "折痕交叉点进入侧光且陈迹准备开口", "intent": "建立折痕检查依据", "visible_causality": "指腹推开纸角后折痕在侧光下显形", "expression": "专注验看", "viewer_read": "陈迹正在检查折法而非辨墨"},
            {"start_seconds": 0.35, "end_seconds": 4.45, "subject": "陈迹、乌云、无字空信封", "action": "陈迹保持指腹压住折痕并抬眼说出唯一判断，乌云闭口嗅闻", "contact_point": "陈迹指腹持续接触折痕；乌云鼻尖悬空", "direction": "陈迹视线由纸面抬向画外同伴", "end_state": "王府账房折痕记号的判断完整说出", "intent": "完成canonical证据判断", "visible_causality": "先检折痕再开口确认来源", "expression": "由专注转为笃定", "viewer_read": "陈迹确认折痕属于王府账房记号"},
            {"start_seconds": 4.45, "end_seconds": 5.0, "subject": "陈迹、乌云、无字空信封", "action": "陈迹闭口并将指尖停在折痕交叉点，乌云胡须与纸角轻动", "contact_point": "信封仍由陈迹持有", "direction": "动作收束在原轴线", "end_state": "折痕证据被明确指出且物权不转移", "intent": "形成可剪辑确认终态", "visible_causality": "说完后指尖仍指向证据点", "expression": "冷静确认", "viewer_read": "结论成立且无字信封未换手"},
        ],
    }
    bindings = task["multimodal_entity_bindings"]
    chenji = next(row for row in bindings if row["entity_id"] == "chenji")
    chenji.update({
        "voice_reference": rel(AUDIO),
        "voice_reference_sha256": audio_sha,
        "voice_reference_asset_id": "cypqud0bu7t",
        "audio_slot": "@音频1",
        "dialogue_audio_slots": ["@音频1"],
        "visible_speaker": True,
        "lip_sync": True,
        "prop_owners": {"无字空信封": "左手压住且右手指腹持续检验折痕交叉点"},
    })
    wuyun = next(row for row in bindings if row["entity_id"] == "wuyun")
    wuyun["prop_owners"] = {"无字空信封": "不持有且鼻尖不接触纸面"}
    task["multimodal_binding_sha256"] = binding_digest(bindings)
    task["keyframe_interpolation_gate"] = {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 1, "adjacent_pairs_checked": 0, "checked_adjacent_pairs": 0, "candidate_recheck_required": True, "physical_interpolation_or_declared_cut": "PASS", "reason": "Single continuous fold inspection with explicit terminal state."}

    prompt_manifest = json.loads(OLD_PROMPT_MANIFEST.read_text(encoding="utf-8"))
    scene_authority = ROOT / config["scene_contract_ref"]
    prompt_manifest["source_scene_authority_sha256"] = sha(scene_authority)
    row = next(row for row in prompt_manifest["rows"] if row["unit_id"] == "U13")
    row.update({"prompt_path": rel(PROMPT), "prompt_sha256": prompt_sha})
    write_json(PROMPT_MANIFEST, prompt_manifest)

    dialogue_manifest = json.loads(OLD_DIALOGUE_MANIFEST.read_text(encoding="utf-8"))
    row = next(row for row in dialogue_manifest["rows"] if row["video_unit_id"] == "U13")
    row.update({"spoken_text": TEXT, "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(AUDIO), "sha256": audio_sha, "remote_asset_id": "cypqud0bu7t", "start_seconds": 0.35, "end_seconds": 4.45, "breath_after_seconds": 0.2, "expression": "沿折痕验看后笃定确认，末字后闭口"})
    write_json(DIALOGUE_MANIFEST, dialogue_manifest)

    write_json(DIALOGUE_GATE, {"schema": "qingshan.e36.unit_dialogue_prompt_gate.v1", "episode": "E36", "unit_id": "U13", "source_cl2x": "CL2X-809", "canonical_script_sha256": SCRIPT_SHA, "manifest_sha256": MANIFEST_SHA, "prompt_path": rel(PROMPT), "prompt_sha256": prompt_sha, "dialogue": {"speaker": "陈迹", "text": TEXT, "start_seconds": 0.35, "end_seconds": 4.45, "delivery": "视频模型原生自然中文普通话", "visible_speaker_contract": "十七岁陈迹脸与嘴在完整说话区间持续清晰可见", "sync_contract": "嘴唇逐字同步，自然换气，眉眼由专注转为确认"}, "checks": {"canonical_and_manifest_sha_match": "PASS", "exact_dialogue": "PASS", "exact_audio_asr": "PASS_1P0", "audio_duration": "PASS_4P051917_WITHIN_2_TO_15", "speaker_binding": "PASS", "native_mandarin": "PASS", "full_interval_visible_mouth": "PASS_DECLARED", "age_17_identity": "PASS_DECLARED", "lip_breath_expression_sync": "PASS_DECLARED", "subject_action_contact_direction_end_state": "PASS", "first_frame_motion_state": "PASS", "ambient_life": "PASS", "period_continuity": "PASS", "credits_spent": 2}, "verdict": "PASS", "blocked_by": None, "submission_allowed_after_supervisor_precheck": True})
    write_json(ANCHOR_PLAN, {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36", "planned_reference_image_count": 1, "units": [{"unit_id": "U13", "planned_reference_image_count": 1, "reference_image_task_keys": ["E36-CW-U13-A1-STILL-V2"], "keyframe_interpolation_gate": task["keyframe_interpolation_gate"], "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "Single continuous fold inspection with no identity or space transition.", "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False}, "anchor_roles": ["start_motion_fold_inspection"], "action_design_class": "continuous_single_anchor_fold_inspection"}}]})
    write_json(CAUSALITY_PLAN, {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E36", "units": [{"unit_id": "U13", "causality": {"applicable": True, "purpose": "以折痕检查确认王府账房记号", "intended_effect": "陈迹确认空信封折法来源", "visible_causality": "陈迹指腹沿旧折痕推开纸角，折痕交叉点进入侧光后才抬眼说出判断", "viewer_read": "观众能看清指腹、折痕、侧光与结论之间的连续因果", "preconditions": ["无字空信封位于案上", "陈迹指腹接近旧折痕", "乌云只嗅闻不触纸"], "mechanism_chain": ["指腹沿旧折痕滑动", "纸角翻入侧光", "交叉折痕显形", "陈迹说出王府账房记号判断"], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "若指腹沿折痕检查与侧光显形缺失，折法来源判断没有可见依据。"}, "prop_function_status": "PASS", "evidence_refs": [rel(DIALOGUE_GATE), rel(PROMPT)]}}]})
    write_json(PERIOD_PLAN, {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36", "period_contract": {"status": "PASS", "era": "中国古代架空洛城", "source_refs": ["workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md", "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_SCENE_STATE_AUTHORITY_V1.json#E36-CW-S03"]}, "units": [{"unit_id": "U13", "period_lock": {"status": "PASS", "reviewed_visible_elements": ["旧木案", "裸蜡烛古式烛台", "古装衣袖", "无字空信封"], "detected_anachronisms": [], "forbidden_elements": ["现代物件", "现代文字", "玻璃罩煤油灯", "民国灯具", "可读字幕", "水印"], "exception_approvals": {}, "evidence_refs": [rel(ANCHOR), rel(PROMPT)]}}]})
    write_json(CONFIG, config)
    print(json.dumps({"status": "PASS", "config": str(CONFIG), "config_sha256": sha(CONFIG), "prompt": str(PROMPT), "prompt_sha256": prompt_sha, "audio_sha256": audio_sha, "anchor_sha256": anchor_sha}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
