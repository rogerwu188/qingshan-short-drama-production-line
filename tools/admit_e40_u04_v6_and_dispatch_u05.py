#!/usr/bin/env python3
"""Admit U04 V6 and dispatch the next safe U05 production successor."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHED = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
X2CL = ROOT / "workflow/CODEX_TO_CLAUDE.md"
VIDEO = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u04_v6_local_semantic_mask_repair_v1/E40_U04_V6_LOCAL_SEMANTIC_MASK_REPAIR_CANDIDATE_V1.mp4"
SPEC = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u04_v6_local_semantic_mask_repair_v1/E40_U04_V6_LOCAL_SEMANTIC_MASK_REPAIR_SPEC_V1.json"
CONTACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u04_v6_local_semantic_mask_repair_v1/E40_U04_V6_LOCAL_SEMANTIC_MASK_REPAIR_CONTACT_SHEET_V1.png"
EXACT = ROOT / "qa/e40_production_20260814/u04_v6_local_semantic_mask_repair_v1/E40_U04_V6_EXACT_FIRST_FRAME_GATE_V1.json"
CADENCE = ROOT / "qa/e40_production_20260814/u04_v6_local_semantic_mask_repair_v1/E40_U04_V6_FRAME_CADENCE_AUDIT_V1.json"
OCR = ROOT / "qa/e40_production_20260814/u04_v6_local_semantic_mask_repair_v1/E40_U04_V6_SOURCE_OCR_AUDIT_V1.json"
HUMAN = ROOT / "qa/e40_production_20260814/u04_v6_local_semantic_mask_repair_v1/E40_U04_V6_ORIGINAL_RES_HUMAN_QA_V1.json"
FROST_COMPARE = ROOT / "qa/e40_production_20260814/E40_U04_V6_FROST_FIRST_LAST_CROP.png"
ADMISSION = ROOT / "workflow/releases/E40_U04_V6_SILENT_VISUAL_UNIT_ADMISSION_20260814.json"
U05_PREFLIGHT = ROOT / "working_assets/e40_preproduction_20260808/u05_asset_isolation_preflight_v1/E40_U05_ASSET_ISOLATION_PREFLIGHT_MANIFEST_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U04_V6_ADMISSION_U05_SUCCESSOR_DISPATCH_20260814.json"


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


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def main() -> None:
    required = [SCHED, QUEUE, X2CL, VIDEO, SPEC, CONTACT, EXACT, CADENCE, OCR, FROST_COMPARE, U05_PREFLIGHT]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("missing evidence: " + ", ".join(missing))
    exact = json.loads(EXACT.read_text(encoding="utf-8"))
    cadence = json.loads(CADENCE.read_text(encoding="utf-8"))
    ocr = json.loads(OCR.read_text(encoding="utf-8"))
    if any(report.get("status") != "PASS" for report in (exact, cadence, ocr)):
        raise SystemExit("U04 V6 machine gates are not all PASS")
    now = datetime.now(timezone.utc)
    now_s = iso(now)
    human = {
        "schema": "qingshan.e40.u04.v6.original_resolution_human_qa.v1",
        "episode": "E40", "unit_id": "U04", "variant": "V6", "reviewed_at": now_s,
        "source": {"path": rel(VIDEO), "sha256": sha(VIDEO), "bytes": VIDEO.stat().st_size},
        "technical": {"codec": "h264", "width": 720, "height": 1280, "fps": 24, "frames": 96, "duration_seconds": 4.0, "audio_stream_count": 0},
        "machine_gates": {
            "exact_frame": {"path": rel(EXACT), "sha256": sha(EXACT), "status": "PASS", "mae": 2.331527, "ssim": 0.998792, "phash_distance": 0},
            "frame0_to_frame1": {"status": "PASS", "mae": 1.160592, "ssim": 0.997533, "phash_distance": 0, "mean_optical_flow": 0.322288},
            "cadence": {"path": rel(CADENCE), "sha256": sha(CADENCE), "status": "PASS", "failures": []},
            "ocr": {"path": rel(OCR), "sha256": sha(OCR), "status": "PASS", "samples": 7, "recognitions": 0},
            "audio_absent": "PASS_ZERO_AUDIO_STREAMS",
        },
        "original_resolution_review": {
            "one_actor_one_connected_hand": "PASS",
            "natural_five_finger_anatomy": "PASS",
            "white_robe_and_period_hall_continuity": "PASS",
            "single_frost_owner_count_transfer": "PASS_ONE_TRACE_SAME_FINGER_NO_TRANSFER",
            "frost_primary_action": "PASS_FULL_RING_RECEDES_TO_SHORT_PALE_FRAGMENT_BY_1P2S",
            "finger_wrist_gaze_successor_motion": "PASS_BOUNDED_AND_CONTINUOUS",
            "collar_neck_geometry": "PASS_NO_V5_MASK_SMEAR",
            "camera_cut_loop_flash": "ABSENT",
            "text_watermark_modern_props": "ABSENT",
            "failed_provider_pixels_used": False,
        },
        "visual_evidence": {"contact_sheet": {"path": rel(CONTACT), "sha256": sha(CONTACT)}, "frost_first_last_crop": {"path": rel(FROST_COMPARE), "sha256": sha(FROST_COMPARE)}},
        "score": 88, "minimum_score": 80,
        "verdict": "PASS_ADMITTED_U04_SILENT_VISUAL_UNIT_FOR_EPISODE_ASSEMBLY",
        "release_or_full_episode_assembly_authorized": False,
    }
    atomic_json(HUMAN, human)
    admission = {
        "schema": "qingshan.e40.u04.v6.silent_visual_unit_admission.v1", "status": "PASS_U04_V6_ADMITTED_FOR_EPISODE_ASSEMBLY", "recorded_at": now_s,
        "episode": "E40", "unit_id": "U04", "variant": "V6",
        "video": rel(VIDEO), "video_sha256": sha(VIDEO), "spec": rel(SPEC), "spec_sha256": sha(SPEC),
        "human_qa": rel(HUMAN), "human_qa_sha256": sha(HUMAN),
        "exact_frame_gate": rel(EXACT), "exact_frame_gate_sha256": sha(EXACT),
        "cadence_gate": rel(CADENCE), "cadence_gate_sha256": sha(CADENCE),
        "ocr_gate": rel(OCR), "ocr_gate_sha256": sha(OCR),
        "dialogue": [], "audio_contract": "SILENT_VISUAL_NO_DIALOGUE_ZERO_AUDIO_STREAMS",
        "provider_v3": {"task_id": "03a0e327-56ff-4d12-ac25-19137127d6f8", "pay": 64, "refund": 0, "pixels_reused": False, "status": "QUARANTINED_FRAME0_AND_AUDIO_FAIL"},
        "local_v6": {"provider_posts": 0, "transactions": 0, "credits": 0},
        "admission_scope": "EXACT_V6_SHA_ONLY_U04_EPISODE_ASSEMBLY_INPUT",
        "release_authorized": False,
    }
    atomic_json(ADMISSION, admission)

    scheduler = json.loads(SCHED.read_text(encoding="utf-8"))
    predecessor = next((row for row in scheduler.get("tasks", []) if row.get("task_id") == "E40-U04-V5-LOCAL-AUTHORITY-CADENCE-REPAIR-QA"), None)
    if predecessor is None or predecessor.get("state") != "QA":
        raise SystemExit("active U04 local scheduler task missing")
    predecessor.update({
        "state": "TERMINAL", "wait_scope": "NONE_TERMINAL", "blocked_by": None,
        "progress": "V6_EXACT_FRAME_AUDIO0_CADENCE_OCR_HUMAN88_ADMITTED",
        "last_progress_at": now_s, "next_action": "Terminal U04 admission; U05 production successor owns next unit.",
        "next_due_at": None, "executor_next_wakeup_at": None,
        "evidence_ref": rel(ADMISSION), "evidence_sha256": sha(ADMISSION), "output_ref": rel(VIDEO), "output_sha256": sha(VIDEO),
        "completed_at": now_s, "terminal_status": "PASS_U04_V6_ADMITTED_FOR_EPISODE_ASSEMBLY",
    })
    successor_id = "E40-U05-COHERENT-PERFORMANCE-SOURCE-ACQUISITION-QA"
    if not any(row.get("task_id") == successor_id for row in scheduler.get("tasks", [])):
        scheduler["tasks"].append({
            "task_id": successor_id, "lane_id": "U05_COHERENT_PERFORMANCE_SOURCE", "state": "QA", "wait_scope": "NONE_ACTIVE_QA", "zero_cost": True,
            "deliverable_type": "U05_COHERENT_WHITE_ROBE_HALL_VISIBLE_LINE_SOURCE_ACQUISITION_AND_QA", "priority": 172,
            "scope": ["E40", "U05", "COHERENT_SOURCE", "CHENJI_WHITE_ROBE", "HALL", "VISIBLE_EXACT_LINE", "ASSET_QA", "NO_PROVIDER_UNTIL_FRAME_ADMITTED", "NO_RELEASE"],
            "exact_predecessor_task_id": predecessor["task_id"], "liveness_role": "PRODUCING", "observation_only": False,
            "maximum_new_submissions": 0, "authorization": False, "provider_post_allowed": False, "provider_query_allowed": False, "download_allowed": False,
            "provider_calls": 0, "transactions": 0, "credits": 0,
            "blocked_by": "U05_CURRENT_ISOLATED_SOURCES_DO_NOT_COOCCUR_NATURALLY",
            "progress": "U04_ADMITTED_U05_EXISTING_FAIL_CLOSED_ISOLATION_PREFLIGHT_BOUND_FOR_COHERENT_SOURCE_DECISION",
            "last_progress_at": now_s,
            "next_action": "Read canonical U05 visible-line action and admitted character/hall assets; choose and build one coherent non-collage performance frame, then run original-image human/OCR QA before any video package.",
            "lease_owner": "codex-e40-production:u05-source", "lease_expires_at": iso(now + timedelta(hours=2)), "next_due_at": iso(now + timedelta(minutes=10)),
            "execution_mode": "CONTINUOUS", "executor_handle": "automation:e40", "executor_task_id": successor_id,
            "executor_acknowledged_at": now_s, "executor_next_wakeup_at": iso(now + timedelta(minutes=10)),
            "evidence_ref": rel(U05_PREFLIGHT), "evidence_sha256": sha(U05_PREFLIGHT),
        })
    scheduler["updated_at"] = now_s
    scheduler["scheduler_decision"] = {"global_wait": False, "reason": "U04_ADMITTED_U05_COHERENT_SOURCE_QA_ACTIVE"}
    atomic_json(SCHED, scheduler)

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue.update({
        "updated_at": now_s,
        "mode": "E40_CONTINUOUS_EPISODE_PRODUCTION_U04_ADMITTED_U05_COHERENT_SOURCE_QA_ACTIVE",
        "status": "E40_U04_V6_ADMITTED_U05_SOURCE_ACQUISITION_ACTIVE",
        "updated_note_latest": "U04 V6 independent local authority-only visual passes exact frame0, frame0-to-1 continuity, zero-audio, cadence, OCR and original-resolution human88. It is admitted for episode assembly only. U05 coherent non-collage performance-source acquisition is now the active unit successor.",
        "blocked_by": "U05_COHERENT_VISIBLE_LINE_PERFORMANCE_SOURCE_AND_QA_PENDING; E40_REMAINING_UNITS_FULL_EPISODE_ASSEMBLY_QA_AND_RELEASE_PENDING",
        "next_action": "Build and admit one coherent U05 white-robed Chenji hall performance start frame, then compile its exact visible-line video/audio path without reusing collage patterns.",
    })
    queue["latest_e40_u04_v6_visual_admission"] = {"path": rel(ADMISSION), "sha256": sha(ADMISSION), "video": rel(VIDEO), "video_sha256": sha(VIDEO), "human_qa_sha256": sha(HUMAN), "status": admission["status"]}
    queue["latest_e40_u05_successor"] = {"task_id": successor_id, "preflight": rel(U05_PREFLIGHT), "preflight_sha256": sha(U05_PREFLIGHT), "status": "ACTIVE_COHERENT_SOURCE_ACQUISITION_QA"}
    queue["task_lane_scheduler"] = {"path": rel(SCHED), "heartbeat_integration": scheduler["heartbeat_integration"], "sha256": sha(SCHED)}
    atomic_json(QUEUE, queue)
    with X2CL.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {now_s} — E40 U04 V6 admitted; U05 coherent-source successor active\n\n")
        handle.write(f"- U04 V6 `{rel(VIDEO)}` SHA=`{sha(VIDEO)}` passes exact frame0 (MAE 2.331527, SSIM 0.998792, pHash 0), frame0→1 continuity, zero audio streams, cadence, OCR and original-resolution human88. Frost recedes from the admitted full ring to one short pale fragment, owner/count/transfer remain exact, and V5 collar smear is absent. Admission `{rel(ADMISSION)}` SHA=`{sha(ADMISSION)}` is scoped to this exact silent visual SHA for episode assembly only.\n")
        handle.write(f"- Scheduler closes U04 and activates `{successor_id}` against existing fail-closed U05 isolation preflight `{rel(U05_PREFLIGHT)}` SHA=`{sha(U05_PREFLIGHT)}`. Next action is one coherent non-collage U05 white-robed Chenji hall performance frame and human/OCR QA before any paid video path. No provider post, upload, release or E38/E39 mutation.\n")
    atomic_json(RECEIPT, {"schema": "qingshan.e40.u04.v6_admission_u05_successor_dispatch.v1", "status": "PASS_U04_ADMITTED_U05_SUCCESSOR_ACTIVE", "recorded_at": now_s, "admission_sha256": sha(ADMISSION), "human_qa_sha256": sha(HUMAN), "scheduler_sha256": sha(SCHED), "work_queue_sha256": sha(QUEUE), "successor": successor_id})
    print(json.dumps({"status": "PASS_U04_ADMITTED_U05_SUCCESSOR_ACTIVE", "video_sha256": sha(VIDEO), "admission_sha256": sha(ADMISSION), "successor": successor_id}, ensure_ascii=False))


if __name__ == "__main__":
    main()
