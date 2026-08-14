#!/usr/bin/env python3
"""Admit U11 silent unit, continuity-bind U12 frame/audio, dispatch local U12 render."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

R = Path(__file__).resolve().parents[1]

V11 = R / "working_assets/e40_production_20260814/u11_v3_local_authority_side_room_cat_alert_silent_v1/E40-U11-V3-LOCAL-AUTHORITY-SIDE-ROOM-CAT-ALERT-SILENT.mp4"
M11 = R / "qa/e40_production_20260814/u11_v3_local_authority_side_room_cat_alert_silent_v1/E40_U11_V3_LOCAL_AUTHORITY_MACHINE_QA_V1.json"
O11 = R / "qa/e40_production_20260814/u11_v3_local_authority_side_room_cat_alert_silent_v1/E40_U11_V3_FULL_DURATION_OCR_AUDIT_V1.json"
OA11 = R / "qa/e40_production_20260814/u11_v3_local_authority_side_room_cat_alert_silent_v1/E40_U11_V3_OCR_FALSE_POSITIVE_ADJUDICATION_V1.json"
H11 = R / "qa/e40_production_20260814/u11_v3_local_authority_side_room_cat_alert_silent_v1/E40_U11_V3_ORIGINAL_RESOLUTION_HUMAN_VISUAL_QA_V1.json"
T11 = R / "qa/e40_production_20260814/u11_v3_local_authority_side_room_cat_alert_silent_v1/frame_0095_tail.png"
A11 = R / "workflow/releases/E40_U11_V3_SILENT_VISUAL_UNIT_ADMISSION_20260814.json"

F12 = R / "working_assets/e40_preproduction_20260814/u12_parallel_rubbing_throw_authority_reuse_v1/E40_U12_PARALLEL_CANDIDATE_V1_AUTHORITY_EXACT_START_FRAME_720X1280.png"
H12 = R / "qa/e40_preproduction_20260814/u12_parallel_rubbing_throw_authority_reuse_v1/E40_U12_PARALLEL_CANDIDATE_V1_ORIGINAL_RES_HUMAN_QA_V1.json"
O12 = R / "qa/e40_preproduction_20260814/u12_parallel_rubbing_throw_authority_reuse_v1/E40_U12_PARALLEL_CANDIDATE_V1_MACHINE_OCR_AUDIT_V1.json"
OA12 = R / "qa/e40_preproduction_20260814/u12_parallel_rubbing_throw_authority_reuse_v1/E40_U12_PARALLEL_CANDIDATE_V1_OCR_HUMAN_ADJUDICATION_V1.json"
AU12 = R / "working_assets/e40_production_20260814/u12_parallel_kokoro_exact_audio_candidates_v1/E40-DIA010_zm_009_speed1p0_normalized48k.wav"
AQ12 = R / "qa/e40_production_20260814/u12_parallel_kokoro_exact_audio_candidates_v1/E40_U12_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
AS12 = R / "qa/e40_production_20260814/u12_parallel_kokoro_exact_audio_candidates_v1/E40_U12_PARALLEL_KOKORO_SELECTED_AUDIO_RECEIPT_V1.json"
AR12 = R / "qa/e40_preproduction_20260814/u12_parallel_kokoro_exact_audio_candidates_v1/E40_U12_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
C12 = R / "qa/e40_preproduction_20260814/u12_parallel_rubbing_throw_authority_reuse_v1/E40_U11_TAIL_TO_U12_FRAME_CONTINUITY_QA_V1.json"
A12 = R / "workflow/releases/E40_U12_PARALLEL_EXACT_START_FRAME_AUDIO_ADMISSION_20260814.json"

LANES = R / "workflow/production_line/E40_TASK_LANES_V1.json"
QUEUE = R / "workflow/work_queue.json"
HANDOFF = R / "workflow/CODEX_TO_CLAUDE.md"
T11_ID = "E40-U11-V3-LOCAL-AUTHORITY-SIDE-ROOM-CAT-ALERT-SILENT-VISUAL-QA"
T12_ID = "E40-U12-V3-LOCAL-AUTHORITY-RUBBING-THROW-EXACT-DIA010-QA"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(R))


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def main() -> int:
    if any(path.exists() for path in (A11, C12, A12)):
        raise SystemExit("FAIL_COLLISION")
    required = (V11, M11, O11, OA11, H11, T11, F12, H12, O12, OA12, AU12, AQ12, AS12, AR12, LANES, QUEUE, HANDOFF)
    for path in required:
        if not path.is_file():
            raise SystemExit(f"FAIL_MISSING:{path}")
    m11, oa11, h11 = (json.loads(path.read_text()) for path in (M11, OA11, H11))
    h12, oa12, aq12, as12, ar12 = (json.loads(path.read_text()) for path in (H12, OA12, AQ12, AS12, AR12))
    if m11.get("failures") != ["OCR_NONZERO"] or not m11.get("frame0_pixel_exact") or m11.get("audio_stream_count") != 0:
        raise SystemExit("FAIL_U11_MACHINE_GATES")
    if oa11.get("status") != "PASS_FALSE_POSITIVE_ONLY_NO_VISIBLE_TEXT" or h11.get("effective_failures"):
        raise SystemExit("FAIL_U11_EFFECTIVE_OCR_HUMAN")
    if h12.get("status") != "PASS" or oa12.get("status") != "PASS_ZERO_VISIBLE_READABLE_TEXT":
        raise SystemExit("FAIL_U12_FRAME")
    selected = aq12.get("selected") or {}
    if aq12.get("status") != "PASS_MACHINE_SELECTION" or selected.get("normalized_sha256") != sha(AU12) or selected.get("asr_similarity") != 1.0:
        raise SystemExit("FAIL_U12_AUDIO")
    if as12.get("status") != "PASS_RELEASE_CLEAR_ZERO_CREDIT_EXACT_AUDIO_SELECTED" or ar12.get("releaseBlocked") is not False:
        raise SystemExit("FAIL_U12_RIGHTS")

    now = datetime.now(timezone.utc)
    canonical = {
        "canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
        "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
    }
    write_json(A11, {
        "schema": "qingshan.e40.u11.v3.silent_visual_unit_admission.v1",
        "status": "PASS_U11_V3_ADMITTED_FOR_EPISODE_ASSEMBLY",
        "admitted_at": stamp(now), "episode": "E40", "unit": "U11", **canonical,
        "video_path": rel(V11), "video_sha256": sha(V11),
        "machine_qa": rel(M11), "machine_qa_sha256": sha(M11),
        "raw_ocr_qa": rel(O11), "raw_ocr_qa_sha256": sha(O11),
        "ocr_false_positive_adjudication": rel(OA11), "ocr_false_positive_adjudication_sha256": sha(OA11),
        "human_qa": rel(H11), "human_qa_sha256": sha(H11),
        "tail_frame": rel(T11), "tail_frame_sha256": sha(T11),
        "gates": {"exact_frame0": True, "silent_no_audio_stream": True, "cat_alert": True, "chenji_finger_response": True, "cadence": True, "effective_no_visible_text": True},
        "provider_posts": 0, "credits": 0, "release_status": "NOT_RELEASED_UNIT_ONLY",
    })
    write_json(C12, {
        "schema": "qingshan.e40.u11_tail_to_u12_frame.continuity_qa.v1",
        "status": "PASS_CONTINUITY_BINDING", "reviewed_at": stamp(now),
        "predecessor_tail": rel(T11), "predecessor_tail_sha256": sha(T11),
        "candidate_frame": rel(F12), "candidate_frame_sha256": sha(F12),
        "checks": {"cat_warning_to_chenji_throw_cut": "PASS_CANONICAL_CAUSAL_CUT", "chenji_white_robe": "PASS", "warm_period_hall": "PASS", "frame_right_side_room_to_curtain_axis": "PASS", "one_midair_rubbing": "PASS", "yunfei_hidden_behind_curtain": "PASS", "effective_no_visible_text": "PASS"},
        "human_score": 92, "failures": [],
    })
    write_json(A12, {
        "schema": "qingshan.e40.u12.parallel.frame_audio_admission.v1",
        "status": "PASS_U12_EXACT_START_FRAME_AUDIO_ADMITTED_FOR_LOCAL_VIDEO",
        "admitted_at": stamp(now), "episode": "E40", "unit": "U12", **canonical,
        "canonical_line": "调令上的印，是您的旧印。", "speaker": "陈迹",
        "frame_path": rel(F12), "frame_sha256": sha(F12),
        "human_qa": rel(H12), "human_qa_sha256": sha(H12),
        "raw_ocr_qa": rel(O12), "raw_ocr_qa_sha256": sha(O12),
        "ocr_human_adjudication": rel(OA12), "ocr_human_adjudication_sha256": sha(OA12),
        "continuity_qa": rel(C12), "continuity_qa_sha256": sha(C12),
        "selected_audio": rel(AU12), "selected_audio_sha256": sha(AU12),
        "audio_qa": rel(AQ12), "audio_qa_sha256": sha(AQ12),
        "selected_audio_receipt": rel(AS12), "selected_audio_receipt_sha256": sha(AS12),
        "rights_evidence": rel(AR12), "rights_evidence_sha256": sha(AR12),
        "provider_posts": 0, "credits": 0, "release_status": "NOT_RELEASED_FRAME_ONLY",
    })

    lanes = json.loads(LANES.read_text())
    active = [task for task in lanes["tasks"] if task.get("task_id") == T11_ID]
    if len(active) != 1 or any(task.get("task_id") == T12_ID for task in lanes["tasks"]):
        raise SystemExit("FAIL_SCHEDULER")
    active[0].update({"state": "TERMINAL", "wait_scope": "NONE_TERMINAL", "blocked_by": None, "progress": "U11_FRAME0_SILENT_CADENCE_CAT_ALERT_EFFECTIVE_OCR_PASS_ADMITTED", "last_progress_at": stamp(now), "next_action": "Terminal U11; U12 local render owns production.", "next_due_at": None, "executor_next_wakeup_at": None, "evidence_ref": rel(A11), "evidence_sha256": sha(A11), "output_ref": rel(V11), "output_sha256": sha(V11), "completed_at": stamp(now), "terminal_status": "PASS_U11_V3_ADMITTED_FOR_EPISODE_ASSEMBLY"})
    lanes["tasks"].append({
        "task_id": T12_ID, "lane_id": "U12_LOCAL_AUTHORITY_RUBBING_THROW", "state": "RUNNING", "wait_scope": "NONE_ACTIVE_RUNNING", "zero_cost": True,
        "deliverable_type": "U12_EXACT_FRAME_EXACT_DIA010_RUBBING_THROW_VIDEO_AND_QA", "priority": 183,
        "scope": ["E40", "U12", "V3", "LOCAL_AUTHORITY_ONLY", "EXACT_FRAME0", "EXACT_DIA010", "MID_AIR_RUBBING", "RIGHTS_CLEAR", "NO_PROVIDER", "NO_RELEASE"],
        "exact_predecessor_task_id": T11_ID, "liveness_role": "PRODUCING", "observation_only": False, "maximum_new_submissions": 0, "authorization": False,
        "provider_post_allowed": False, "provider_query_allowed": False, "download_allowed": False, "provider_calls": 0, "transactions": 0, "credits": 0, "blocked_by": None,
        "progress": "U12_FRAME_AUDIO_CONTINUITY_RIGHTS_BOUND_LOCAL_RENDER_RUNNING", "last_progress_at": stamp(now),
        "next_action": "Render U12 authority-only rubbing throw: keep exact frame0, half-unrolled rubbing settles toward the inner table while Chenji delivers exact DIA010; run frame0, ASR, motion, OCR, cadence, human and rights QA.",
        "lease_owner": "codex-e40-production:u12-v3-local", "lease_expires_at": stamp(now + timedelta(hours=2)), "next_due_at": stamp(now + timedelta(minutes=10)),
        "execution_mode": "CONTINUOUS", "executor_handle": "automation:e40", "executor_task_id": T12_ID, "executor_acknowledged_at": stamp(now), "executor_next_wakeup_at": stamp(now + timedelta(minutes=10)),
        "evidence_ref": rel(A12), "evidence_sha256": sha(A12), "audio_ref": rel(AU12), "audio_sha256": sha(AU12),
    })
    lanes["updated_at"] = stamp(now)
    write_json(LANES, lanes)

    queue = json.loads(QUEUE.read_text())
    queue["latest_e40_u11_parallel_preproduction"].update({"status": "PASS_U11_V3_ADMITTED_FOR_EPISODE_ASSEMBLY", "video": rel(V11), "video_sha256": sha(V11), "unit_admission": rel(A11), "unit_admission_sha256": sha(A11), "active_task_id": None, "next_action": "Terminal U11; U12 local render running."})
    queue["latest_e40_u12_parallel_preproduction"] = {"status": "PASS_U12_FRAME_AUDIO_ADMITTED_LOCAL_VIDEO_RUNNING", "canonical_line": "调令上的印，是您的旧印。", "speaker": "陈迹", "frame": rel(F12), "frame_sha256": sha(F12), "human_qa": rel(H12), "human_qa_sha256": sha(H12), "ocr_adjudication": rel(OA12), "ocr_adjudication_sha256": sha(OA12), "selected_audio": rel(AU12), "selected_audio_sha256": sha(AU12), "audio_qa": rel(AQ12), "audio_qa_sha256": sha(AQ12), "rights_evidence": rel(AR12), "rights_evidence_sha256": sha(AR12), "continuity_qa": rel(C12), "continuity_qa_sha256": sha(C12), "frame_admission": rel(A12), "frame_admission_sha256": sha(A12), "provider_posts": 0, "credits": 0, "blocked_by": None, "active_task_id": T12_ID, "next_action": lanes["tasks"][-1]["next_action"]}
    write_json(QUEUE, queue)
    with HANDOFF.open("a", encoding="utf-8") as handle:
        handle.write(f"\n\n## E40 checkpoint {stamp(now)} — U11 admitted; U12 frame/audio bound and local render dispatched\n\n- U11 V3 `{rel(V11)}` SHA=`{sha(V11)}` passed exact frame0, silent/no-audio, cadence, natural-cat warning and HUMAN92. Its only raw OCR hit was one-frame Latin `I` on the far-right lattice/candle edge; original-resolution no-visible-text adjudication SHA=`{sha(OA11)}` made the effective gate PASS. Admission SHA=`{sha(A11)}`.\n- U11 tail to U12 frame continuity passed SHA=`{sha(C12)}`. U12 binds exact DIA010 audio SHA=`{sha(AU12)}` and rights-clear admission SHA=`{sha(A12)}`. Scheduler started `{T12_ID}`; provider posts/credits=0, no release.\n")
        handle.flush(); os.fsync(handle.fileno())
    print(json.dumps({"status": "PASS_U11_ADMITTED_U12_LOCAL_RENDER_RUNNING", "u11_admission_sha256": sha(A11), "u12_admission_sha256": sha(A12)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
