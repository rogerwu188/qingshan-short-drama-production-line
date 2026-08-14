#!/usr/bin/env python3
"""Classify U05 V3 hard failure and dispatch zero-cost local V4 precompile QA."""

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
TASK_ID = "36e91c3b-0c31-4e65-9146-a2d6c26bf092"
TASK_KEY = "E40-U05-V3-FAST720-ADMITTED-FRAME-NATIVE-EXACT-DIA004-V1"
REMOTE_TASK = "E40-U05-V3-ADMITTED-FRAME-FAST720-NATIVE-DIA004-VIDEO-QA"
SUCCESSOR = "E40-U05-V4-LOCAL-AUTHORITY-EXACT-DIALOGUE-PERFORMANCE-PRECOMPILE-QA"
SCHED = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
X2CL = ROOT / "workflow/CODEX_TO_CLAUDE.md"
MEMORY = ROOT / "workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json"
TX = ROOT / f"workflow/tasks/giggle_video_submit_transactions/E40/{TASK_KEY}__166276fd8a025f48.json"
HARVEST = ROOT / "workflow/tasks/E40_U05_V3_FAST720_HARVEST_20260814.json"
VIDEO = ROOT / f"working_assets/e40_production_20260814/u05_v3_fast720/{TASK_KEY}_{TASK_ID}.mp4"
QA_DIR = ROOT / "qa/e40_production_20260814/u05_v3_fast720_harvest_qa_v1"
EXACT = QA_DIR / "E40_U05_V3_EXACT_FIRST_FRAME_POST_HARVEST_GATE_V1.json"
CADENCE = QA_DIR / "E40_U05_V3_FRAME_CADENCE_AUDIT_V1.json"
OCR = QA_DIR / "E40_U05_V3_FULL_DURATION_OCR_AUDIT_V1.json"
CONTACT = QA_DIR / "E40_U05_V3_ORIGINAL_RES_CONTACT_SHEET_V1.jpg"
HUMAN = QA_DIR / "E40_U05_V3_ORIGINAL_RES_HUMAN_QA_V1.json"
PLAN = ROOT / "qa/e40_preproduction_20260814/u05_v4_local_authority_exact_dialogue_v1/E40_U05_V4_LOCAL_AUTHORITY_EXACT_DIALOGUE_PLAN_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U05_V3_FAILURE_V4_LOCAL_SUCCESSOR_20260814.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def load_credit_module():
    sys.path.insert(0, str(TOOLS))
    path = TOOLS / "giggle_credit_statements.py"
    spec = importlib.util.spec_from_file_location("e40_u05_terminal_credit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load authoritative credit tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = ROOT
    return module


def main() -> None:
    required = [SCHED, QUEUE, X2CL, MEMORY, TX, HARVEST, VIDEO, EXACT, CADENCE, OCR, CONTACT]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("missing evidence: " + ", ".join(missing))
    exact = json.loads(EXACT.read_text(encoding="utf-8"))
    cadence = json.loads(CADENCE.read_text(encoding="utf-8"))
    ocr = json.loads(OCR.read_text(encoding="utf-8"))
    if exact.get("status") != "FAIL" or cadence.get("status") != "PASS" or ocr.get("status") != "PASS":
        raise SystemExit("U05 V3 evidence mismatch")
    credit = load_credit_module().fetch_task_credit_net_by_task_id(TASK_ID, event_description="SingleGenerateVideo")
    if credit.get("status") != "PASS_CHARGED" or int(credit.get("net_charged_credits", -1)) != 64:
        raise SystemExit("authoritative task credit classification is not Pay64")
    rows = credit.get("statement_rows") or []
    if len(rows) != 1 or rows[0].get("model") != "seedance-2.0-fast":
        raise SystemExit("authoritative task ledger model/row mismatch")

    now = datetime.now(timezone.utc)
    now_s = iso(now)
    metrics = exact["frame0_authority"]["metrics"]
    human = {
        "schema": "qingshan.e40.u05.v3.original_resolution_human_qa.v1",
        "episode": "E40",
        "unit_id": "U05",
        "variant": "V3",
        "reviewed_at": now_s,
        "source": {"path": rel(VIDEO), "sha256": sha(VIDEO), "bytes": VIDEO.stat().st_size},
        "technical_probe": {"video": {"codec": "h264 High", "width": 720, "height": 1280, "fps": 24, "frames": 97, "duration_seconds": 4.041667}, "audio": {"present": True, "codec": "aac", "channels": 2, "sample_rate_hz": 44100, "duration_seconds": 4.086009}},
        "original_resolution_review": {
            "one_visible_actor_and_speaker": "PASS",
            "white_robe_hall_curtain_continuity": "PASS",
            "exactly_two_blank_pages": "PASS",
            "page_owner_and_hand_contact": "PASS",
            "visible_mouth_performance": "PASS_VISUAL_ONLY_ASR_NOT_REQUIRED_AFTER_EARLY_FRAME0_HARD_FAIL",
            "natural_realtime_action_and_stable_camera": "PASS",
            "readable_text_watermark_modern_props": "ABSENT",
            "visual_only_score": 92,
        },
        "machine_gates": {
            "exact_first_frame": {"path": rel(EXACT), "sha256": sha(EXACT), "status": "FAIL", "mae": metrics["mae"], "ssim": metrics["ssim"], "phash_hamming": metrics["phash_hamming"]},
            "decoded_frame0_to_frame1_continuity": exact["frame0_to_frame1_continuity"]["status"],
            "cadence": {"path": rel(CADENCE), "sha256": sha(CADENCE), "status": "PASS"},
            "ocr": {"path": rel(OCR), "sha256": sha(OCR), "status": "PASS_ZERO_RECOGNITIONS_8_SAMPLES"},
            "exact_asr_and_lip_sync": "NOT_EVALUATED_FOR_ADMISSION_AFTER_PRIOR_HARD_FRAME0_FAILURE",
        },
        "visual_evidence": {"contact_sheet": {"path": rel(CONTACT), "sha256": sha(CONTACT)}},
        "verdict": "FAIL_HARD_FRAME0_AUTHORITY_QUARANTINED",
        "quarantined": True,
        "admitted_to_agentcut": False,
        "execution_pixels_allowed": False,
        "unchanged_retry_forbidden": True,
        "forbidden_repairs": ["SINGLE_FRAME_PREPEND_OR_REPLACEMENT", "RAW_V3_PIXEL_OR_AUDIO_REUSE_AS_ADMISSION_FIX"],
        "failure_memory_required": "PF-043",
    }
    atomic_json(HUMAN, human)
    plan = {
        "schema": "qingshan.e40.u05.v4.local_authority_exact_dialogue_plan.v1",
        "created_at": now_s,
        "predecessor": {"variant": "V3", "task_id": TASK_ID, "pay": 64, "refund": 0, "human_qa": rel(HUMAN), "human_qa_sha256": sha(HUMAN)},
        "authority_frame": "working_assets/e40_preproduction_20260814/u05_v2_imagegen_coherent_exact_start_frame_v1/E40_U05_V2_IMAGEGEN_COHERENT_EXACT_START_FRAME_720X1280_V1.png",
        "authority_sha256": "4f5205fa8a001b1943a322ee146ec19f4a62c530a9b1286bf921e327c2dbcc7e",
        "canonical_line": "先请教娘娘——扣他，为何不杀？",
        "material_change": "Switch from provider-regenerated I2V pixels to a separately versioned authority-only local performance: exact decoded frame0, immediate page/hand motion, rights-cleared exact Chenji dialogue, phoneme-timed bounded mouth deformation, and independently verified lip sync.",
        "failed_provider_pixels_or_audio_reused": False,
        "required_gates": ["exact_frame0", "frame0_to_frame1_continuity", "cadence", "ocr0", "exact_asr1p0", "single_speaker", "visible_lip_sync", "original_resolution_human"],
        "provider_posts": 0,
        "transactions": 0,
        "credits": 0,
        "status": "AUTHORIZED_ZERO_COST_LOCAL_PRECOMPILE_AND_QA",
    }
    atomic_json(PLAN, plan)

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
        "qa_verdict": rel(HUMAN),
        "qa_verdict_sha256": sha(HUMAN),
        "retry_guard": "UNCHANGED_REPLAY_CLOSED_PF043_LOCAL_AUTHORITY_ROUTE_ACTIVE",
    })
    atomic_json(TX, tx)

    scheduler = json.loads(SCHED.read_text(encoding="utf-8"))
    predecessor = next((row for row in scheduler.get("tasks", []) if row.get("task_id") == REMOTE_TASK), None)
    if predecessor is None:
        raise SystemExit("missing U05 V3 scheduler task")
    predecessor.update({
        "state": "TERMINAL",
        "wait_scope": "NONE_TERMINAL",
        "provider_query_allowed": False,
        "download_allowed": False,
        "progress": "REMOTE_COMPLETED_PAY64_FRAME0_AUTHORITY_HARD_FAIL_QUARANTINED_PF043",
        "last_progress_at": now_s,
        "next_action": f"Terminal; unchanged replay forbidden. {SUCCESSOR} owns the local authority route.",
        "next_due_at": None,
        "executor_next_wakeup_at": None,
        "evidence_ref": rel(HUMAN),
        "evidence_sha256": sha(HUMAN),
        "output_ref": rel(VIDEO),
        "output_sha256": sha(VIDEO),
        "completed_at": now_s,
        "terminal_status": "FAIL_HARD_FRAME0_AUTHORITY_QUARANTINED_PAY64_NO_REPLAY",
    })
    successor = next((row for row in scheduler.get("tasks", []) if row.get("task_id") == SUCCESSOR), None)
    payload = {
        "task_id": SUCCESSOR,
        "lane_id": "U05_LOCAL_AUTHORITY_EXACT_DIALOGUE",
        "state": "QA",
        "wait_scope": "NONE_ACTIVE_QA",
        "zero_cost": True,
        "deliverable_type": "U05_V4_LOCAL_AUTHORITY_EXACT_FRAME_EXACT_DIALOGUE_LIPSYNC_PRECOMPILE_AND_QA",
        "priority": 174,
        "scope": ["E40", "U05", "V4", "PF-043", "LOCAL_AUTHORITY_ONLY", "EXACT_FRAME0", "EXACT_DIALOGUE", "VISIBLE_LIPSYNC", "NO_PROVIDER", "NO_RELEASE"],
        "exact_predecessor_task_id": REMOTE_TASK,
        "liveness_role": "PRODUCING",
        "observation_only": False,
        "maximum_new_submissions": 0,
        "authorization": False,
        "provider_post_allowed": False,
        "provider_query_allowed": False,
        "download_allowed": False,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
        "blocked_by": "V4_LOCAL_AUTHORITY_EXACT_DIALOGUE_PRECOMPILE_AND_QA_PENDING",
        "progress": "V3_QUARANTINED_PF043_RECORDED_V4_LOCAL_AUTHORITY_ROUTE_ACTIVE",
        "last_progress_at": now_s,
        "next_action": "Compile a rights-cleared exact Chenji line and authority-only phoneme-timed mouth/page/hand performance; render a separately versioned candidate, then run every exact-frame/audio/dialogue/lip-sync/OCR/human gate.",
        "lease_owner": "codex-e40-production:u05-v4-local",
        "lease_expires_at": iso(now + timedelta(hours=2)),
        "next_due_at": iso(now + timedelta(minutes=10)),
        "execution_mode": "CONTINUOUS",
        "executor_handle": "automation:e40",
        "executor_task_id": SUCCESSOR,
        "executor_acknowledged_at": now_s,
        "executor_next_wakeup_at": iso(now + timedelta(minutes=10)),
        "evidence_ref": rel(PLAN),
        "evidence_sha256": sha(PLAN),
    }
    if successor is None:
        scheduler["tasks"].append(payload)
    else:
        successor.update(payload)
    scheduler["updated_at"] = now_s
    scheduler["recorded_at"] = now_s
    scheduler["scheduler_decision"] = {"global_wait": False, "reason": "U05_V4_LOCAL_AUTHORITY_EXACT_DIALOGUE_QA_ACTIVE"}
    scheduler["heartbeat_integration"]["episode_terminal"] = False
    atomic_json(SCHED, scheduler)

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue.update({
        "updated_at": now_s,
        "mode": "E40_CONTINUOUS_EPISODE_PRODUCTION_U05_V3_QUARANTINED_V4_LOCAL_QA_ACTIVE",
        "status": "E40_U05_V3_PAY64_FRAME0_FAIL_V4_LOCAL_AUTHORITY_EXACT_DIALOGUE_ACTIVE",
        "updated_note_latest": "U05 V3 completed and was harvested once. Coherent one-actor/two-page performance, cadence and OCR passed, but exact decoded frame0 failed the admitted authority and the clip is quarantined. PF-043 is persisted; a separately versioned zero-credit local authority-only exact-dialogue performance route is active. No provider replay.",
        "blocked_by": "U05_V4_LOCAL_EXACT_FRAME_EXACT_DIALOGUE_LIPSYNC_QA_PENDING; E40_FULL_EPISODE_ASSEMBLY_QA_AND_RELEASE_PENDING",
        "next_action": "Compile and render U05 V4 authority-only exact-dialogue performance, then admit only after exact-frame, ASR, lip-sync, cadence, OCR and original-resolution human QA pass.",
    })
    credits = queue["e40_credits"]
    credits.update({
        "active_remote_video_pay": 0,
        "active_remote_video_task_id": None,
        "pending_remote_video_task_count": 0,
        "pending_remote_video_task_ids": [],
        "status": "AUTHORITATIVE_TOTALS_1641_128_1513_U05_V3_TERMINAL_PAY64_QUARANTINED",
        "totals_fresh_through": f"U05_V3_TASK_ID_{TASK_ID}_TERMINAL_PAY64",
    })
    queue["latest_e40_u05_v3_fast720_harvest_qa"] = {
        "task_id": TASK_ID,
        "model": "seedance-2.0-fast",
        "pay": 64,
        "refund": 0,
        "net": 64,
        "harvest": rel(HARVEST),
        "harvest_sha256": sha(HARVEST),
        "output": rel(VIDEO),
        "output_sha256": sha(VIDEO),
        "human_qa": rel(HUMAN),
        "human_qa_sha256": sha(HUMAN),
        "admitted_to_agentcut": False,
        "status": "FAIL_HARD_FRAME0_AUTHORITY_QUARANTINED_NO_REPLAY",
    }
    queue["latest_e40_u05_v4_local_authority_repair"] = {"plan": rel(PLAN), "plan_sha256": sha(PLAN), "status": "ACTIVE_ZERO_COST_PRECOMPILE_AND_QA"}
    queue["task_lane_scheduler"] = {"path": rel(SCHED), "heartbeat_integration": scheduler["heartbeat_integration"], "sha256": sha(SCHED)}
    atomic_json(QUEUE, queue)

    with X2CL.open("a", encoding="utf-8") as stream:
        stream.write(f"\n## {now_s} — E40 U05 V3 terminal quarantine; V4 local authority dialogue route active\n\n")
        stream.write(f"- U05 V3 task `{TASK_ID}` completed and was downloaded once. Exact authoritative credit classification is Pay64 / Refund0. The raw source passed cadence, OCR0 and original-resolution visual review (one actor, white robe, two blank pages, visible mouth), but decoded frame0 failed the admitted authority: MAE `{metrics['mae']:.6f}`, SSIM `{metrics['ssim']:.6f}`, pHash `{metrics['phash_hamming']}`. `{rel(HUMAN)}` SHA=`{sha(HUMAN)}` quarantines all V3 pixels/audio; no one-frame prepend/replacement, raw reuse or unchanged provider replay.\n")
        stream.write(f"- PF-043 is persisted in `{rel(MEMORY)}` SHA=`{sha(MEMORY)}`. Materially changed zero-credit successor `{SUCCESSOR}` is active from `{rel(PLAN)}` SHA=`{sha(PLAN)}`: exact authority frame0, rights-cleared exact Chenji line, phoneme-timed bounded mouth/page/hand motion, and full exact-frame/ASR/lip-sync/cadence/OCR/human QA. No new provider post, transaction, credit, release or E38/E39 mutation.\n")
    atomic_json(RECEIPT, {
        "schema": "qingshan.e40.u05.v3_failure_v4_local_successor.v1",
        "status": "PASS_V3_QUARANTINED_V4_LOCAL_QA_ACTIVE",
        "recorded_at": now_s,
        "task_id": TASK_ID,
        "credit_classification": credit,
        "human_qa": rel(HUMAN),
        "human_qa_sha256": sha(HUMAN),
        "v4_plan": rel(PLAN),
        "v4_plan_sha256": sha(PLAN),
        "failure_memory_sha256": sha(MEMORY),
        "scheduler_sha256": sha(SCHED),
        "work_queue_sha256": sha(QUEUE),
        "provider_posts": 0,
        "new_transactions": 0,
        "new_credits": 0,
    })
    print(json.dumps({"status": "PASS_V3_QUARANTINED_V4_LOCAL_QA_ACTIVE", "pay": 64, "refund": 0, "net": 64, "scheduler_sha256": sha(SCHED), "work_queue_sha256": sha(QUEUE)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
