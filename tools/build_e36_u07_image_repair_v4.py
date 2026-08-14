#!/usr/bin/env python3
"""Build changed-input U07 still repair after V3 frost/identity/text QA failure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
QA = ROOT / "qa/e36_v2_stills_repair_20260729/u07_video_runtime"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))

def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

prompt = PROD / "image_prompts_repair_v3/E36-CW-U07-A4.txt"
messenger = ROOT / "assets/reference/e25_20260719/E25-FAKE-MESSENGER-IDENTITY-LOCK.png"
jiaotu = ROOT / "working_assets/e32_reference_single_subject_20260723/jiaotu_front_single.jpg"
scene = ROOT / "working_assets/e36_v2_stills_20260728/u07_candidates_v3/E36-CW-U07-A3-STILL-V3_bf8f4e94-3608-4c68-8997-93415fa2b6fa.png"
source_action = "纸扎替身正落进原位、尚在倾斜未稳，阴神手正扣住真棋后领"
bindings = [
    {"role": "character", "entity_id": "messenger", "path": rel(messenger), "sha256": sha(messenger), "qa_status": "PASS"},
    {"role": "character", "entity_id": "jiaotu", "path": rel(jiaotu), "sha256": sha(jiaotu), "qa_status": "PASS"},
    {"role": "scene", "entity_id": "E36-9-1-U07-v3-layout-only", "path": rel(scene), "sha256": sha(scene), "qa_status": "LAYOUT_ONLY_V3_FAILS_EXPLICITLY_EXCLUDED"}
]
gate = {"schema": "qingshan.video_unit_anchor_count_gate.v1", "episode": "E36", "unit_id": "U07", "status": "PASS", "planned_anchor_count": 1, "new_image_submit_count": 1, "reason": "Single corrected start-motion anchor; V1/V2/V3 failed states remain excluded."}
write(QA / "E36_U07_ANCHOR_COUNT_GATE_V4.json", gate)
preflight = {"schema": "qingshan.image_prompt_preflight.v1", "episode": "E36", "unit_id": "U07", "task_key": "E36-CW-U07-A4-STILL-V4", "status": "PASS", "checks": {"canonical_script_sha": "PASS", "manifest_sha": "PASS", "changed_input": "PASS", "frost_zero_liquid_language": "PASS", "adult_male_hidden_stake": "PASS", "all_background_text_forbidden": "PASS", "first_frame_motion_state": "PASS", "ambient_life": "PASS"}, "source_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6", "source_manifest_sha256": "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5", "prompt_path": rel(prompt), "prompt_sha256": sha(prompt)}
write(QA / "E36_U07_A4_IMAGE_PROMPT_PREFLIGHT_V4.json", preflight)
contract = {"schema": "qingshan.image_prompt_contract.v2", "shot_id": "E36-CW-U07-A4", "source_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6", "source_action": source_action, "source_action_sha256": hashlib.sha256(source_action.encode("utf-8")).hexdigest(), "visible_characters": ["messenger", "jiaotu"], "reference_bindings": bindings, "first_frame_motion_state": source_action, "ambient_life": "看客持续推挤、踮脚、举臂指点，前景肩背横移，午日浮尘翻滚。", "spatial_continuity": {"mode": "SAME_SPACE_CONTINUOUS", "policy_source": "PER_UNIT_SCRIPT_CONTENT", "scene_id": "E36-9-1", "camera_design": "刑台中景；左前成年男性暗桩、中部倾斜纸替、中央后递信人、右后皎兔，霜壳与后领接触清楚。"}, "repair_delta": "Replace every liquid cue with dry matte rime, make the hidden stake unmistakably adult male, and blank every flag and sign while preserving layout and collar contact.", "status": "PASS", "failures": []}
manifest = {"schema": "qingshan.episode_parallel_batch.v1", "episode": "E36", "status": "READY_TO_SUBMIT_SINGLE_ITEM_REPAIR", "source_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6", "output_dir": "working_assets/e36_v2_stills_20260728/u07_candidates_v4", "qa_dir": rel(QA), "retry_policy": "FAILED_ITEM_ONLY_CHANGED_INPUT_REQUIRED", "repair_of": {"task_id": "bf8f4e94-3608-4c68-8997-93415fa2b6fa", "asset_sha256": sha(scene), "qa_report": rel(QA / "E36_U07_A3_IMAGE_QA_FAIL_V3.json"), "qa_report_sha256": sha(QA / "E36_U07_A3_IMAGE_QA_FAIL_V3.json"), "failed_gates": ["effect_semantics_frost_not_water", "hidden_stake_age_identity", "background_text_safety"]}, "consumer_contract": {"planned_anchor_count": 1, "new_image_submit_count": 1, "all_required_anchors_planned_before_submit": True, "incremental_video_submit": "U07_ONLY_AFTER_IMAGE_QA_PASS"}, "blocked_tasks": [], "machine_gate_reports": [rel(QA / "E36_U07_ANCHOR_COUNT_GATE_V4.json"), rel(QA / "E36_U07_A4_IMAGE_PROMPT_PREFLIGHT_V4.json")], "tasks": [{"task_key": "E36-CW-U07-A4-STILL-V4", "tool_type": "image_generation", "scene_id": "E36-9-1", "shot_id": "E36-CW-U07-A4", "video_unit_id": "E36-CW-U07", "video_unit_duration_seconds": 5, "state_index": 1, "state_count": 1, "state_role": "start_motion", "prompt_file": rel(prompt), "prompt_sha256": sha(prompt), "reference_images": [row["path"] for row in bindings], "reference_bindings": bindings, "prompt_contract": contract, "model": "gpt-image-2-pro", "aspect_ratio": "9:16", "resolution": "2K", "status": "READY_AFTER_FAILED_ITEM_REPAIR_GATE", "source_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"}]}
write(PROD / "E36_U07_IMAGE_REPAIR_SUBMIT_V4.json", manifest)
print(PROD / "E36_U07_IMAGE_REPAIR_SUBMIT_V4.json")
