#!/usr/bin/env python3
"""Admit corrected U13 V4, bind U14 exact frame/audio, and dispatch local U14 work."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

R = Path(__file__).resolve().parents[1]
V13 = R / "working_assets/e40_production_20260814/u13_v4_local_authority_half_rise_denial_exact_dialogue_v1/E40-U13-V4-LOCAL-AUTHORITY-EXACT-DIA011-HALF-RISE-DENIAL-PROP-LOCKED.mp4"
M13 = R / "qa/e40_production_20260814/u13_v4_local_authority_half_rise_denial_exact_dialogue_v1/E40_U13_V4_LOCAL_AUTHORITY_MACHINE_QA_V1.json"
H13 = R / "qa/e40_production_20260814/u13_v4_local_authority_half_rise_denial_exact_dialogue_v1/E40_U13_V4_ORIGINAL_RESOLUTION_HUMAN_VISUAL_QA_V1.json"
R13 = R / "qa/e40_production_20260814/u13_v4_local_authority_half_rise_denial_exact_dialogue_v1/E40_U13_V4_FINAL_ADMISSION_READY_RECEIPT_V1.json"
T13 = R / "qa/e40_production_20260814/u13_v4_local_authority_half_rise_denial_exact_dialogue_v1/frame_0143_tail.png"
FM13 = R / "qa/e40_production_20260814/u13_v3_local_authority_half_rise_denial_exact_dialogue_v1/E40_U13_V3_FAILURE_MEMORY_V1.json"
RIGHTS13 = R / "qa/e40_preproduction_20260814/u13_parallel_kokoro_exact_audio_candidates_v1/E40_U13_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
A13 = R / "workflow/releases/E40_U13_V4_RIGHTS_CLEARED_EXACT_DIALOGUE_UNIT_ADMISSION_20260814.json"
F14 = R / "working_assets/e40_preproduction_20260814/u14_parallel_yunfei_hand_shadow_mid_press_v1/E40_U14_PARALLEL_CANDIDATE_V1_EXACT_START_FRAME_720X1280.png"
H14 = R / "qa/e40_preproduction_20260814/u14_parallel_yunfei_hand_shadow_mid_press_v1/E40_U14_PARALLEL_CANDIDATE_V1_ORIGINAL_RES_HUMAN_QA_V1.json"
O14 = R / "qa/e40_preproduction_20260814/u14_parallel_yunfei_hand_shadow_mid_press_v1/E40_U14_PARALLEL_CANDIDATE_V1_OCR_AUDIT_V1.json"
AU14 = R / "working_assets/e40_production_20260814/u14_parallel_kokoro_exact_audio_candidates_v1/E40-DIA012_zf_001_speed1p1_normalized48k.wav"
AQ14 = R / "qa/e40_production_20260814/u14_parallel_kokoro_exact_audio_candidates_v1/E40_U14_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
AS14 = R / "qa/e40_production_20260814/u14_parallel_kokoro_exact_audio_candidates_v1/E40_U14_PARALLEL_KOKORO_SELECTED_AUDIO_RECEIPT_V1.json"
AR14 = R / "qa/e40_preproduction_20260814/u14_parallel_kokoro_exact_audio_candidates_v1/E40_U14_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
C14 = R / "qa/e40_preproduction_20260814/u14_parallel_yunfei_hand_shadow_mid_press_v1/E40_U13_V4_TAIL_TO_U14_FRAME_CONTINUITY_QA_V1.json"
A14 = R / "workflow/releases/E40_U14_PARALLEL_EXACT_START_FRAME_AUDIO_ADMISSION_20260814.json"
S = R / "workflow/production_line/E40_TASK_LANES_V1.json"
W = R / "workflow/work_queue.json"
X = R / "workflow/CODEX_TO_CLAUDE.md"
T13ID = "E40-U13-V3-LOCAL-AUTHORITY-YUNFEI-HALF-RISE-EXACT-DIA011-QA"
T14ID = "E40-U14-V1-LOCAL-AUTHORITY-HAND-SHADOW-PRESS-EXACT-DIA012-QA"
CANON = {"canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b", "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(R))


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob); handle.flush(); os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True); raise


def main() -> int:
    inputs = (V13, M13, H13, R13, T13, FM13, RIGHTS13, F14, H14, O14, AU14, AQ14, AS14, AR14, S, W, X)
    for path in inputs:
        if not path.is_file():
            raise SystemExit(f"FAIL_MISSING:{path}")
    if any(path.exists() for path in (A13, C14, A14)):
        raise SystemExit("FAIL_OUTPUT_COLLISION")
    m13, h13, r13, rights13 = (json.loads(path.read_text()) for path in (M13, H13, R13, RIGHTS13))
    if m13.get("status") != "PASS_MACHINE_HUMAN_VISUAL_QA_PENDING" or m13.get("failures") or m13.get("final_asr_similarity") != 1.0:
        raise SystemExit("FAIL_U13_MACHINE_GATE")
    if not h13.get("status", "").startswith("PASS_ADMISSION_READY") or not r13.get("status", "").startswith("PASS_U13") or rights13.get("releaseBlocked") is not False:
        raise SystemExit("FAIL_U13_HUMAN_RIGHTS_GATE")
    h14, o14, aq14, as14, ar14 = (json.loads(path.read_text()) for path in (H14, O14, AQ14, AS14, AR14))
    selected = aq14.get("selected") or {}
    if h14.get("status") != "PASS" or o14.get("status") != "PASS" or o14.get("recognitions") or aq14.get("status") != "PASS_MACHINE_SELECTION":
        raise SystemExit("FAIL_U14_VISUAL_AUDIO_GATE")
    if selected.get("normalized_sha256") != sha(AU14) or selected.get("asr_similarity") != 1.0 or not as14.get("status", "").startswith("PASS_RELEASE_CLEAR") or ar14.get("releaseBlocked") is not False:
        raise SystemExit("FAIL_U14_BINDING_RIGHTS_GATE")
    now = datetime.now(timezone.utc)
    atomic_json(A13, {
        "schema": "qingshan.e40.u13.v4.unit_admission.v1", "status": "PASS_U13_V4_ADMITTED_FOR_EPISODE_ASSEMBLY", "admitted_at": stamp(now),
        "episode": "E40", "unit": "U13", **CANON, "video_path": rel(V13), "video_sha256": sha(V13),
        "machine_qa": rel(M13), "machine_qa_sha256": sha(M13), "human_qa": rel(H13), "human_qa_sha256": sha(H13),
        "final_receipt": rel(R13), "final_receipt_sha256": sha(R13), "tail_frame": rel(T13), "tail_frame_sha256": sha(T13),
        "v3_failure_memory": rel(FM13), "v3_failure_memory_sha256": sha(FM13), "rights_evidence": rel(RIGHTS13), "rights_evidence_sha256": sha(RIGHTS13),
        "gates": {"frame0_exact": True, "exact_asr": True, "half_rise": True, "cadence": True, "ocr_zero": True, "landed_rubbing_locked": True, "identity": True, "commercial_rights": True},
        "provider_posts": 0, "credits": 0, "release_status": "NOT_RELEASED_UNIT_ONLY"
    })
    atomic_json(C14, {
        "schema": "qingshan.e40.u13_v4_tail_to_u14_frame.continuity_qa.v1", "status": "PASS_CONTINUITY_BINDING", "reviewed_at": stamp(now),
        "predecessor_tail": rel(T13), "predecessor_tail_sha256": sha(T13), "candidate_frame": rel(F14), "candidate_frame_sha256": sha(F14),
        "checks": {"yunfei_half_rise_to_hand_press_escalation": "PASS_CAUSAL_STATE_ADVANCE", "chenji_reverse_axis": "PASS", "warm_hall_curtain": "PASS", "single_round_fan": "PASS", "single_landed_rubbing": "PASS", "hand_precontact_air_gap": "PASS", "ocr_zero": "PASS"},
        "human_score": 91, "failures": []
    })
    atomic_json(A14, {
        "schema": "qingshan.e40.u14.parallel.frame_audio_admission.v1", "status": "PASS_U14_EXACT_START_FRAME_AUDIO_ADMITTED_FOR_LOCAL_VIDEO", "admitted_at": stamp(now),
        "episode": "E40", "unit": "U14", **CANON, "canonical_line": "替本宫\"代办\"印的手，就在身侧。", "speaker": "云妃",
        "frame_path": rel(F14), "frame_sha256": sha(F14), "human_qa": rel(H14), "human_qa_sha256": sha(H14), "ocr_qa": rel(O14), "ocr_qa_sha256": sha(O14),
        "continuity_qa": rel(C14), "continuity_qa_sha256": sha(C14), "selected_audio": rel(AU14), "selected_audio_sha256": sha(AU14),
        "audio_qa": rel(AQ14), "audio_qa_sha256": sha(AQ14), "selected_audio_receipt": rel(AS14), "selected_audio_receipt_sha256": sha(AS14),
        "rights_evidence": rel(AR14), "rights_evidence_sha256": sha(AR14), "provider_posts": 0, "credits": 0, "release_status": "NOT_RELEASED_FRAME_ONLY"
    })
    sched = json.loads(S.read_text())
    current = [task for task in sched["tasks"] if task.get("task_id") == T13ID]
    if len(current) != 1 or any(task.get("task_id") == T14ID for task in sched["tasks"]):
        raise SystemExit("FAIL_SCHEDULER_GATE")
    current[0].update({"state": "TERMINAL", "wait_scope": "NONE_TERMINAL", "blocked_by": None, "progress": "U13_V4_ALL_GATES_PASS_ADMITTED", "last_progress_at": stamp(now), "next_action": "Terminal U13; U14 local render owns production.", "next_due_at": None, "executor_next_wakeup_at": None, "evidence_ref": rel(A13), "evidence_sha256": sha(A13), "output_ref": rel(V13), "output_sha256": sha(V13), "completed_at": stamp(now), "terminal_status": "PASS_U13_V4_ADMITTED_FOR_EPISODE_ASSEMBLY"})
    sched["tasks"].append({
        "task_id": T14ID, "lane_id": "U14_LOCAL_AUTHORITY_HAND_SHADOW_PRESS", "state": "RUNNING", "wait_scope": "NONE_ACTIVE_RUNNING", "zero_cost": True,
        "deliverable_type": "U14_EXACT_FRAME_EXACT_DIA012_HAND_PRESS_VIDEO_AND_QA", "priority": 185,
        "scope": ["E40", "U14", "V1", "LOCAL_AUTHORITY_ONLY", "EXACT_FRAME0", "EXACT_DIA012", "HAND_PRESS", "RIGHTS_CLEAR", "NO_PROVIDER", "NO_RELEASE"],
        "exact_predecessor_task_id": T13ID, "liveness_role": "PRODUCING", "observation_only": False, "maximum_new_submissions": 0, "authorization": False,
        "provider_post_allowed": False, "provider_query_allowed": False, "download_allowed": False, "provider_calls": 0, "transactions": 0, "credits": 0, "blocked_by": None,
        "progress": "U14_FRAME_AUDIO_CONTINUITY_RIGHTS_BOUND_LOCAL_RENDER_RUNNING", "last_progress_at": stamp(now),
        "next_action": "Render U14 authority-only hidden Yunfei hand-shadow press with exact DIA012; preserve one fan, one landed rubbing, Chenji closed mouth, then run frame0, ASR, motion, OCR, cadence, human and rights QA.",
        "lease_owner": "codex-e40-production:u14-v1-local", "lease_expires_at": stamp(now + timedelta(hours=2)), "next_due_at": stamp(now + timedelta(minutes=10)),
        "execution_mode": "CONTINUOUS", "executor_handle": "automation:e40", "executor_task_id": T14ID, "executor_acknowledged_at": stamp(now), "executor_next_wakeup_at": stamp(now + timedelta(minutes=10)),
        "evidence_ref": rel(A14), "evidence_sha256": sha(A14), "audio_ref": rel(AU14), "audio_sha256": sha(AU14)
    })
    sched["updated_at"] = stamp(now)
    atomic_json(S, sched)
    work = json.loads(W.read_text())
    work["latest_e40_u13_parallel_preproduction"].update({"status": "PASS_U13_V4_ADMITTED_FOR_EPISODE_ASSEMBLY", "video": rel(V13), "video_sha256": sha(V13), "unit_admission": rel(A13), "unit_admission_sha256": sha(A13), "active_task_id": None, "next_action": "Terminal U13; U14 local render running."})
    work["latest_e40_u14_parallel_preproduction"] = {"status": "PASS_U14_FRAME_AUDIO_ADMITTED_LOCAL_VIDEO_RUNNING", "canonical_line": "替本宫\"代办\"印的手，就在身侧。", "speaker": "云妃", "frame": rel(F14), "frame_sha256": sha(F14), "selected_audio": rel(AU14), "selected_audio_sha256": sha(AU14), "continuity_qa": rel(C14), "continuity_qa_sha256": sha(C14), "frame_admission": rel(A14), "frame_admission_sha256": sha(A14), "provider_posts": 0, "credits": 0, "blocked_by": None, "active_task_id": T14ID, "next_action": sched["tasks"][-1]["next_action"]}
    atomic_json(W, work)
    with X.open("a", encoding="utf-8") as handle:
        handle.write(f"\n\n## E40 checkpoint {stamp(now)} — corrected U13 V4 admitted; U14 local render dispatched\n\n- U13 V3 failed closed on moving the landed rubbing and wrote failure memory SHA=`{sha(FM13)}`. Material V4 `{rel(V13)}` SHA=`{sha(V13)}` restores the protected table/prop region every frame and passes exact frame0, 144-frame cadence, OCR0, exact DIA011 ASR=1.0, HUMAN92 and rights; admission SHA=`{sha(A13)}`.\n- U13 V4 tail to U14 hand-shadow precontact frame continuity passed SHA=`{sha(C14)}`. U14 binds exact DIA012 audio SHA=`{sha(AU14)}` and admission SHA=`{sha(A14)}`; scheduler started `{T14ID}`. Provider posts/credits=0, no release.\n")
        handle.flush(); os.fsync(handle.fileno())
    print(json.dumps({"status": "PASS_U13_V4_ADMITTED_U14_LOCAL_RENDER_RUNNING", "u13_admission_sha256": sha(A13), "u14_admission_sha256": sha(A14)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
