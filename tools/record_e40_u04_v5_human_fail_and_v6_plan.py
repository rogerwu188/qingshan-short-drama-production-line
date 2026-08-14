#!/usr/bin/env python3
"""Persist U04 V5 human failure and authorize materially changed local V6."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY = ROOT / "workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json"
SCHED = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
X2CL = ROOT / "workflow/CODEX_TO_CLAUDE.md"
VIDEO = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u04_v5_local_authority_cadence_repair_v1/E40_U04_V5_LOCAL_AUTHORITY_MOTION_CADENCE_REPAIR_CANDIDATE_V1.mp4"
CONTACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u04_v5_local_authority_cadence_repair_v1/E40_U04_V5_LOCAL_AUTHORITY_MOTION_CONTACT_SHEET_V1.png"
EXACT = ROOT / "qa/e40_production_20260814/u04_v5_local_authority_cadence_repair_v1/E40_U04_V5_EXACT_FIRST_FRAME_GATE_V1.json"
CADENCE = ROOT / "qa/e40_production_20260814/u04_v5_local_authority_cadence_repair_v1/E40_U04_V5_FRAME_CADENCE_AUDIT_V1.json"
OCR = ROOT / "qa/e40_production_20260814/u04_v5_local_authority_cadence_repair_v1/E40_U04_V5_SOURCE_OCR_AUDIT_V1.json"
HUMAN = ROOT / "qa/e40_production_20260814/u04_v5_local_authority_cadence_repair_v1/E40_U04_V5_ORIGINAL_RES_HUMAN_QA_V1.json"
PLAN = ROOT / "qa/e40_preproduction_20260814/u04_v6_local_semantic_mask_repair_v1/E40_U04_V6_LOCAL_SEMANTIC_MASK_REPAIR_PLAN_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U04_V5_HUMAN_FAIL_V6_PLAN_20260814.json"


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
    required = [MEMORY, SCHED, QUEUE, X2CL, VIDEO, CONTACT, EXACT, CADENCE, OCR]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("missing evidence: " + ", ".join(missing))
    for path in (EXACT, CADENCE, OCR):
        if json.loads(path.read_text(encoding="utf-8")).get("status") != "PASS":
            raise SystemExit(f"machine gate not PASS: {path}")
    now = datetime.now(timezone.utc)
    now_s = iso(now)
    human = {
        "schema": "qingshan.e40.u04.v5.original_resolution_human_qa.v1",
        "episode": "E40", "unit_id": "U04", "variant": "V5", "reviewed_at": now_s,
        "source": {"path": rel(VIDEO), "sha256": sha(VIDEO)},
        "machine_gates": {
            "exact_frame": {"path": rel(EXACT), "sha256": sha(EXACT), "status": "PASS", "mae": 2.332824, "ssim": 0.998786, "phash_distance": 0},
            "frame0_to_frame1": {"status": "PASS", "mae": 2.204672, "ssim": 0.991893, "mean_optical_flow": 0.475949},
            "cadence": {"path": rel(CADENCE), "sha256": sha(CADENCE), "status": "PASS"},
            "ocr": {"path": rel(OCR), "sha256": sha(OCR), "status": "PASS_ZERO_RECOGNITIONS"},
            "audio_absent": "PASS_ZERO_AUDIO_STREAMS",
        },
        "human_checks": {
            "one_actor_one_connected_hand": "PASS",
            "natural_five_finger_anatomy": "PASS",
            "stable_camera_no_cut_loop": "PASS",
            "frost_recession_visible_and_complete": "FAIL_TRACE_REMAINS_VISIBLY_STATIC_ACROSS_CONTACT_SAMPLES",
            "neck_and_collar_geometry": "FAIL_LOCAL_MASK_BOUNDARY_SMEAR",
            "text_watermark_modern_props": "ABSENT",
        },
        "score": 58, "minimum_score": 80,
        "verdict": "FAIL_HUMAN_SEMANTIC_FROST_AND_MASK_BOUNDARY_QUARANTINED",
        "admitted_to_agentcut": False, "execution_pixels_allowed": False,
        "failure_memory_required": "PF-041",
    }
    atomic_json(HUMAN, human)

    memory = json.loads(MEMORY.read_text(encoding="utf-8"))
    if any(row.get("id") == "PF-041" for row in memory.get("rules", [])):
        raise SystemExit("PF-041 already exists; refusing duplicate transition")
    memory["rules"].append({
        "id": "PF-041",
        "failure": "U04 V5 passed exact frame0, frame0-to-1, zero-audio, cadence and OCR, but the frost-removal alpha stayed in authority coordinates while the hand layer moved, leaving the frost trace visibly static; the large inpainted hand background also smeared the neck/collar boundary.",
        "first_pass_prompt_rule": "Transform the frost-removal alpha and clean-finger plate with the same hand remap, then blend in moving coordinates. Composite the bounded hand remap over the untouched authority instead of an inpainted full-hand background, and keep the hand mask below the collar.",
        "pre_submit_check": "MOVING_FROST_ALPHA_BOUND_TO_HAND_REMAP_TRACE_VISIBLY_RECEDES_NO_NECK_COLLAR_MASK_SMEAR",
    })
    memory["updated_at"] = now_s
    atomic_json(MEMORY, memory)

    plan = {
        "schema": "qingshan.e40.u04.v6.local_semantic_mask_repair_plan.v1", "created_at": now_s,
        "predecessor": {"variant": "V5", "video": rel(VIDEO), "video_sha256": sha(VIDEO), "human_qa": rel(HUMAN), "human_qa_sha256": sha(HUMAN)},
        "failure_memory": {"path": rel(MEMORY), "sha256": sha(MEMORY), "rule": "PF-041"},
        "material_changes": ["move clean-finger plate and frost alpha with hand remap", "replace full-hand background inpaint with untouched-authority soft composite", "restrict hand mask below collar"],
        "failed_provider_pixels_reused": False, "provider_posts": 0, "transactions": 0, "credits": 0,
        "status": "AUTHORIZED_ZERO_COST_LOCAL_V6_BUILD_AND_QA",
    }
    atomic_json(PLAN, plan)

    scheduler = json.loads(SCHED.read_text(encoding="utf-8"))
    task = next((row for row in scheduler.get("tasks", []) if row.get("task_id") == "E40-U04-V5-LOCAL-AUTHORITY-CADENCE-REPAIR-QA"), None)
    if task is None or task.get("state") != "QA":
        raise SystemExit("active U04 V5 scheduler task missing")
    task.update({
        "progress": "V5_MACHINE_GATES_PASS_HUMAN58_FROST_STATIC_COLLAR_SMEAR_PF041_V6_ACTIVE",
        "blocked_by": "V6_MOVING_FROST_ALPHA_AND_UNTOUCHED_AUTHORITY_COMPOSITE_QA_PENDING",
        "last_progress_at": now_s,
        "next_action": "Build V6 with moving frost alpha and no full-hand background inpaint; rerun all gates and original-resolution human QA.",
        "lease_expires_at": iso(now + timedelta(hours=2)), "next_due_at": iso(now + timedelta(minutes=10)),
        "executor_acknowledged_at": now_s, "executor_next_wakeup_at": iso(now + timedelta(minutes=10)),
        "evidence_ref": rel(PLAN), "evidence_sha256": sha(PLAN),
    })
    scheduler["updated_at"] = now_s
    scheduler["scheduler_decision"] = {"global_wait": False, "reason": "U04_V6_LOCAL_SEMANTIC_MASK_REPAIR_QA_ACTIVE"}
    atomic_json(SCHED, scheduler)

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue.update({
        "updated_at": now_s,
        "mode": "E40_CONTINUOUS_EPISODE_PRODUCTION_U04_V6_LOCAL_SEMANTIC_REPAIR_ACTIVE",
        "status": "E40_U04_V5_MACHINE_PASS_HUMAN_FAIL_V6_LOCAL_REPAIR_ACTIVE",
        "updated_note_latest": "U04 V5 passes exact frame0, audio0, cadence and OCR but is quarantined by original-resolution human QA: frost alpha did not follow the moving hand and the full-hand inpaint smeared the collar boundary. PF-041 is persisted and a materially changed zero-credit V6 local semantic-mask repair is active.",
        "blocked_by": "U04_V6_LOCAL_SEMANTIC_MASK_REPAIR_AND_FULL_QA_PENDING; E40_FULL_EPISODE_ASSEMBLY_QA_AND_RELEASE_PENDING",
        "next_action": "Render and QA U04 V6 with hand-bound frost removal and untouched-authority compositing; admit only after human score >=80.",
    })
    queue["latest_e40_u04_v5_human_qa"] = {"path": rel(HUMAN), "sha256": sha(HUMAN), "status": human["verdict"]}
    queue["latest_e40_u04_v6_local_semantic_repair"] = {"plan": rel(PLAN), "plan_sha256": sha(PLAN), "status": plan["status"]}
    queue["task_lane_scheduler"] = {"path": rel(SCHED), "heartbeat_integration": scheduler["heartbeat_integration"], "sha256": sha(SCHED)}
    atomic_json(QUEUE, queue)
    with X2CL.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {now_s} — E40 U04 V5 machine-pass / human-fail; V6 semantic repair active\n\n")
        handle.write(f"- V5 `{rel(VIDEO)}` SHA=`{sha(VIDEO)}` passes exact frame0, frame0→1, zero-audio, cadence and OCR, but human QA `{rel(HUMAN)}` SHA=`{sha(HUMAN)}` scores 58: the frost alpha remained in authority coordinates while the hand moved, and the full-hand inpaint smeared the collar boundary. PF-041 is persisted before V6.\n")
        handle.write("- V6 materially binds both the clean-finger plate and frost-removal alpha to the hand remap, composites over untouched authority, and restricts the hand mask below the collar. Provider posts/transactions/credits remain zero; no release or E38/E39 mutation.\n")
    atomic_json(RECEIPT, {"schema": "qingshan.e40.u04.v5_human_fail_v6_plan.v1", "status": "PASS_V5_QUARANTINED_V6_ACTIVE", "recorded_at": now_s, "human_qa_sha256": sha(HUMAN), "plan_sha256": sha(PLAN), "memory_sha256": sha(MEMORY), "scheduler_sha256": sha(SCHED), "work_queue_sha256": sha(QUEUE)})
    print(json.dumps({"status": "PASS_V5_QUARANTINED_V6_ACTIVE", "human_qa_sha256": sha(HUMAN), "plan_sha256": sha(PLAN)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
