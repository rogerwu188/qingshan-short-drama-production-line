#!/usr/bin/env python3
"""Close U03 V4, register U04 exact frame, and dispatch its safe successor."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHED = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
LOCK = ROOT / "workflow/work_queue.json.lock"
X2CL = ROOT / "workflow/CODEX_TO_CLAUDE.md"
U03 = ROOT / "workflow/releases/E40_U03_V4_RIGHTS_CLEARED_AUDIOVISUAL_UNIT_ADMISSION_20260814.json"
U04 = ROOT / "workflow/releases/E40_U04_V2_EXACT_START_FRAME_ADMISSION_20260814.json"
RECEIPT = ROOT / "workflow/tasks/E40_U03_V4_CLOSEOUT_AND_U04_VIDEO_SUCCESSOR_DISPATCH_20260814.json"
OLD_TASK = "E40-U03-V2-VISUAL-ADMISSION-AND-AGENTCUT-ASSEMBLY-QA"
NEW_TASK = "E40-U04-V3-ADMITTED-FRAME-FAST720-PREFLIGHT-AND-VIDEO-QA"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, payload: dict) -> None:
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def main() -> int:
    u03 = json.loads(U03.read_text(encoding="utf-8"))
    u04 = json.loads(U04.read_text(encoding="utf-8"))
    if u03.get("status") != "PASS_U03_ADMITTED_FOR_EPISODE_ASSEMBLY":
        raise SystemExit("FAIL_CLOSED_U03_NOT_ADMITTED")
    if u04.get("status") != "PASS_U04_EXACT_START_FRAME_ADMITTED_FOR_VIDEO_GENERATION":
        raise SystemExit("FAIL_CLOSED_U04_FRAME_NOT_ADMITTED")
    now = datetime.now(timezone.utc)
    with LOCK.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        scheduler = json.loads(SCHED.read_text(encoding="utf-8"))
        old = next((task for task in scheduler["tasks"] if task.get("task_id") == OLD_TASK), None)
        if old is None:
            raise SystemExit("FAIL_CLOSED_OLD_TASK_MISSING")
        old.update({
            "state": "TERMINAL", "wait_scope": "NONE_TERMINAL", "blocked_by": None,
            "progress": "U03_V4_LOCAL_AUTHORITY_MOTION_EXACT_FRAME_CADENCE_OCR_SUBTITLE_ASR_LOUDNESS_AND_RIGHTS_PASS_ADMITTED",
            "last_progress_at": iso(now), "next_action": "Closed; U04 admitted-frame video successor registered.",
            "evidence_ref": str(U03.relative_to(ROOT)), "evidence_sha256": sha256(U03),
            "lease_expires_at": iso(now), "next_due_at": None,
        })
        scheduler["tasks"] = [task for task in scheduler["tasks"] if task.get("task_id") != NEW_TASK]
        scheduler["tasks"].append({
            "task_id": NEW_TASK,
            "lane_id": "U04_ADMITTED_FRAME_TO_VIDEO",
            "state": "RUNNING",
            "wait_scope": "NONE_ACTIVE_RUNNING",
            "zero_cost": True,
            "deliverable_type": "U04_ADMITTED_EXACT_FRAME_FAST720_PREFLIGHT_VIDEO_GENERATION_AND_QA",
            "priority": 170,
            "scope": ["E40", "U04", "V3", "EXACT_START_FRAME", "FAST720_PREFLIGHT", "VIDEO_QA", "SEEDANCE_2_0_FAST_ONLY", "NO_RELEASE"],
            "exact_predecessor_task_id": OLD_TASK,
            "liveness_role": "PRODUCING", "observation_only": False,
            "maximum_new_submissions": 1, "authorization": True,
            "provider_post_allowed": False, "provider_query_allowed": False, "download_allowed": False,
            "provider_calls": 0, "transactions": 0, "credits": 0,
            "blocked_by": "ZERO_COST_FAST720_PAID_PREFLIGHT_NOT_YET_PASSED",
            "progress": "U04_V2_COHERENT_NON_COLLAGE_EXACT_START_FRAME_ADMITTED_PREFLIGHT_REWRITE_DISPATCHED",
            "last_progress_at": iso(now),
            "next_action": "Materially rewrite and bind the U04 silent visual prompt to the admitted frame, run fast-only capability/price/collision/transaction-readiness gates, then persist a new transaction before at most one authorized provider POST.",
            "lease_owner": "codex-e40-production:u04-v3-fast720",
            "lease_expires_at": iso(now + timedelta(hours=2)),
            "next_due_at": iso(now + timedelta(minutes=10)),
            "execution_mode": "CONTINUOUS", "executor_handle": "automation:e40",
            "executor_task_id": NEW_TASK, "executor_acknowledged_at": iso(now),
            "executor_next_wakeup_at": iso(now + timedelta(minutes=10)),
            "evidence_ref": str(U04.relative_to(ROOT)), "evidence_sha256": sha256(U04),
        })
        scheduler["updated_at"] = iso(now)
        scheduler["recorded_at"] = iso(now)
        scheduler["scheduler_decision"] = {
            "global_wait": False,
            "reason": "U03_V4_TERMINAL_ADMITTED_U04_V3_RUNNING_FAST720_ZERO_COST_PREFLIGHT",
        }
        scheduler["heartbeat_integration"]["episode_terminal"] = False
        atomic_json(SCHED, scheduler)
        scheduler_sha = sha256(SCHED)

        queue = json.loads(QUEUE.read_text(encoding="utf-8"))
        queue.update({
            "updated_at": iso(now),
            "mode": "E40_CONTINUOUS_EPISODE_PRODUCTION_U03_ADMITTED_U04_FAST720_PREFLIGHT_RUNNING",
            "status": "E40_U03_V4_AUDIOVISUAL_UNIT_ADMITTED_U04_V2_EXACT_START_FRAME_ADMITTED_SUCCESSOR_RUNNING",
            "updated_note_latest": "U03 V4 is admitted from a pinned authority raster with exact first-frame continuity, cadence, OCR, exact subtitle/ASR, loudness and rights passes at zero credits. The rejected U04 collage was not reused; a coherent ImageGen U04 frame now passes human and zero-text QA. U04 fast-only video preflight is the active successor.",
            "next_action": "Rewrite and bind U04 fast-only silent visual prompt to the admitted frame; pass capability, current price, collision and transaction-readiness gates before any single paid POST.",
            "occupied_scope_count": 2, "real_active_handle_count": 2, "blocked_by": None,
        })
        queue["latest_e40_u03_v4_rights_cleared_audiovisual_admission"] = {
            "path": str(U03.relative_to(ROOT)), "sha256": sha256(U03),
            "video": u03["video"], "video_sha256": u03["video_sha256"], "status": u03["status"],
        }
        queue["latest_e40_u04_v2_exact_start_frame_admission"] = {
            "path": str(U04.relative_to(ROOT)), "sha256": sha256(U04),
            "image": u04["image"], "image_sha256": u04["image_sha256"], "status": u04["status"],
        }
        queue["task_lane_scheduler"]["sha256"] = scheduler_sha
        queue["task_lane_scheduler"]["heartbeat_integration"]["episode_terminal"] = False
        atomic_json(QUEUE, queue)

    entry = f"""

