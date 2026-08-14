#!/usr/bin/env python3
"""Classify U04 V3, persist failure memory, and dispatch local V5 QA."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path("/Users/rogerwu/.local/share/backlotos/share/pipeline-tools")
TASK_ID = "03a0e327-56ff-4d12-ac25-19137127d6f8"
TASK_KEY = "E40-U04-V3-FAST720-COHERENT-EXACT-FIRST-FRAME-FROST-RECEDE-SILENT-V1"
SCHED = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
X2CL = ROOT / "workflow/CODEX_TO_CLAUDE.md"
MEMORY = ROOT / "workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json"
TX = ROOT / "workflow/tasks/giggle_video_submit_transactions/E40/E40-U04-V3-FAST720-COHERENT-EXACT-FIRST-FRAME-FROST-RECEDE-SILENT-V1__105db2165831f79d.json"
HARVEST = ROOT / "workflow/tasks/E40_U04_V3_FAST720_HARVEST_20260814.json"
VIDEO = ROOT / f"working_assets/e40_production_20260814/u04_v3_fast720/{TASK_KEY}_{TASK_ID}.mp4"
QA3 = ROOT / "qa/e40_production_20260814/u04_v3_fast720_harvest_qa_v1"
EXACT3 = QA3 / "E40_U04_V3_EXACT_FIRST_FRAME_GATE_V1.json"
CADENCE3 = QA3 / "E40_U04_V3_FRAME_CADENCE_AUDIT_V1.json"
OCR3 = QA3 / "E40_U04_V3_SOURCE_OCR_AUDIT_V1.json"
VOLUME3 = QA3 / "E40_U04_V3_VOLUMEDETECT_V1.txt"
CONTACT3 = QA3 / "E40_U04_V3_CONTACT_SHEET_V1.png"
COMPARE3 = QA3 / "E40_U04_V3_AUTHORITY_VS_FRAME0_V1.png"
HUMAN3 = QA3 / "E40_U04_V3_ORIGINAL_RES_HUMAN_QA_V1.json"
V4_VIDEO = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u04_v4_local_authority_motion_v1/E40_U04_V4_LOCAL_AUTHORITY_MOTION_CANDIDATE_V1.mp4"
V4_CADENCE = ROOT / "qa/e40_production_20260814/u04_v4_local_authority_motion_v1/E40_U04_V4_FRAME_CADENCE_AUDIT_V1.json"
V5_PLAN = ROOT / "qa/e40_preproduction_20260814/u04_v5_local_authority_cadence_repair_v1/E40_U04_V5_LOCAL_AUTHORITY_CADENCE_REPAIR_PLAN_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U04_V3_FAILURE_V5_LOCAL_SUCCESSOR_20260814.json"


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


def load_credit_module():
    sys.path.insert(0, str(TOOLS))
    path = TOOLS / "giggle_credit_statements.py"
    spec = importlib.util.spec_from_file_location("e40_u04_terminal_credit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load authoritative credit tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = ROOT
    return module


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def main() -> None:
    required = [SCHED, QUEUE, X2CL, MEMORY, TX, HARVEST, VIDEO, EXACT3, CADENCE3, OCR3, VOLUME3, CONTACT3, COMPARE3, V4_VIDEO, V4_CADENCE]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("missing evidence: " + ", ".join(missing))
    exact = json.loads(EXACT3.read_text(encoding="utf-8"))
    cadence3 = json.loads(CADENCE3.read_text(encoding="utf-8"))
    ocr3 = json.loads(OCR3.read_text(encoding="utf-8"))
    cadence4 = json.loads(V4_CADENCE.read_text(encoding="utf-8"))
    if exact.get("status") != "FAIL" or cadence3.get("status") != "PASS" or ocr3.get("status") != "PASS":
        raise SystemExit("U04 V3 machine evidence mismatch")
    if cadence4.get("status") != "FAIL":
        raise SystemExit("U04 V4 cadence evidence is not FAIL")

    credit = load_credit_module().fetch_task_credit_net_by_task_id(TASK_ID, event_description="SingleGenerateVideo")
    if credit.get("status") != "PASS_CHARGED" or int(credit.get("net_charged_credits", -1)) != 64:
        raise SystemExit("authoritative task credit classification is not Pay64")
    rows = credit.get("statement_rows") or []
    if len(rows) != 1 or rows[0].get("model") != "seedance-2.0-fast":
        raise SystemExit("authoritative task ledger model/row mismatch")

    now = datetime.now(timezone.utc)
    now_s = iso(now)
    human = {
        "schema": "qingshan.e40.u04.v3.original_resolution_human_qa.v1",
        "episode": "E40",
        "unit_id": "U04",
        "variant": "V3",
        "reviewed_at": now_s,
        "source": {"path": rel(VIDEO), "sha256": sha(VIDEO), "bytes": VIDEO.stat().st_size},
        "technical_probe": {
            "video": {"codec": "h264 High", "pixel_format": "yuv420p", "width": 720, "height": 1280, "fps": 24, "frames": 97, "duration_seconds": 4.041667},
            "audio": {"present": True, "codec": "aac", "channels": 2, "sample_rate_hz": 44100, "duration_seconds": 4.086009, "mean_volume_db": -42.9, "max_volume_db": -24.6},
            "audio_contract": "FAIL_HARD_SOURCE_AUDIO_STREAM_MUST_BE_ABSENT",
        },
        "original_resolution_review": {
            "one_actor_one_connected_hand": "PASS",
            "natural_five_finger_anatomy": "PASS",
            "single_frost_trace_recedes_without_transfer": "PASS",
            "restrained_finger_flex": "PASS",
            "gaze_shifts_to_offscreen_opponent": "PASS",
            "wrist_and_sleeve_recoil": "PASS",
            "stable_camera_no_cut_loop": "PASS",
            "text_watermark_modern_props": "ABSENT",
            "identity_drift": "MINOR_FRAME0_FACE_REGENERATION_HARD_GATE_FAIL",
            "visual_only_score": 91,
        },
        "machine_gates": {
            "exact_first_frame": {"path": rel(EXACT3), "sha256": sha(EXACT3), "status": "FAIL", "mae": 7.659212, "ssim_corrected_global_diagnostic": 0.967628, "phash_distance": 2},
            "decoded_frame0_to_frame1_continuity": "PASS",
            "cadence": {"path": rel(CADENCE3), "sha256": sha(CADENCE3), "status": "PASS"},
            "ocr": {"path": rel(OCR3), "sha256": sha(OCR3), "status": "PASS_ZERO_RECOGNITIONS_8_SAMPLES"},
            "audio_absent": {"path": rel(VOLUME3), "sha256": sha(VOLUME3), "status": "FAIL_HARD_AUDIBLE_AAC_STREAM"},
        },
        "visual_evidence": {"contact_sheet": {"path": rel(CONTACT3), "sha256": sha(CONTACT3)}, "authority_vs_frame0": {"path": rel(COMPARE3), "sha256": sha(COMPARE3)}},
        "verdict": "FAIL_HARD_FRAME0_AND_AUDIO_QUARANTINED",
        "quarantined": True,
        "admitted_to_agentcut": False,
        "execution_pixels_allowed": False,
        "unchanged_retry_forbidden": True,
        "forbidden_repairs": ["SINGLE_FRAME_PREPEND_OR_REPLACEMENT", "POST_HARVEST_AUDIO_STRIP_AS_ADMISSION_FIX"],
        "failure_memory_required": "PF-039",
    }
    atomic_json(HUMAN3, human)

    memory = json.loads(MEMORY.read_text(encoding="utf-8"))
    existing = {row.get("id") for row in memory.get("rules", [])}
    if "PF-039" not in existing:
        memory["rules"].append({
            "id": "PF-039",
            "failure": "U04 V3 Seedance Fast produced a coherent high-quality hand/frost/gaze performance, but decoded frame0 was regenerated away from the admitted authority (MAE 7.659212, global SSIM 0.967628) and the nominally silent source carried audible AAC noise (mean -42.9 dB, max -24.6 dB).",
            "first_pass_prompt_rule": "For U04 do not trust provider I2V to preserve exact decoded frame0 or omit audio. Quarantine provider pixels and switch to an independent local authority-only motion plate with frame0 exact and zero audio streams; never prepend/replace one frame or strip provider audio as an admission fix.",
            "pre_submit_check": "LOCAL_AUTHORITY_ONLY_FAILED_PROVIDER_PIXELS_EXCLUDED_EXACT_FRAME0_PASS_ZERO_AUDIO_STREAMS",
        })
    if "PF-040" not in existing:
        memory["rules"].append({
            "id": "PF-040",
            "failure": "U04 V4 local authority-only motion preserved the admitted frame and zero-audio contract, but delayed visible foreground movement created a 0.500-second opening cadence freeze from 0.375s.",
            "first_pass_prompt_rule": "Begin visible frost/hand foreground change immediately after frame0 and sustain bounded non-periodic motion through the opening; do not rely on sub-threshold candle breathing to clear cadence.",
            "pre_submit_check": "FRAME1_FOREGROUND_DELTA_PRESENT_AND_NO_OPENING_FREEZE_AT_0P15_THRESHOLD",
        })
    memory["updated_at"] = now_s
    atomic_json(MEMORY, memory)

    plan = {
        "schema": "qingshan.e40.u04.v5.local_authority_cadence_repair_plan.v1",
        "created_at": now_s,
        "predecessor": {"provider_variant": "V3", "task_id": TASK_ID, "pay": 64, "refund": 0, "human_qa": rel(HUMAN3), "human_qa_sha256": sha(HUMAN3)},
        "local_failed_variant": {"variant": "V4", "video": rel(V4_VIDEO), "video_sha256": sha(V4_VIDEO), "cadence": rel(V4_CADENCE), "cadence_sha256": sha(V4_CADENCE), "failure": "opening 0.500-second freeze"},
        "failure_memory": {"path": rel(MEMORY), "sha256": sha(MEMORY), "rules": ["PF-039", "PF-040"]},
        "material_change": "Start frost recession and connected hand micro-pressure immediately after decoded frame0, amplify opening foreground delta above cadence threshold, preserve authority-only source and zero audio streams.",
        "failed_provider_pixels_reused": False,
        "provider_posts": 0,
        "transactions": 0,
        "credits": 0,
        "status": "AUTHORIZED_ZERO_COST_LOCAL_V5_BUILD_AND_QA",
    }
    atomic_json(V5_PLAN, plan)

    tx = json.loads(TX.read_text(encoding="utf-8"))
    if tx.get("task_id") != TASK_ID:
        raise SystemExit("transaction task binding mismatch")
    tx.update({
        "state": "TERMINAL_COMPLETED_PAY64_OUTPUT_QUARANTINED",
        "terminal_recorded_at": now_s,
        "remote_status": "completed",
        "credit_classification": credit,
        "harvest": rel(HARVEST),
        "harvest_sha256": sha(HARVEST),
        "output": rel(VIDEO),
        "output_sha256": sha(VIDEO),
        "qa_verdict": rel(HUMAN3),
        "qa_verdict_sha256": sha(HUMAN3),
        "retry_guard": "UNCHANGED_REPLAY_CLOSED_PF039_LOCAL_AUTHORITY_ROUTE_ACTIVE",
    })
    atomic_json(TX, tx)

    scheduler = json.loads(SCHED.read_text(encoding="utf-8"))
    predecessor = None
    for row in scheduler.get("tasks", []):
        if row.get("task_id") == "E40-U04-V3-ADMITTED-FRAME-FAST720-PREFLIGHT-AND-VIDEO-QA":
            predecessor = row
            row.update({
                "state": "TERMINAL", "wait_scope": "NONE_TERMINAL", "provider_query_allowed": False, "download_allowed": False,
                "progress": "REMOTE_COMPLETED_PAY64_FRAME0_AND_AUDIO_HARD_FAIL_QUARANTINED_LOCAL_V4_CADENCE_FAIL",
                "last_progress_at": now_s, "next_action": "Terminal; unchanged replay forbidden. U04 V5 local authority-only cadence repair owns successor QA.",
                "next_due_at": None, "executor_next_wakeup_at": None, "evidence_ref": rel(HUMAN3), "evidence_sha256": sha(HUMAN3),
                "output_ref": rel(VIDEO), "output_sha256": sha(VIDEO), "completed_at": now_s,
                "terminal_status": "FAIL_HARD_FRAME0_AND_AUDIO_QUARANTINED_PAY64_NO_REPLAY",
            })
    if predecessor is None:
        raise SystemExit("missing U04 V3 scheduler task")
    successor_id = "E40-U04-V5-LOCAL-AUTHORITY-CADENCE-REPAIR-QA"
    if not any(row.get("task_id") == successor_id for row in scheduler.get("tasks", [])):
        scheduler["tasks"].append({
            "task_id": successor_id, "lane_id": "U04_LOCAL_AUTHORITY_MOTION_QA", "state": "QA", "wait_scope": "NONE_ACTIVE_QA", "zero_cost": True,
            "deliverable_type": "U04_V5_LOCAL_AUTHORITY_EXACT_FRAME_AUDIO0_CADENCE_OCR_HUMAN_QA", "priority": 171,
            "scope": ["E40", "U04", "V5", "PF-039", "PF-040", "LOCAL_AUTHORITY_ONLY", "EXACT_FRAME0", "AUDIO0", "CADENCE", "OCR", "NO_PROVIDER", "NO_RELEASE"],
            "exact_predecessor_task_id": predecessor["task_id"], "liveness_role": "PRODUCING", "observation_only": False,
            "maximum_new_submissions": 0, "authorization": False, "provider_post_allowed": False, "provider_query_allowed": False, "download_allowed": False,
            "provider_calls": 0, "transactions": 0, "credits": 0, "blocked_by": "V5_LOCAL_CADENCE_REPAIR_AND_QA_PENDING",
            "progress": "V3_QUARANTINED_V4_OPENING_CADENCE_FAIL_PF039_PF040_RECORDED_V5_ACTIVE",
            "last_progress_at": now_s, "next_action": "Build V5 with immediate foreground delta, then run exact frame0, frame0-to-1, audio0, cadence, OCR and original-resolution human QA.",
            "lease_owner": "codex-e40-production:u04-v5-local", "lease_expires_at": iso(now + timedelta(hours=2)), "next_due_at": iso(now + timedelta(minutes=10)),
            "execution_mode": "CONTINUOUS", "executor_handle": "automation:e40", "executor_task_id": successor_id,
            "executor_acknowledged_at": now_s, "executor_next_wakeup_at": iso(now + timedelta(minutes=10)),
            "evidence_ref": rel(V5_PLAN), "evidence_sha256": sha(V5_PLAN),
        })
    scheduler["updated_at"] = now_s
    scheduler["scheduler_decision"] = {"global_wait": False, "reason": "U04_V5_LOCAL_AUTHORITY_CADENCE_REPAIR_QA_ACTIVE"}
    atomic_json(SCHED, scheduler)

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue.update({
        "updated_at": now_s,
        "mode": "E40_CONTINUOUS_EPISODE_PRODUCTION_U04_V3_QUARANTINED_V5_LOCAL_QA_ACTIVE",
        "status": "E40_U04_V3_PAY64_FRAME0_AUDIO_FAIL_V4_CADENCE_FAIL_V5_LOCAL_REPAIR_ACTIVE",
        "updated_note_latest": "U04 V3 completed and was harvested once. Its coherent visual performance passed cadence/OCR/human review but failed exact frame0 and source-audio absence, so provider pixels are quarantined. V4 independent local authority motion then failed one opening cadence interval. PF-039/PF-040 are persisted and materially changed V5 local cadence repair is active; no provider retry.",
        "blocked_by": "U04_V5_LOCAL_EXACT_FRAME_AUDIO0_CADENCE_OCR_HUMAN_QA_PENDING; E40_FULL_EPISODE_ASSEMBLY_QA_AND_RELEASE_PENDING",
        "next_action": "Build and QA U04 V5 local authority-only cadence repair; admit only after all machine and original-resolution human gates pass.",
    })
    credits = queue["e40_credits"]
    credits.update({
        "gross_pay": 1577, "refund": 128, "net": 1449, "remaining": 8551, "video_pay": 1184,
        "active_remote_video_pay": 0, "active_remote_video_task_id": None,
        "pending_remote_video_task_count": 0, "pending_remote_video_task_ids": [],
        "status": "AUTHORITATIVE_TOTALS_1577_128_1449_U04_V3_TERMINAL_PAY64_QUARANTINED",
        "totals_fresh_through": f"U04_V3_TASK_ID_{TASK_ID}_TERMINAL_PAY64",
    })
    queue["latest_e40_u04_v3_fast720_harvest_qa"] = {
        "task_id": TASK_ID, "model": "seedance-2.0-fast", "pay": 64, "refund": 0, "net": 64,
        "harvest": rel(HARVEST), "harvest_sha256": sha(HARVEST), "output": rel(VIDEO), "output_sha256": sha(VIDEO),
        "human_qa": rel(HUMAN3), "human_qa_sha256": sha(HUMAN3), "admitted_to_agentcut": False,
        "status": "FAIL_HARD_FRAME0_AND_AUDIO_QUARANTINED_NO_REPLAY",
    }
    queue["latest_e40_u04_v5_local_authority_repair"] = {"plan": rel(V5_PLAN), "plan_sha256": sha(V5_PLAN), "status": "ACTIVE_ZERO_COST_BUILD_AND_QA"}
    queue["task_lane_scheduler"] = {"path": rel(SCHED), "heartbeat_integration": scheduler["heartbeat_integration"], "sha256": sha(SCHED)}
    atomic_json(QUEUE, queue)

    with X2CL.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {now_s} — E40 U04 V3 terminal quarantine; V5 local authority repair active\n\n")
        handle.write(f"- U04 V3 task `{TASK_ID}` completed and was harvested exactly once. Authoritative ledger classification is Pay 64 / Refund 0. Visual performance passed cadence, OCR and human91, but decoded frame0 failed the admitted authority (MAE 7.659212; corrected global SSIM diagnostic 0.967628) and the nominally silent source carried AAC audio (mean -42.9 dB, max -24.6 dB). `{rel(HUMAN3)}` SHA=`{sha(HUMAN3)}` quarantines all V3 execution pixels; no prepend, frame replacement or audio-strip admission fix is allowed.\n")
        handle.write(f"- Independent zero-credit V4 used only the admitted authority and no provider pixels, but cadence found an opening `0.375+0.500s` freeze. PF-039 and PF-040 are persisted in `{rel(MEMORY)}` SHA=`{sha(MEMORY)}`. Materially changed V5 will begin visible foreground motion immediately after frame0 and remains the active QA successor. No provider retry, upload, release or E38/E39 mutation occurred.\n")
    atomic_json(RECEIPT, {
        "schema": "qingshan.e40.u04.v3_failure_v5_local_successor.v1", "status": "PASS_V3_QUARANTINED_V5_LOCAL_QA_ACTIVE", "recorded_at": now_s,
        "task_id": TASK_ID, "credit_classification": credit, "human_qa": rel(HUMAN3), "human_qa_sha256": sha(HUMAN3),
        "v5_plan": rel(V5_PLAN), "v5_plan_sha256": sha(V5_PLAN), "failure_memory_sha256": sha(MEMORY),
        "scheduler_sha256": sha(SCHED), "work_queue_sha256": sha(QUEUE), "provider_posts": 0, "new_transactions": 0, "new_credits": 0,
    })
    print(json.dumps({"status": "PASS_V3_QUARANTINED_V5_LOCAL_QA_ACTIVE", "pay": 64, "refund": 0, "net": 64, "scheduler_sha256": sha(SCHED), "work_queue_sha256": sha(QUEUE)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
