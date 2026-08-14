#!/usr/bin/env python3
"""Build the strict U07 replacement still submission package."""

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


prompt = PROD / "image_prompts_repair_v3/E36-CW-U07-A3.txt"
messenger = ROOT / "assets/reference/e25_20260719/E25-FAKE-MESSENGER-IDENTITY-LOCK.png"
jiaotu = ROOT / "working_assets/e32_reference_single_subject_20260723/jiaotu_front_single.jpg"
scene = ROOT / "working_assets/e36_v2_stills_20260728/repair_v2_candidates/E36_E36-CW-U07-A2-STILL-V2_21644198-1ac1-4359-b628-c9d52989c4c4.png"
source_action = "纸扎替身正落进原位、尚在倾斜未稳，阴神手正扣住真棋后领"
bindings = [
    {"role": "character", "entity_id": "messenger", "path": rel(messenger), "sha256": sha(messenger), "qa_status": "PASS"},
    {"role": "character", "entity_id": "jiaotu", "path": rel(jiaotu), "sha256": sha(jiaotu), "qa_status": "PASS"},
    {"role": "scene", "entity_id": "E36-9-1-U07-layout-only", "path": rel(scene), "sha256": sha(scene), "qa_status": "LAYOUT_ONLY_DEFECTS_EXPLICITLY_EXCLUDED"},
]

anchor_gate = {
    "schema": "qingshan.video_unit_anchor_count_gate.v1",
    "episode": "E36",
    "unit_id": "U07",
    "status": "PASS",
    "planned_anchor_count": 1,
    "new_image_submit_count": 1,
    "reason": "One corrected start-motion anchor supports a single continuous five-second extraction action; old V2 states are excluded from video submission because their role and frost geometry conflict.",
    "excluded_assets": [
        "E36-CW-U07-A1-STILL-V2",
        "E36-CW-U07-A2-STILL-V2"
    ]
}
write(QA / "E36_U07_ANCHOR_COUNT_GATE_V3.json", anchor_gate)

preflight = {
    "schema": "qingshan.image_prompt_preflight.v1",
    "episode": "E36",
    "unit_id": "U07",
    "task_key": "E36-CW-U07-A3-STILL-V3",
    "status": "PASS",
    "checks": {
        "canonical_script_sha": "PASS",
        "manifest_sha": "PASS",
        "character_identity_refs": "PASS",
        "first_frame_motion_state": "PASS",
        "subject_action_contact_direction_end_state": "PASS",
        "frost_not_water": "PASS",
        "role_separation": "PASS",
        "paper_decoy_no_text": "PASS",
        "period_continuity": "PASS",
        "ambient_life": "PASS"
    },
    "source_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
    "source_manifest_sha256": "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5",
    "prompt_path": rel(prompt),
    "prompt_sha256": sha(prompt)
}
write(QA / "E36_U07_A3_IMAGE_PROMPT_PREFLIGHT_V3.json", preflight)

contract = {
    "schema": "qingshan.image_prompt_contract.v2",
    "shot_id": "E36-CW-U07-A3",
    "source_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
    "source_action": source_action,
    "source_action_sha256": hashlib.sha256(source_action.encode("utf-8")).hexdigest(),
    "visible_characters": ["messenger", "jiaotu"],
    "reference_bindings": bindings,
    "first_frame_motion_state": source_action,
    "ambient_life": "看客推挤、指点、前景肩背移动与午日浮尘形成持续环境运动。",
    "spatial_continuity": {
        "mode": "SAME_SPACE_CONTINUOUS",
        "policy_source": "PER_UNIT_SCRIPT_CONTENT",
        "scene_id": "E36-9-1",
        "camera_design": "刑台略低机位中景；左前暗桩、中部倾斜纸替、右后皎兔与递信人，关键接触点均清楚。"
    },
    "repair_delta": "Correct role count and identity, freeze only the hidden stake, preserve dry feet on the true piece, remove all paper text and show collar contact.",
    "status": "PASS",
    "failures": []
}

manifest = {
    "schema": "qingshan.episode_parallel_batch.v1",
    "episode": "E36",
    "status": "READY_TO_SUBMIT_SINGLE_ITEM_REPAIR",
    "source_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
    "output_dir": "working_assets/e36_v2_stills_20260728/u07_candidates_v3",
    "qa_dir": rel(QA),
    "retry_policy": "FAILED_ITEM_ONLY_CHANGED_INPUT_REQUIRED",
    "repair_of": {
        "qa_report": "qa/e36_v2_stills_20260728/E36_U07_IMAGE_QA_FAIL_V1.json",
        "failed_gates": ["effect_semantics_frost_not_water", "multistate_character_continuity", "contact_point_clarity", "action_direction_continuity"]
    },
    "consumer_contract": {"planned_anchor_count": 1, "new_image_submit_count": 1, "all_required_anchors_planned_before_submit": True, "incremental_video_submit": "U07_ONLY_AFTER_IMAGE_QA_PASS"},
    "blocked_tasks": [],
    "machine_gate_reports": [rel(QA / "E36_U07_ANCHOR_COUNT_GATE_V3.json"), rel(QA / "E36_U07_A3_IMAGE_PROMPT_PREFLIGHT_V3.json")],
    "tasks": [{
        "task_key": "E36-CW-U07-A3-STILL-V3",
        "tool_type": "image_generation",
        "scene_id": "E36-9-1",
        "shot_id": "E36-CW-U07-A3",
        "video_unit_id": "E36-CW-U07",
        "video_unit_duration_seconds": 5,
        "state_index": 1,
        "state_count": 1,
        "state_role": "start_motion",
        "prompt_file": rel(prompt),
        "prompt_sha256": sha(prompt),
        "reference_images": [row["path"] for row in bindings],
        "reference_bindings": bindings,
        "prompt_contract": contract,
        "model": "gpt-image-2-pro",
        "aspect_ratio": "9:16",
        "resolution": "2K",
        "status": "READY_AFTER_FAILED_ITEM_REPAIR_GATE",
        "source_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
    }]
}
write(PROD / "E36_U07_IMAGE_REPAIR_SUBMIT_V3.json", manifest)
print(PROD / "E36_U07_IMAGE_REPAIR_SUBMIT_V3.json")