## {iso(now)} — E40 U03 V4 admitted; U04 coherent exact frame admitted and successor active

- U03 provider outputs V1/R2 remained rejected and were not repaired or reused. R2 remains authoritative Pay=`64`, Refund=`0`, Net=`64`, terminal QA-failed no-replay.
- A new zero-credit local authority-motion V3 was built from the pinned 720x1280 U03 raster. V3 passed exact-frame/continuity, OCR and subtitle gates but failed cadence at `2.167+0.500s`; failure memory was persisted before a material motion rewrite.
- U03 V4 SHA=`{u03['video_sha256']}` materially increased non-periodic post-1.65s foreground and candle motion. It passed decoded frame0 SSIM=`0.9996817`, MAE=`2.5384`, frame0→1 continuity, zero cadence failures, exact subtitle OCR, full-unit normalized ASR=`1.0`, LUFS=`-18.3`, peak=`-1.0 dBFS`, and pinned Apache-2.0 voice rights. Admission `{U03.relative_to(ROOT)}` SHA=`{sha256(U03)}`; provider posts=`0`, credits=`0`.
- U04 old deterministic composite remains failed/preserved (`HUMAN34_COLLAGE_ANATOMY_SCALE_FAIL`) and was not reused. Using the image-generation skill with four pinned project references, a single coherent eye/hand/frost frame was generated and deterministically cropped/resized to 720x1280. Candidate `{u04['image']}` SHA=`{u04['image_sha256']}` passed human QA score=`94`, one actor/one connected hand/one half-crawled frost trace, exact white wardrobe, period hall and OCR zero recognitions. Admission `{U04.relative_to(ROOT)}` SHA=`{sha256(U04)}`.
- Scheduler closes U03 and keeps `{NEW_TASK}` RUNNING. Provider POST remains disabled until a materially rewritten `seedance-2.0-fast`-only U04 package passes current price, collision, model capability and durable transaction-readiness gates. E38/E39 unchanged; no upload/release mutation.
"""
    with X2CL.open("a", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.write(entry)
        stream.flush()
        os.fsync(stream.fileno())
    atomic_json(RECEIPT, {
        "schema": "qingshan.e40.u03_v4_closeout_u04_video_successor_dispatch.v1",
        "status": "PASS_U03_TERMINAL_U04_SUCCESSOR_RUNNING",
        "created_at": iso(now), "u03_admission_sha256": sha256(U03), "u04_frame_admission_sha256": sha256(U04),
        "scheduler_sha256": sha256(SCHED), "work_queue_sha256": sha256(QUEUE), "x2cl_sha256": sha256(X2CL),
        "successor_task_id": NEW_TASK,
    })
    print(json.dumps({"status": "PASS_U03_TERMINAL_U04_SUCCESSOR_RUNNING", "successor": NEW_TASK, "scheduler_sha256": sha256(SCHED), "work_queue_sha256": sha256(QUEUE)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
