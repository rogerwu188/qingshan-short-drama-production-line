#!/usr/bin/env python3
"""Admit U02 V10 and activate the real audio/subtitle/AgentCut assembly successor."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHED = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
MEMORY = ROOT / "workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json"
BASE = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808"
QA = ROOT / "qa/e40_production_20260814"
V10_VIDEO = BASE / "u02_v10_rigid_prop_curtain_tail_v1/E40_U02_V10_RIGID_PROP_CURTAIN_TAIL_CANDIDATE_V1.mp4"
V10_SPEC = BASE / "u02_v10_rigid_prop_curtain_tail_v1/E40_U02_V10_RIGID_PROP_CURTAIN_TAIL_SPEC_V1.json"
V10_DIR = QA / "u02_v10_rigid_prop_curtain_tail_v1"
V10_EXACT = V10_DIR / "E40_U02_V10_EXACT_FIRST_FRAME_GATE_V1.json"
V10_CADENCE = V10_DIR / "E40_U02_V10_FRAME_CADENCE_AUDIT_V1.json"
V10_OCR = V10_DIR / "E40_U02_V10_SOURCE_OCR_AUDIT_V1.json"
V10_CONTACT = V10_DIR / "E40_U02_V10_CONTACT_SHEET_V1.png"
HUMAN_QA = V10_DIR / "E40_U02_V10_ORIGINAL_RES_HUMAN_QA_V1.json"
CHAIN = V10_DIR / "E40_U02_V6_TO_V10_DETERMINISTIC_REMEDIATION_CHAIN_V1.json"
V11_DIR = ROOT / "qa/e40_preproduction_20260814/u02_v11_audio_subtitle_agentcut_assembly_v1"
V11_PLAN = V11_DIR / "E40_U02_V11_AUDIO_SUBTITLE_AGENTCUT_ASSEMBLY_PLAN_V1.json"
NOW = "2026-08-14T07:12:00Z"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main() -> None:
    required = [SCHED, QUEUE, MEMORY, V10_VIDEO, V10_SPEC, V10_EXACT, V10_CADENCE, V10_OCR, V10_CONTACT]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("missing evidence: " + ", ".join(missing))
    exact = json.loads(V10_EXACT.read_text(encoding="utf-8"))
    cadence = json.loads(V10_CADENCE.read_text(encoding="utf-8"))
    ocr = json.loads(V10_OCR.read_text(encoding="utf-8"))
    if exact.get("status") != "PASS" or cadence.get("status") != "PASS" or ocr.get("status") != "PASS":
        raise SystemExit("V10 machine gates are not all PASS")

    human = {
        "schema": "qingshan.e40.u02.v10.original_resolution_human_qa.v1",
        "episode": "E40", "unit_id": "U02", "variant": "V10", "reviewed_at": NOW,
        "source": {"path": rel(V10_VIDEO), "sha256": sha(V10_VIDEO)},
        "technical": {"codec": "h264 High 4:4:4 Predictive", "width": 720, "height": 1280, "pixel_format": "yuv444p", "fps": 24, "frames": 96, "duration_seconds": 4.0, "audio_stream_count": 0},
        "machine_gates": {
            "exact_first_frame": {"path": rel(V10_EXACT), "sha256": sha(V10_EXACT), "status": "PASS", "mae": 0.388351, "ssim": 0.999811, "phash_distance": 0},
            "frame0_to_frame1": {"status": "PASS", "mae": 0.120978, "ssim": 0.999850, "mean_optical_flow": 0.027784},
            "cadence": {"path": rel(V10_CADENCE), "sha256": sha(V10_CADENCE), "status": "PASS", "motion_mean": 0.452949, "freeze_ratio": 0.0, "periodic_chain_count": 0},
            "ocr": {"path": rel(V10_OCR), "sha256": sha(V10_OCR), "status": "PASS", "samples": 7, "recognitions": 0},
            "audio_absent": "PASS_ZERO_AUDIO_STREAMS",
        },
        "original_resolution_samples": {"frames": [12, 31, 60, 95], "directory": rel(V10_DIR / "frames")},
        "human_checks": {
            "single_right_hand_single_fan_owner_continuity": "PASS",
            "head_face_neck_shoulder_torso_second_person_absent": "PASS",
            "fan_ribs_remain_readably_straight_and_single": "PASS",
            "hand_fingers_and_grip_remain_natural": "PASS",
            "right_lattice_lines_remain_straight": "PASS",
            "curtain_tail_is_one_continuous_fabric_gust": "PASS",
            "curtain_hem_stays_on_bottom_border": "PASS",
            "right_bottom_light_slit_does_not_grow": "PASS",
            "camera_cut_loop_text_watermark_modern_prop": "ABSENT",
            "failed_v5_pixels_used": False,
        },
        "score": 84,
        "minimum_score": 80,
        "verdict": "PASS_ADMITTED_U02_SILENT_VISUAL_SOURCE_FOR_AGENTCUT",
        "admission_scope": "EXACT_V10_SHA_ONLY_U02_SILENT_VISUAL_AGENTCUT_INPUT",
        "release_or_full_episode_assembly_authorized": False,
    }
    atomic_json(HUMAN_QA, human)

    chain_rows = []
    definitions = [
        ("V6", BASE / "u02_v6_deterministic_source_authority_v1/E40_U02_V6_DETERMINISTIC_SOURCE_AUTHORITY_CANDIDATE_V1.mp4", QA / "u02_v6_deterministic_source_authority_v1/E40_U02_V6_FRAME_CADENCE_AUDIT_V1.json", "FAIL_OPEN_TO_END_FREEZE_PF035"),
        ("V7", BASE / "u02_v7_amplified_deterministic_authority_v1/E40_U02_V7_AMPLIFIED_DETERMINISTIC_AUTHORITY_CANDIDATE_V1.mp4", QA / "u02_v7_amplified_deterministic_authority_v1/E40_U02_V7_FRAME_CADENCE_AUDIT_V1.json", "FAIL_OPENING_0P500_FREEZE_PF036"),
        ("V8", BASE / "u02_v8_opening_overlap_deterministic_v1/E40_U02_V8_OPENING_OVERLAP_DETERMINISTIC_CANDIDATE_V1.mp4", QA / "u02_v8_opening_overlap_deterministic_v1/E40_U02_V8_FRAME_CADENCE_AUDIT_V1.json", "FAIL_TAIL_1P458_FREEZE_PF037"),
        ("V9", BASE / "u02_v9_continuous_foreground_deterministic_v1/E40_U02_V9_CONTINUOUS_FOREGROUND_DETERMINISTIC_CANDIDATE_V1.mp4", QA / "u02_v9_continuous_foreground_deterministic_v1/E40_U02_V9_FRAME_CADENCE_AUDIT_V1.json", "FAIL_HUMAN_RIGID_FAN_BOWING_PF038"),
        ("V10", V10_VIDEO, V10_CADENCE, "PASS_EXACT_FRAME_AUDIO0_CADENCE_OCR_HUMAN84"),
    ]
    for variant, video, cadence_path, outcome in definitions:
        chain_rows.append({"variant": variant, "video": rel(video), "video_sha256": sha(video), "cadence": rel(cadence_path), "cadence_sha256": sha(cadence_path), "outcome": outcome, "provider_calls": 0, "transactions": 0, "credits": 0})
    atomic_json(CHAIN, {
        "schema": "qingshan.e40.u02.v6_to_v10.deterministic_remediation_chain.v1", "episode": "E40", "unit_id": "U02", "recorded_at": NOW,
        "canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
        "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
        "source_authority_sha256": "2f8841136030bd4f691ddb9faa77badfe52e7caf207f6f6975030703894fe725",
        "rows": chain_rows, "failure_memory": {"path": rel(MEMORY), "sha256": sha(MEMORY), "rules": ["PF-035", "PF-036", "PF-037", "PF-038"]},
        "terminal_admission": {"variant": "V10", "video_sha256": sha(V10_VIDEO), "human_qa": rel(HUMAN_QA), "human_qa_sha256": sha(HUMAN_QA)},
        "status": "PASS_V10_ADMITTED_AFTER_FOUR_MATERIAL_LOCAL_REPRESENTATION_CHANGES_ZERO_PROVIDER_ZERO_CREDITS",
    })

    atomic_json(V11_PLAN, {
        "schema": "qingshan.e40.u02.v11.audio_subtitle_agentcut_assembly_plan.v1", "episode": "E40", "unit_id": "U02", "created_at": NOW,
        "visual": {"path": rel(V10_VIDEO), "sha256": sha(V10_VIDEO), "human_qa": rel(HUMAN_QA), "human_qa_sha256": sha(HUMAN_QA), "duration_seconds": 4.0},
        "dialogue": [
            {"line_id": "E40-DIA-001", "speaker": "云妃", "exact_text": "阿栓，在本宫手上。", "face_visibility": "HIDDEN_BEHIND_CURTAIN", "accepted_audio_path": None, "status": "PENDING_DEDICATED_EXACT_AUDIO"},
            {"line_id": "E40-DIA-002", "speaker": "云妃", "exact_text": "拿他，换景朝一个接头人。", "face_visibility": "HIDDEN_BEHIND_CURTAIN", "accepted_audio_path": None, "status": "PENDING_DEDICATED_EXACT_AUDIO"},
        ],
        "subtitle_style": "WHITE_HEITI_BLACK_OUTLINE_NO_BACKGROUND_BOX_BOTTOM_CENTER",
        "assembly_rule": "Acquire or bind two exact dedicated Yunfei audio lines, verify transcript/speaker/duration, then assemble picture+audio+subtitles in AgentCut and run unit audiovisual QA.",
        "provider_calls": 0, "transactions": 0, "credits": 0,
        "current_blocker": "TWO_DEDICATED_EXACT_YUNFEI_AUDIO_ASSETS_NOT_YET_ADMITTED",
        "status": "ACTIVE_AUDIO_BINDING_AND_AGENTCUT_ASSEMBLY_QA",
    })

    scheduler = json.loads(SCHED.read_text(encoding="utf-8"))
    predecessor = None
    for row in scheduler["tasks"]:
        if row.get("task_id") == "E40-U02-V6-CHANGED-TRANSPORT-AND-SILENT-SOURCE-REMEDIATION-QA":
            predecessor = row
            row.update({
                "state": "TERMINAL", "wait_scope": "NONE_TERMINAL", "blocked_by": None,
                "progress": "V6_TO_V10_LOCAL_CHAIN_EXACT_FRAME_AUDIO0_CADENCE_OCR_HUMAN84_V10_ADMITTED",
                "last_progress_at": NOW, "next_action": "Terminal visual remediation; V11 owns exact Yunfei audio, subtitles and isolated AgentCut assembly.",
                "next_due_at": None, "executor_next_wakeup_at": None, "evidence_ref": rel(CHAIN), "evidence_sha256": sha(CHAIN),
                "output_ref": rel(V10_VIDEO), "output_sha256": sha(V10_VIDEO), "completed_at": NOW,
                "terminal_status": "PASS_V10_ADMITTED_U02_SILENT_VISUAL_SOURCE_FOR_AGENTCUT",
            })
    if predecessor is None:
        raise SystemExit("missing V6 scheduler task")
    successor_id = "E40-U02-V11-EXACT-YUNFEI-AUDIO-SUBTITLE-AGENTCUT-ASSEMBLY-QA"
    if any(row.get("task_id") == successor_id for row in scheduler["tasks"]):
        raise SystemExit("V11 successor already exists")
    scheduler["tasks"].append({
        "task_id": successor_id, "lane_id": "U02_AGENTCUT_AUDIO_SUBTITLE_ASSEMBLY", "state": "QA", "wait_scope": "NONE_ACTIVE_QA", "zero_cost": True,
        "deliverable_type": "U02_EXACT_AUDIO_SUBTITLE_AGENTCUT_UNIT_ASSEMBLY", "priority": 168,
        "scope": ["E40", "U02", "V11", "EXACT_V10_VISUAL", "EXACT_YUNFEI_AUDIO", "SUBTITLES", "AGENTCUT", "NO_VIDEO_PROVIDER", "NO_RELEASE"],
        "exact_predecessor_task_id": predecessor["task_id"], "liveness_role": "PRODUCING", "observation_only": False,
        "maximum_new_submissions": 0, "authorization": False, "provider_post_allowed": False, "provider_query_allowed": False, "download_allowed": False,
        "provider_calls": 0, "transactions": 0, "credits": 0,
        "blocked_by": "TWO_DEDICATED_EXACT_YUNFEI_AUDIO_ASSETS_NOT_YET_ADMITTED",
        "progress": "V11_ACTIVE_EXACT_V10_VISUAL_BOUND_DIALOGUE_LINES_AND_SUBTITLE_STYLE_BOUND",
        "last_progress_at": NOW, "next_action": "Resolve the two dedicated exact Yunfei audio assets, then assemble U02 picture/audio/subtitles and run audiovisual QA; do not submit another video.",
        "lease_owner": "codex-e40-production:u02-v11-agentcut-audio", "lease_expires_at": "2026-08-14T09:12:00Z", "next_due_at": "2026-08-14T07:22:00Z",
        "execution_mode": "CONTINUOUS", "executor_handle": "automation:e40", "executor_task_id": successor_id,
        "executor_acknowledged_at": NOW, "executor_next_wakeup_at": "2026-08-14T07:22:00Z",
        "evidence_ref": rel(V11_PLAN), "evidence_sha256": sha(V11_PLAN),
    })
    scheduler["updated_at"] = NOW
    atomic_json(SCHED, scheduler)

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue.update({
        "updated_at": NOW,
        "mode": "E40_CONTINUOUS_EPISODE_PRODUCTION_U02_V10_VISUAL_ADMITTED_V11_AUDIO_SUBTITLE_AGENTCUT_ACTIVE",
        "occupied_scope_count": 2, "real_active_handle_count": 3,
        "status": "E40_U02_V10_EXACT_FRAME_AUDIO0_CADENCE_OCR_HUMAN84_ADMITTED_V11_ASSEMBLY_ACTIVE",
        "updated_note_latest": "U02 V6-V10 zero-cost deterministic source-authority chain completed. V6/V7/V8 failed cadence and V9 failed rigid-fan human review with memories PF-035..038; V10 passes exact frame0, zero audio streams, cadence, OCR and original-resolution human84 and is admitted for U02 AgentCut only. V11 exact Yunfei audio/subtitle/AgentCut assembly is active; no provider video retry occurred.",
        "blocked_by": "U02_V11_TWO_DEDICATED_EXACT_YUNFEI_AUDIO_ASSETS_AND_AGENTCUT_UNIT_ASSEMBLY_PENDING; E40_FULL_EPISODE_ASSEMBLY_QA_AND_RELEASE_PENDING",
        "next_action": "Resolve or generate the two dedicated exact Yunfei U02 audio lines under their own durable transaction gates, then assemble exact V10 picture with audio and subtitles in AgentCut and run unit audiovisual QA.",
    })
    queue["latest_e40_u02_v10_deterministic_visual_admission"] = {
        "video": rel(V10_VIDEO), "video_sha256": sha(V10_VIDEO), "spec": rel(V10_SPEC), "spec_sha256": sha(V10_SPEC),
        "human_qa": rel(HUMAN_QA), "human_qa_sha256": sha(HUMAN_QA), "chain": rel(CHAIN), "chain_sha256": sha(CHAIN),
        "exact_frame_gate_sha256": sha(V10_EXACT), "cadence_gate_sha256": sha(V10_CADENCE), "ocr_gate_sha256": sha(V10_OCR),
        "provider_calls": 0, "transactions": 0, "credits": 0, "status": "PASS_ADMITTED_U02_SILENT_VISUAL_SOURCE_FOR_AGENTCUT",
    }
    queue["latest_e40_u02_v11_agentcut_audio_assembly"] = {"plan": rel(V11_PLAN), "plan_sha256": sha(V11_PLAN), "status": "ACTIVE_AUDIO_BINDING_AND_AGENTCUT_ASSEMBLY_QA"}
    queue["task_lane_scheduler"] = {"path": rel(SCHED), "heartbeat_integration": scheduler["heartbeat_integration"], "sha256": sha(SCHED)}
    atomic_json(QUEUE, queue)
    print(json.dumps({"status": "PASS_V10_ADMITTED_V11_STARTED", "video_sha256": sha(V10_VIDEO), "human_qa_sha256": sha(HUMAN_QA), "chain_sha256": sha(CHAIN), "v11_plan_sha256": sha(V11_PLAN), "scheduler_sha256": sha(SCHED), "work_queue_sha256": sha(QUEUE)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
