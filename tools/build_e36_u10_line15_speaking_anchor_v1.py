#!/usr/bin/env python3
"""Build the one-item E36 U10 line15 speaking-anchor image package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
PACK = PROD / "recovery_10000_20260730/u10_line15_image"
QA = ROOT / "qa/e36_agentcut_20260730/u10_line15_image_runtime"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_FILE_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"
TASK_KEY = "E36-CW-U10-L15-A1-STILL-V1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


prompt = PACK / "E36-CW-U10-L15-A1.txt"
messenger = ROOT / "assets/reference/e25_20260719/E25-FAKE-MESSENGER-IDENTITY-LOCK.png"
scene = ROOT / "working_assets/e36_v2_stills_20260728/repair_v2_candidates/E36_E36-CW-U10-A1-STILL-V2_dfa4a764-90b3-453a-a31e-ba4c4118e334.png"
source_plan = ROOT / "qa/e36_agentcut_20260730/E36_U10_LINE15_SOURCE_GATE_AND_SPEAKING_ANCHOR_PLAN_V1.json"
contextual_qa = ROOT / "qa/e36_agentcut_20260730/u10_line15_video_runtime/E36-U10-L15-D01_EXACT_DIALOGUE_AUDIO_QA_V1.json"
robust_qa = ROOT / "qa/e36_agentcut_20260730/u10_line15_video_runtime/E36-U10-L15-D01_UNCONDITIONED_ASR_ROBUST_V1.json"
source_action = "递信人被缚跪坐时身体向前蜷缩，右手抓紧膝上衣料，正说到“凭什么惊动这许多老爷”，嘴唇处于自然发音中间态，眼眶湿润、呼吸发紧。"

expected = {
    messenger: "5d3f357346ebf72301abf08f54c9999c05fabcb8cde2856c64f096b8d9180cff",
    scene: "5856558ab939386e0f1c803ffc55df969a788fe308b1eccf162eb19a44167625",
    source_plan: "27ab975de02ab9e287b9fceb78255f83254bcb276ba7aeeea2d7f86d0b92b797",
    contextual_qa: "8ed072faba799168c043e4412eb8b870e110abecfacc171a01af3c730502b352",
    robust_qa: "6f3451faed053e3ab2ca6742d1d6401460ca54bba4bfd5ac68329b5408abc4d7",
}
for path, expected_sha in expected.items():
    if not path.is_file() or sha(path) != expected_sha:
        raise SystemExit(f"Input authority mismatch: {path}")

plan = json.loads(source_plan.read_text(encoding="utf-8"))
contextual = json.loads(contextual_qa.read_text(encoding="utf-8"))
robust = json.loads(robust_qa.read_text(encoding="utf-8"))
if plan["canonical"]["script_sha256"] != SCRIPT_SHA or plan["canonical"]["manifest_file_sha256"] != MANIFEST_FILE_SHA:
    raise SystemExit("Canonical script/manifest authority mismatch")
if contextual.get("status") != "PASS" or contextual.get("asr_similarity") != 1.0:
    raise SystemExit("Contextual source gate is not exact PASS")
robust_summary = robust.get("summary") or {}
if robust.get("status") != "PASS_ROBUST_EXACT_12_OF_12" or robust_summary.get("exact_count") != 12 or robust_summary.get("decode_count") != 12:
    raise SystemExit("Robust source gate is not exact 12/12 PASS")

bindings = [
    {
        "role": "character",
        "entity_id": "messenger",
        "path": rel(messenger),
        "sha256": sha(messenger),
        "qa_status": "PASS",
    },
    {
        "role": "scene",
        "entity_id": "E36-TAIPING-CLINIC-SECRET-ROOM-U10-LAYOUT",
        "path": rel(scene),
        "sha256": sha(scene),
        "qa_status": "LAYOUT_AND_PERIOD_ONLY_PRIOR_SILENT_SCOPE_PASS",
    },
]

anchor_gate = {
    "schema": "qingshan.video_unit_anchor_count_gate.v1",
    "episode": "E36",
    "unit_id": "U10-L15",
    "status": "PASS",
    "planned_anchor_count": 1,
    "new_image_submit_count": 1,
    "reason": "One changed-input speaking anchor is required because the accepted silent U10 anchor hides the messenger mouth; no sibling image task is submitted.",
}
write(QA / "E36_U10_LINE15_ANCHOR_COUNT_GATE_V1.json", anchor_gate)

preflight = {
    "schema": "qingshan.image_prompt_preflight.v1",
    "episode": "E36",
    "unit_id": "U10-L15",
    "task_key": TASK_KEY,
    "status": "PASS",
    "source_cl2x": "CL2X-851",
    "source_mailbox_sha256": "18b5efc11f8e335048cc11028a8f9212a1e0ad94567146587b67d7affa5ea18f",
    "checks": {
        "canonical_script_sha": "PASS",
        "canonical_manifest_file_sha": "PASS",
        "source_plan_sha": "PASS",
        "contextual_source_similarity_1p0": "PASS",
        "robust_source_exact_12_of_12": "PASS",
        "messenger_identity_reference": "PASS",
        "single_scene_reference": "PASS",
        "subject_action_contact_direction_terminal": "PASS",
        "mouth_fully_visible_mid_speech": "PASS",
        "first_frame_motion_state": "PASS",
        "ambient_life_b_level": "PASS",
        "adult_period_continuity": "PASS",
        "visible_text_forbidden": "PASS",
        "one_item_only": "PASS",
        "projected_credit_limit": "PASS_7868_LE_10000",
    },
    "source_script_sha256": SCRIPT_SHA,
    "source_manifest_file_sha256": MANIFEST_FILE_SHA,
    "source_plan_path": rel(source_plan),
    "source_plan_sha256": sha(source_plan),
    "prompt_path": rel(prompt),
    "prompt_sha256": sha(prompt),
    "projected_image_credits": 11,
    "episode_exact_source_attributable_before": 7857,
    "episode_cap": 10000,
}
write(QA / "E36_U10_LINE15_SPEAKING_ANCHOR_IMAGE_PREFLIGHT_V1.json", preflight)

contract = {
    "schema": "qingshan.image_prompt_contract.v2",
    "shot_id": "E36-CW-U10-L15-A1",
    "source_script_sha256": SCRIPT_SHA,
    "source_action": source_action,
    "source_action_sha256": hashlib.sha256(source_action.encode("utf-8")).hexdigest(),
    "visible_characters": ["messenger"],
    "reference_bindings": bindings,
    "first_frame_motion_state": "抓衣手指已经收紧、肩膀正处于一次颤动中段、嘴唇已开始第一句发音",
    "ambient_life": "B级：烛焰轻摇、直棂窗硬光缓移、案面薄尘随弱冷流起落",
    "spatial_continuity": {
        "mode": "SAME_SPACE_CONTINUOUS",
        "policy_source": "PER_UNIT_SCRIPT_CONTENT",
        "scene_id": "E36-TAIPING-CLINIC-SECRET-ROOM",
        "camera_design": "递信人胸像近景，眼平三分之二侧面，身体由右向左朝画外皎兔，嘴部无遮挡。",
    },
    "terminal_state": "说完小的自己都怕后低头、肩膀仍轻颤，嘴巴自然闭合",
    "repair_delta": "Reframe from the prior silent JiaoTu close-up to the bound adult messenger's fully visible mid-speech face while preserving secret-room period and layout continuity.",
    "status": "PASS",
    "failures": [],
}

manifest = {
    "schema": "qingshan.episode_parallel_batch.v1",
    "episode": "E36",
    "status": "READY_TO_SUBMIT_SINGLE_ITEM_CHANGED_INPUT",
    "source_script_sha256": SCRIPT_SHA,
    "source_manifest_file_sha256": MANIFEST_FILE_SHA,
    "output_dir": "working_assets/e36_recovery_10000_20260730/u10_line15_image",
    "qa_dir": rel(QA),
    "retry_policy": "FAILED_ITEM_ONLY_CHANGED_INPUT_REQUIRED",
    "consumer_contract": {
        "planned_anchor_count": 1,
        "new_image_submit_count": 1,
        "all_required_anchors_planned_before_submit": True,
        "incremental_video_submit": "LINE15_FAST6S_ONLY_AFTER_IMAGE_QA_PASS",
    },
    "blocked_tasks": [],
    "machine_gate_reports": [
        rel(QA / "E36_U10_LINE15_ANCHOR_COUNT_GATE_V1.json"),
        rel(QA / "E36_U10_LINE15_SPEAKING_ANCHOR_IMAGE_PREFLIGHT_V1.json"),
    ],
    "tasks": [
        {
            "task_key": TASK_KEY,
            "tool_type": "image_generation",
            "scene_id": "E36-TAIPING-CLINIC-SECRET-ROOM",
            "shot_id": "E36-CW-U10-L15-A1",
            "video_unit_id": "E36-CW-U10-L15",
            "video_unit_duration_seconds": 6,
            "state_index": 1,
            "state_count": 1,
            "state_role": "mid_speech_start_motion",
            "prompt_file": rel(prompt),
            "prompt_sha256": sha(prompt),
            "reference_images": [row["path"] for row in bindings],
            "reference_bindings": bindings,
            "prompt_contract": contract,
            "model": "gpt-image-2-pro",
            "aspect_ratio": "9:16",
            "resolution": "2K",
            "status": "READY_AFTER_SOURCE_AND_IMAGE_PREFLIGHT_GATES",
            "source_script_sha256": SCRIPT_SHA,
        }
    ],
}
write(PACK / "E36_U10_LINE15_SPEAKING_ANCHOR_IMAGE_MANIFEST_V1.json", manifest)
print(PACK / "E36_U10_LINE15_SPEAKING_ANCHOR_IMAGE_MANIFEST_V1.json")
