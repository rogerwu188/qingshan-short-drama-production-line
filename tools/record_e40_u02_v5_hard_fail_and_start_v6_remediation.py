#!/usr/bin/env python3
"""Quarantine U02 V5, persist PF-034, and start the zero-cost V6 remediation lane."""
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
HARVEST = ROOT / "workflow/tasks/E40_U02_V5_FAST720_HARVEST_20260814.json"
VIDEO = ROOT / "working_assets/e40_production_20260814/u02_v5_fast720/E40-U02-V5-FAST720-LOW-HEM-EXACT-FIRST-FRAME-CAUSAL-BEATS-SILENT-V1_85c0018e-32bb-4f38-aa78-9db07d2cdde4.mp4"
QA_DIR = ROOT / "qa/e40_production_20260814/u02_v5_fast720_harvest_qa_v1"
FRAME_GATE = QA_DIR / "E40_U02_V5_EXACT_FIRST_FRAME_GATE_V1.json"
CADENCE = QA_DIR / "E40_U02_V5_FRAME_CADENCE_AUDIT_V1.json"
OCR = QA_DIR / "E40_U02_V5_SOURCE_OCR_AUDIT_V1.json"
VOLUME = QA_DIR / "E40_U02_V5_VOLUMEDETECT_V1.txt"
CONTACT = QA_DIR / "E40_U02_V5_CONTACT_SHEET_V1.png"
COMPARE = QA_DIR / "E40_U02_V5_AUTHORITY_VS_FRAME0_V1.png"
HUMAN_QA = QA_DIR / "E40_U02_V5_ORIGINAL_RES_HUMAN_QA_V1.json"
V6_DIR = ROOT / "qa/e40_preproduction_20260814/u02_v6_changed_transport_silent_source_remediation_v1"
V6_PLAN = V6_DIR / "E40_U02_V6_CHANGED_TRANSPORT_AND_SILENT_SOURCE_REMEDIATION_PLAN_V1.json"
SDK = Path("/Users/rogerwu/.codex/skills/giggle-seedance2-gen/scripts/generation_api.py")
CLIENT = ROOT / "tools/giggle_api_client.py"
NOW = "2026-08-14T06:45:00Z"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


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
    required = [SCHED, QUEUE, MEMORY, HARVEST, VIDEO, FRAME_GATE, CADENCE, OCR, VOLUME, CONTACT, COMPARE, SDK, CLIENT]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("missing required evidence: " + ", ".join(missing))

    frame = json.loads(FRAME_GATE.read_text(encoding="utf-8"))
    cadence = json.loads(CADENCE.read_text(encoding="utf-8"))
    ocr = json.loads(OCR.read_text(encoding="utf-8"))
    if frame.get("status") != "FAIL":
        raise SystemExit("exact-first-frame gate is not authoritative FAIL")
    if cadence.get("status") != "PASS" or ocr.get("status") != "PASS":
        raise SystemExit("cadence/OCR evidence does not match reviewed result")

    human = {
        "schema": "qingshan.e40.u02.v5.original_resolution_human_qa.v1",
        "episode": "E40",
        "unit_id": "U02",
        "variant": "V5",
        "reviewed_at": NOW,
        "source": {"path": rel(VIDEO), "sha256": digest(VIDEO), "bytes": VIDEO.stat().st_size},
        "technical_probe": {
            "video": {"codec": "h264 High", "pixel_format": "yuv420p", "width": 720, "height": 1280, "fps": 24, "frames": 97, "duration_seconds": 4.041667},
            "audio": {"present": True, "codec": "aac", "channels": 2, "sample_rate_hz": 44100, "duration_seconds": 4.086, "mean_volume_db": -27.6, "max_volume_db": -12.3},
            "audio_contract": "FAIL_HARD_SOURCE_AUDIO_STREAM_MUST_BE_ABSENT",
        },
        "original_resolution_review": {
            "sample_times_seconds": [0.0, 1.2, 2.4, 4.0],
            "one_right_hand_one_fan": "PASS",
            "face_head_torso_shoulder_upper_arm_absent": "PASS",
            "second_person_limb_prop_absent": "PASS",
            "curtain_hem_bottom_and_only_local_light_slit": "PASS",
            "stable_camera_no_cut": "PASS",
            "fan_primary_close_complete_by_1p2s": "PASS",
            "independent_causal_successor_motion": "PASS_WRIST_DESCENDS_AND_SHIFTS_INWARD",
            "obvious_loop": "ABSENT",
            "text_watermark_modern_props": "ABSENT",
            "visual_only_score": 86,
        },
        "machine_gates": {
            "exact_first_frame": {"path": rel(FRAME_GATE), "sha256": digest(FRAME_GATE), "status": "FAIL", "mae": 6.913009, "ssim": 0.929103, "phash_distance": 4, "psnr": 27.237},
            "decoded_frame0_to_frame1_continuity": "PASS",
            "cadence": {"path": rel(CADENCE), "sha256": digest(CADENCE), "status": "PASS"},
            "ocr": {"path": rel(OCR), "sha256": digest(OCR), "status": "PASS_ZERO_RECOGNITIONS_8_SAMPLES"},
            "audio_absent": {"path": rel(VOLUME), "sha256": digest(VOLUME), "status": "FAIL_HARD_AUDIBLE_AAC_STREAM"},
        },
        "visual_evidence": {
            "contact_sheet": {"path": rel(CONTACT), "sha256": digest(CONTACT)},
            "authority_vs_frame0": {"path": rel(COMPARE), "sha256": digest(COMPARE)},
        },
        "verdict": "FAIL_HARD_FRAME0_AND_AUDIO_QUARANTINED",
        "quarantined": True,
        "admitted_to_agentcut": False,
        "execution_pixels_allowed": False,
        "unchanged_retry_forbidden": True,
        "forbidden_repairs": ["SINGLE_FRAME_PREPEND_OR_REPLACEMENT", "POST_HARVEST_AUDIO_STRIP_AS_ADMISSION_FIX"],
        "failure_memory_required": "PF-034",
    }
    atomic_json(HUMAN_QA, human)

    memory = json.loads(MEMORY.read_text(encoding="utf-8"))
    if any(row.get("id") == "PF-034" for row in memory.get("rules", [])):
        raise SystemExit("PF-034 already exists; refusing duplicate state transition")
    memory["updated_at"] = NOW
    memory["rules"].append({
        "id": "PF-034",
        "failure": "U02 V5 passed visual, cadence and OCR review, but the Seedance Fast image-to-video result transformed decoded frame 0 away from the admitted authority (MAE 6.913009, SSIM 0.929103, pHash distance 4) and returned an audible AAC stereo stream (mean -27.6 dB, max -12.3 dB) although source audio was forbidden.",
        "first_pass_prompt_rule": "Do not treat an image-to-video start_frame field or silent prose as a pixel-identity or audio-absence guarantee. Before any later paid retry, materially change and locally validate the transport/source strategy so decoded frame 0 meets the exact authority thresholds and the provider source contains no audio stream. A one-frame prepend/replacement and post-harvest audio stripping are forbidden admission fixes; never reuse failed V5 pixels as execution pixels.",
        "pre_submit_check": "CHANGED_TRANSPORT_OR_VALIDATED_MULTI_FRAME_BRIDGE_FRAME0_PASS_AND_PROVIDER_SOURCE_AUDIO_STREAM_ABSENT_NO_SINGLE_FRAME_PATCH_NO_AUDIO_STRIP",
    })
    atomic_json(MEMORY, memory)

    v6 = {
        "schema": "qingshan.e40.u02.v6.changed_transport_silent_source_remediation_plan.v1",
        "episode": "E40",
        "unit_id": "U02",
        "created_at": NOW,
        "predecessor": {"variant": "V5", "task_id": "85c0018e-32bb-4f38-aa78-9db07d2cdde4", "human_qa": rel(HUMAN_QA), "human_qa_sha256": digest(HUMAN_QA)},
        "failure_memory": {"path": rel(MEMORY), "sha256": digest(MEMORY), "rule_id": "PF-034"},
        "installed_capability_audit": {
            "seedance_skill_client": {"path": str(SDK), "sha256": digest(SDK), "image_to_video_fields": ["prompt", "start_frame", "end_frame", "model", "duration", "aspect_ratio", "resolution", "generating_count"], "audio_disable_field": False},
            "repository_client": {"path": rel(CLIENT), "sha256": digest(CLIENT), "endpoint": "/api/v1/generation/image-to-video", "audio_disable_field": False},
            "finding": "NO_INSTALLED_IMAGE_TO_VIDEO_AUDIO_DISABLE_CONTROL_AND_NO_PIXEL_IDENTITY_OUTPUT_GUARANTEE",
        },
        "candidate_matrix": [
            {"candidate": "UNCHANGED_I2V_REPLAY", "verdict": "REJECT", "reason": "Closed fingerprint, no audio-disable field, exact-frame guarantee disproven."},
            {"candidate": "ONE_FRAME_PREPEND_PLUS_AUDIO_STRIP", "verdict": "REJECT", "reason": "Explicitly forbidden admission patch; can create a flash jump and masks provider source failure."},
            {"candidate": "DETERMINISTIC_MULTI_FRAME_BRIDGE", "verdict": "QA_REQUIRED", "reason": "May be considered only if every bridge frame is source-authorized, frame0 exact, first moving-frame continuity passes, and failed V5 pixels are excluded."},
            {"candidate": "CHANGED_PROVIDER_TRANSPORT_WITH_AUDIO_DISABLED", "verdict": "CAPABILITY_EVIDENCE_REQUIRED", "reason": "Current installed clients expose neither a mute/audio-off parameter nor an output pixel-identity contract."},
        ],
        "current_gate": "ACTIVE_ZERO_COST_REMEDIATION_QA",
        "paid_retry_allowed": False,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
        "single_blocker": "Prove one changed transport or source-authorized multi-frame bridge that passes exact decoded frame0 and produces a provider source with no audio stream before compiling any V6 paid package.",
        "next_action": "Run a local source-authority and transport-capability feasibility gate; do not submit or query a provider task.",
    }
    atomic_json(V6_PLAN, v6)

    scheduler = json.loads(SCHED.read_text(encoding="utf-8"))
    predecessor = None
    for row in scheduler["tasks"]:
        if row.get("task_id") == "E40-U02-V5-FAST720-EXACTLY-ONCE-TASK-LOCAL-REMOTE-WAIT":
            predecessor = row
            row.update({
                "state": "TERMINAL", "wait_scope": "NONE_TERMINAL", "provider_query_allowed": False, "download_allowed": False,
                "provider_calls": 2, "progress": "COMPLETED_DOWNLOADED_PAY64_CLASSIFIED_EXACT_FRAME0_AND_AUDIO_HARD_FAIL_QUARANTINED",
                "last_progress_at": NOW, "next_action": "Terminal and quarantined. Never replay or admit V5; V6 zero-cost remediation QA owns changed transport and silent-source proof.",
                "next_due_at": None, "executor_next_wakeup_at": None, "evidence_ref": rel(HUMAN_QA), "evidence_sha256": digest(HUMAN_QA),
                "output_ref": rel(VIDEO), "output_sha256": digest(VIDEO), "completed_at": NOW,
                "terminal_status": "FAIL_HARD_FRAME0_AND_AUDIO_QUARANTINED_NO_REPLAY",
            })
    if predecessor is None:
        raise SystemExit("missing V5 remote predecessor")
    successor_id = "E40-U02-V6-CHANGED-TRANSPORT-AND-SILENT-SOURCE-REMEDIATION-QA"
    if any(row.get("task_id") == successor_id for row in scheduler["tasks"]):
        raise SystemExit("V6 successor already exists; refusing duplicate transition")
    scheduler["tasks"].append({
        "task_id": successor_id, "lane_id": "U02_VIDEO_REMEDIATION_QA", "state": "QA", "wait_scope": "NONE_ACTIVE_QA", "zero_cost": True,
        "deliverable_type": "U02_V6_CHANGED_TRANSPORT_AND_SILENT_SOURCE_FEASIBILITY_GATE", "priority": 167,
        "scope": ["E40", "U02", "V6", "PF-034", "CHANGED_TRANSPORT", "EXACT_FRAME0", "SOURCE_AUDIO_ABSENT", "NO_PROVIDER", "NO_SUBMIT", "NO_TRANSACTION", "NO_CREDITS"],
        "exact_predecessor_task_id": predecessor["task_id"], "liveness_role": "PRODUCING", "observation_only": False,
        "maximum_new_submissions": 0, "authorization": False, "provider_post_allowed": False, "provider_query_allowed": False, "download_allowed": False,
        "provider_calls": 0, "transactions": 0, "credits": 0,
        "blocked_by": "CHANGED_TRANSPORT_EXACT_FRAME0_AND_PROVIDER_SOURCE_AUDIO_ABSENCE_NOT_YET_PROVEN",
        "progress": "V6_ACTIVE_CANDIDATE_MATRIX_COMPILED_INSTALLED_CLIENTS_LACK_AUDIO_DISABLE_AND_PIXEL_IDENTITY_GUARANTEE",
        "last_progress_at": NOW, "next_action": "Run local source-authority and transport-capability feasibility gate; reject any approach using failed V5 pixels, one-frame prepend, or post-harvest audio strip.",
        "lease_owner": "codex-e40-production:u02-v6-remediation", "lease_expires_at": "2026-08-14T08:45:00Z", "next_due_at": "2026-08-14T06:55:00Z",
        "execution_mode": "CONTINUOUS", "executor_handle": "automation:e40", "executor_task_id": successor_id,
        "executor_acknowledged_at": NOW, "executor_next_wakeup_at": "2026-08-14T06:55:00Z",
        "evidence_ref": rel(V6_PLAN), "evidence_sha256": digest(V6_PLAN),
    })
    scheduler["updated_at"] = NOW
    atomic_json(SCHED, scheduler)

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue.update({
        "updated_at": NOW,
        "mode": "E40_CONTINUOUS_EPISODE_PRODUCTION_U29_ASSEMBLED_U02_V5_QUARANTINED_V6_REMEDIATION_QA_ACTIVE",
        "occupied_scope_count": 2,
        "real_active_handle_count": 3,
        "status": "E40_U02_V5_PAY64_TERMINAL_HARD_FAIL_QUARANTINED_V6_ZERO_COST_REMEDIATION_QA_ACTIVE",
        "updated_note_latest": "U02 V5 task completed and was harvested once. Visual motion/cadence/OCR passed, but decoded frame0 failed the exact authority gate and the provider source carried audible AAC audio; the clip is quarantined and cannot enter AgentCut. PF-034 and a zero-cost V6 changed-transport/silent-source remediation lane are active; no retry was submitted.",
        "blocked_by": "U02_V5_FRAME0_AND_SOURCE_AUDIO_HARD_FAIL; V6_CHANGED_TRANSPORT_EXACT_FRAME0_AND_SOURCE_AUDIO_ABSENCE_PROOF_PENDING; E40_FULL_EPISODE_ASSEMBLY_QA_AND_RELEASE_PENDING",
        "next_action": "At the V6 local QA checkpoint, prove a source-authorized changed transport or multi-frame bridge with exact decoded frame0 and no provider audio stream; keep paid retry disabled until both gates pass.",
    })
    credits = queue["e40_credits"]
    credits.update({
        "gross_pay": 1511, "refund": 128, "net": 1383, "remaining": 8617, "video_pay": 1120,
        "active_remote_video_pay": 0, "active_remote_video_task_id": None,
        "pending_remote_video_task_count": 0, "pending_remote_video_task_ids": [],
        "status": "AUTHORITATIVE_TOTALS_1511_128_1383_U02_V5_PAY64_TERMINAL_PLUS_U18_V5_TWO_TASK_CLASSIFICATION_PENDING",
        "totals_fresh_through": "U02_V5_FAST720_TERMINAL_PAY64_HARVESTED_AND_QUARANTINED",
    })
    queue["latest_e40_u02_v5_fast720_harvest_qa"] = {
        "task_id": "85c0018e-32bb-4f38-aa78-9db07d2cdde4", "model": "seedance-2.0-fast", "resolution": "720p",
        "harvest": rel(HARVEST), "harvest_sha256": digest(HARVEST), "output": rel(VIDEO), "output_sha256": digest(VIDEO),
        "human_qa": rel(HUMAN_QA), "human_qa_sha256": digest(HUMAN_QA), "frame0_gate_sha256": digest(FRAME_GATE),
        "cadence_gate_sha256": digest(CADENCE), "ocr_gate_sha256": digest(OCR), "volume_report_sha256": digest(VOLUME),
        "pay": 64, "refund": 0, "net": 64, "admitted_to_agentcut": False,
        "status": "FAIL_HARD_FRAME0_AND_AUDIO_QUARANTINED_NO_REPLAY",
    }
    queue["latest_e40_u02_v6_changed_transport_remediation"] = {
        "plan": rel(V6_PLAN), "plan_sha256": digest(V6_PLAN), "failure_memory": rel(MEMORY), "failure_memory_sha256": digest(MEMORY),
        "rule_id": "PF-034", "provider_calls": 0, "transactions": 0, "credits": 0,
        "paid_retry_allowed": False, "status": "ACTIVE_ZERO_COST_REMEDIATION_QA",
    }
    queue["task_lane_scheduler"] = {"path": rel(SCHED), "heartbeat_integration": scheduler["heartbeat_integration"], "sha256": digest(SCHED)}
    atomic_json(QUEUE, queue)

    print(json.dumps({
        "status": "PASS_V5_QUARANTINED_V6_QA_STARTED", "human_qa_sha256": digest(HUMAN_QA),
        "failure_memory_sha256": digest(MEMORY), "v6_plan_sha256": digest(V6_PLAN),
        "scheduler_sha256": digest(SCHED), "work_queue_sha256": digest(QUEUE),
        "gross_pay": 1511, "refund": 128, "net": 1383, "remaining": 8617,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
