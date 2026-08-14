#!/usr/bin/env python3
"""Persist E40 U02 closeout, U03 audio progress, and the safe successor lane."""

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
U02_ADMIT = ROOT / "workflow/releases/E40_U02_V14_RIGHTS_CLEARED_AUDIOVISUAL_UNIT_ADMISSION_20260814.json"
U03_ADMIT = ROOT / "workflow/releases/E40_U03_DIA003_RIGHTS_CLEARED_EXACT_AUDIO_ADMISSION_20260814.json"
RECEIPT = ROOT / "workflow/tasks/E40_U02_V14_CLOSEOUT_AND_U03_VISUAL_SUCCESSOR_DISPATCH_20260814.json"
OLD_TASK = "E40-U02-V11-EXACT-YUNFEI-AUDIO-SUBTITLE-AGENTCUT-ASSEMBLY-QA"
NEW_TASK = "E40-U03-V2-VISUAL-ADMISSION-AND-AGENTCUT-ASSEMBLY-QA"


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
    u02 = json.loads(U02_ADMIT.read_text(encoding="utf-8"))
    u03 = json.loads(U03_ADMIT.read_text(encoding="utf-8"))
    if u02.get("status") != "PASS_U02_ADMITTED_FOR_EPISODE_ASSEMBLY" or u03.get("status") != "PASS_ADMITTED_FOR_U03_AGENTCUT_ASSEMBLY":
        raise SystemExit("FAIL_CLOSED_ADMISSION_RECEIPT")
    now = datetime.now(timezone.utc)
    with LOCK.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        scheduler = json.loads(SCHED.read_text(encoding="utf-8"))
        old = next((task for task in scheduler["tasks"] if task.get("task_id") == OLD_TASK), None)
        if old is None:
            raise SystemExit("FAIL_CLOSED_OLD_TASK_MISSING")
        old.update({
            "state": "TERMINAL", "wait_scope": "NONE_TERMINAL", "blocked_by": None,
            "progress": "V14_RIGHTS_CLEARED_U02_AUDIOVISUAL_UNIT_QA_PASS_ADMITTED_FOR_EPISODE_ASSEMBLY",
            "last_progress_at": iso(now),
            "next_action": "Closed; successor U03 visual admission and AgentCut assembly is registered.",
            "evidence_ref": str(U02_ADMIT.relative_to(ROOT)), "evidence_sha256": sha256(U02_ADMIT),
            "lease_expires_at": iso(now), "next_due_at": None,
        })
        scheduler["tasks"] = [task for task in scheduler["tasks"] if task.get("task_id") != NEW_TASK]
        scheduler["tasks"].append({
            "task_id": NEW_TASK,
            "lane_id": "U03_VISUAL_AND_AGENTCUT_ASSEMBLY",
            "state": "RUNNING",
            "wait_scope": "NONE_ACTIVE_RUNNING",
            "zero_cost": True,
            "deliverable_type": "U03_ADMITTED_VISUAL_PLUS_EXACT_AUDIO_AGENTCUT_UNIT_ASSEMBLY",
            "priority": 169,
            "scope": ["E40", "U03", "V2", "VISUAL_ADMISSION", "EXACT_AUDIO", "SUBTITLES", "AGENTCUT", "SEEDANCE_2_0_FAST_ONLY", "NO_RELEASE"],
            "exact_predecessor_task_id": OLD_TASK,
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
            "blocked_by": None,
            "progress": "U03_DIA003_RIGHTS_CLEARED_EXACT_AUDIO_ADMITTED_VISUAL_INVENTORY_AND_AUTHORITY_AUDIT_STARTED",
            "last_progress_at": iso(now),
            "next_action": "Audit existing U03 visual candidates and exact-start-frame authority; if none is admitted, build the exact local start frame and fresh seedance-2.0-fast-only paid preflight before any durable transaction or provider POST.",
            "lease_owner": "codex-e40-production:u03-v2-visual-agentcut",
            "lease_expires_at": iso(now + timedelta(hours=2)),
            "next_due_at": iso(now + timedelta(minutes=10)),
            "execution_mode": "CONTINUOUS",
            "executor_handle": "automation:e40",
            "executor_task_id": NEW_TASK,
            "executor_acknowledged_at": iso(now),
            "executor_next_wakeup_at": iso(now + timedelta(minutes=10)),
            "evidence_ref": str(U03_ADMIT.relative_to(ROOT)),
            "evidence_sha256": sha256(U03_ADMIT),
        })
        scheduler["updated_at"] = iso(now)
        scheduler["recorded_at"] = iso(now)
        scheduler["scheduler_decision"] = "U02_V14_TERMINAL_ADMITTED_U03_V2_RUNNING_VISUAL_AUTHORITY_AUDIT_AND_AGENTCUT_ASSEMBLY"
        scheduler["heartbeat_integration"]["episode_terminal"] = False
        atomic_json(SCHED, scheduler)
        scheduler_sha = sha256(SCHED)

        queue = json.loads(QUEUE.read_text(encoding="utf-8"))
        queue.update({
            "updated_at": iso(now),
            "mode": "E40_CONTINUOUS_EPISODE_PRODUCTION_U02_ADMITTED_U03_VISUAL_AGENTCUT_RUNNING",
            "status": "E40_U02_V14_RIGHTS_CLEARED_AUDIOVISUAL_UNIT_ADMITTED_U03_DIA003_AUDIO_ADMITTED_SUCCESSOR_RUNNING",
            "updated_note_latest": "Roger delegated routine creative choices. U02 V14 is admitted after exact ASR, subtitle OCR, first-frame, cadence, loudness and Apache-2.0 rights gates; no paid replay occurred. U03 DIA003 is also rights-cleared and exact-ASR admitted at zero credits. The active successor is U03 visual authority inventory and AgentCut unit assembly.",
            "next_action": "Run U03 visual candidate and exact-start-frame authority audit, then either bind an admitted visual or prepare a fresh seedance-2.0-fast-only paid preflight with durable transaction-before-submit.",
            "occupied_scope_count": 2,
            "real_active_handle_count": 2,
            "blocked_by": None,
        })
        queue["e40_credits"].update({"gross_pay": 1513, "net": 1385, "remaining": 8615, "audio_pay": 4, "totals_fresh_through": "U02_DIA001_PAY2_TERMINAL_RIGHTS_FAIL_PLUS_ZERO_CREDIT_KOKORO_U02_U03_ADMISSIONS"})
        queue["latest_e40_u02_v14_rights_cleared_audiovisual_admission"] = {
            "path": str(U02_ADMIT.relative_to(ROOT)), "sha256": sha256(U02_ADMIT),
            "video": u02["video"], "video_sha256": u02["video_sha256"],
            "status": u02["status"], "dialogue_coverage": "2/2", "rights_clear": True,
        }
        queue["latest_e40_u03_dia003_rights_cleared_audio_admission"] = {
            "path": str(U03_ADMIT.relative_to(ROOT)), "sha256": sha256(U03_ADMIT),
            "audio": u03["audio"], "audio_sha256": u03["audio_sha256"], "status": u03["status"],
        }
        queue["task_lane_scheduler"]["sha256"] = scheduler_sha
        queue["task_lane_scheduler"]["heartbeat_integration"]["episode_terminal"] = False
        atomic_json(QUEUE, queue)

    entry = f"""

## {iso(now)} — E40 U02 rights-cleared audiovisual admission; U03 successor active

- Roger's standing instruction `你应该自己选择，以后不需要问我` is persisted at `workflow/approvals/ROGER_E40_AUTONOMOUS_VOICE_EMOTION_SELECTION_20260814.json` SHA=`41b78d54152998d892d72db731bc2a18ef4f2f544138e6eb46fc7a5c6e6ce05d` and added to heartbeat automation `e40`; routine voice/emotion/speed/candidate/editorial choices no longer require a user menu.
- The one Giggle cloned-voice DIA-001 task remained exactly-once terminal, authoritative Pay=`2`, Refund=`0`, Net=`2`, and was not replayed after its commercial-rights metadata failed. Failure memory remains SHA=`4210cf109f5966aedd653e069d1a67b4adc6efe8f3d96c8639da7c29d4e3616f`.
- Replaced that failed rights route with pinned local `hexgrad/Kokoro-82M-v1.1-zh` revision `01e7505bd6a7a2ac4975463114c3a7650a9f7218`, weights SHA=`b1d8410fa44dfb5c15471fd6c4225ea6b4e9ac7fa03c98e8bea47a9928476e2b`, Apache-2.0 model/license evidence and permissively granted Chinese dataset evidence. Provider posts=`0`, credits=`0`.
- U02 V12 slow candidates all passed exact ASR but failed the 4-second picture runtime gate. Material pace repair V13 selected built-in female voice `zf_001`: DIA-001=`1.625s`, DIA-002=`2.075s`, pair plus gap=`3.82s`, both normalized exact-ASR=`1.0`.
- AgentCut strict-media validation passed with zero issues. Its FFmpeg lacked `drawtext`; the capability failure was persisted and the already-QA'd transparent subtitle bitmaps were used at identical timing. U02 V14 output `{u02['video']}` SHA=`{u02['video_sha256']}` passed first-frame, cadence, full-duration text safety, exact 2/2 subtitle sample OCR, full-unit ASR=`1.0`, LUFS=`-17.8`, peak=`-1.0 dBFS`, and rights gate. Admission `{U02_ADMIT.relative_to(ROOT)}` SHA=`{sha256(U02_ADMIT)}`.
- Continued immediately to U03: DIA-003 `换，还是不换？` reused the same rights-cleared `zf_001` identity at speed `1.28`; audio `{u03['audio']}` SHA=`{u03['audio_sha256']}` passed normalized exact ASR=`1.0`, duration=`1.8s`, LUFS=`-19.3`, peak=`-2.0 dBFS`. Admission `{U03_ADMIT.relative_to(ROOT)}` SHA=`{sha256(U03_ADMIT)}`; provider posts=`0`, credits=`0`.
- Scheduler/work queue now close U02 and keep `E40-U03-V2-VISUAL-ADMISSION-AND-AGENTCUT-ASSEMBLY-QA` RUNNING. Next: audit U03 visual candidates/exact-start-frame authority, then bind an admitted visual or prepare a fresh `seedance-2.0-fast`-only paid preflight before any transaction/POST. E38/E39 unchanged; no platform/release mutation.
"""
    with X2CL.open("a", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.write(entry)
        stream.flush()
        os.fsync(stream.fileno())
    atomic_json(RECEIPT, {
        "schema": "qingshan.e40.u02_v14_closeout_u03_successor_dispatch.v1",
        "status": "PASS_U02_TERMINAL_U03_SUCCESSOR_RUNNING",
        "created_at": iso(now), "u02_admission_sha256": sha256(U02_ADMIT), "u03_audio_admission_sha256": sha256(U03_ADMIT),
        "scheduler_sha256": sha256(SCHED), "work_queue_sha256": sha256(QUEUE), "x2cl_sha256": sha256(X2CL),
        "successor_task_id": NEW_TASK,
    })
    print(json.dumps({"status": "PASS_U02_TERMINAL_U03_SUCCESSOR_RUNNING", "successor": NEW_TASK, "scheduler_sha256": sha256(SCHED), "work_queue_sha256": sha256(QUEUE)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
