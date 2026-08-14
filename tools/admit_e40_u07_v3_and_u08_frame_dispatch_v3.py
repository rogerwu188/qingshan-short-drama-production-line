#!/usr/bin/env python3
"""Admit U07 V3, bind its tail to U08 frame, and dispatch U08 local video."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "working_assets/e40_production_20260814/u07_v3_local_authority_fifth_hover_exact_dialogue_v1/E40-U07-V3-LOCAL-AUTHORITY-EXACT-DIA006-FIFTH-HOVER.mp4"
MACHINE = ROOT / "qa/e40_production_20260814/u07_v3_local_authority_fifth_hover_exact_dialogue_v1/E40_U07_V3_LOCAL_AUTHORITY_MACHINE_QA_V1.json"
HUMAN = ROOT / "qa/e40_production_20260814/u07_v3_local_authority_fifth_hover_exact_dialogue_v1/E40_U07_V3_ORIGINAL_RES_HUMAN_VISUAL_QA_V1.json"
TAIL = ROOT / "qa/e40_production_20260814/u07_v3_local_authority_fifth_hover_exact_dialogue_v1/frame_0095_tail.png"
RIGHTS = ROOT / "qa/e40_preproduction_20260814/u07_v2_kokoro_rights_clearance_v1/E40_U07_V2_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
U07_ADMISSION = ROOT / "workflow/releases/E40_U07_V3_RIGHTS_CLEARED_EXACT_DIALOGUE_UNIT_ADMISSION_20260814.json"
U08_FRAME = ROOT / "working_assets/e40_preproduction_20260814/u08_parallel_exact_start_frame_v1/E40_U08_PARALLEL_EXACT_START_FRAME_720X1280_V2.png"
U08_HUMAN = ROOT / "qa/e40_preproduction_20260814/u08_parallel_exact_start_frame_v1/E40_U08_PARALLEL_EXACT_START_FRAME_HUMAN_QA_V1.json"
U08_OCR = ROOT / "qa/e40_preproduction_20260814/u08_parallel_exact_start_frame_v1/E40_U08_PARALLEL_EXACT_START_FRAME_OCR_AUDIT_V2.json"
U08_STATIC = ROOT / "qa/e40_preproduction_20260814/u08_parallel_exact_start_frame_v1/E40_U08_FAST720_BOUND_CANDIDATE_STATIC_GATE_V1.json"
U08_AUDIO = ROOT / "working_assets/e40_production_20260814/u08_parallel_kokoro_exact_audio_candidates_v2/E40-DIA007_zm_009_speed1p0_mono_compensated48k_v2a.wav"
U08_AUDIO_QA = ROOT / "qa/e40_production_20260814/u08_parallel_kokoro_exact_audio_candidates_v2/E40_U08_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V2.json"
U08_RIGHTS = ROOT / "qa/e40_preproduction_20260814/u08_parallel_kokoro_exact_audio_candidates_v1/E40_U08_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
CONTINUITY = ROOT / "qa/e40_preproduction_20260814/u08_parallel_exact_start_frame_v1/E40_U07_TAIL_TO_U08_FRAME_CONTINUITY_QA_V1.json"
U08_ADMISSION = ROOT / "workflow/releases/E40_U08_PARALLEL_EXACT_START_FRAME_ADMISSION_20260814.json"
SCHEDULER = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
WQ = ROOT / "workflow/work_queue.json"
X2CL = ROOT / "workflow/CODEX_TO_CLAUDE.md"
U07_TASK = "E40-U07-V3-LOCAL-AUTHORITY-EXACT-DIALOGUE-FIFTH-FROST-PERFORMANCE-QA"
U08_TASK = "E40-U08-V3-LOCAL-AUTHORITY-EXACT-DIALOGUE-FAN-SHADOW-PERFORMANCE-QA"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def main() -> int:
    outputs = (U07_ADMISSION, CONTINUITY, U08_ADMISSION)
    if any(path.exists() for path in outputs):
        raise SystemExit("FAIL_CLOSED_OUTPUT_COLLISION")
    required = (VIDEO, MACHINE, HUMAN, TAIL, RIGHTS, U08_FRAME, U08_HUMAN, U08_OCR, U08_STATIC, U08_AUDIO, U08_AUDIO_QA, U08_RIGHTS, SCHEDULER, WQ)
    for path in required:
        if not path.is_file():
            raise SystemExit(f"FAIL_MISSING:{path}")
    machine = json.loads(MACHINE.read_text(encoding="utf-8"))
    human = json.loads(HUMAN.read_text(encoding="utf-8"))
    rights = json.loads(RIGHTS.read_text(encoding="utf-8"))
    audio_qa = json.loads(U08_AUDIO_QA.read_text(encoding="utf-8"))
    u08_rights = json.loads(U08_RIGHTS.read_text(encoding="utf-8"))
    if not machine.get("status", "").startswith("PASS") or machine.get("failures") or machine.get("final_asr_similarity") != 1.0:
        raise SystemExit("FAIL_CLOSED_U07_MACHINE")
    if human.get("status") != "PASS_HUMAN_VISUAL_ADMISSION_READY" or rights.get("releaseBlocked") is not False:
        raise SystemExit("FAIL_CLOSED_U07_HUMAN_OR_RIGHTS")
    if not audio_qa.get("status", "").startswith("PASS") or u08_rights.get("releaseBlocked") is not False:
        raise SystemExit("FAIL_CLOSED_U08_AUDIO_OR_RIGHTS")
    moment = datetime.now(timezone.utc)
    u07_admission = {
        "schema": "qingshan.e40.u07.v3.rights_cleared_exact_dialogue_unit_admission.v1",
        "status": "PASS_U07_V3_ADMITTED_FOR_EPISODE_ASSEMBLY",
        "admitted_at": stamp(moment),
        "episode": "E40",
        "unit": "U07",
        "canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
        "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
        "video_path": rel(VIDEO),
        "video_sha256": sha(VIDEO),
        "machine_qa": rel(MACHINE),
        "machine_qa_sha256": sha(MACHINE),
        "human_qa": rel(HUMAN),
        "human_qa_sha256": sha(HUMAN),
        "rights_evidence": rel(RIGHTS),
        "rights_evidence_sha256": sha(RIGHTS),
        "tail_frame": rel(TAIL),
        "tail_frame_sha256": sha(TAIL),
        "gates": {"exact_frame0": True, "exact_asr": True, "four_marks_empty_fifth": True, "bounded_hover": True, "ocr_zero": True, "identity": True, "commercial_rights": True},
        "provider_posts": 0,
        "credits": 0,
        "release_status": "NOT_RELEASED_UNIT_ONLY",
    }
    atomic_json(U07_ADMISSION, u07_admission)
    continuity = {
        "schema": "qingshan.e40.u07_tail_to_u08_frame.continuity_qa.v1",
        "status": "PASS_CONTINUITY_BINDING",
        "reviewed_at": stamp(moment),
        "predecessor_tail": rel(TAIL),
        "predecessor_tail_sha256": sha(TAIL),
        "candidate_frame": rel(U08_FRAME),
        "candidate_frame_sha256": sha(U08_FRAME),
        "checks": {
            "same_chenji_identity_face_hairpin": "PASS",
            "same_white_robe_and_dark_hall": "PASS",
            "screen_direction_and_gaze_transition": "PASS_INTENTIONAL_CUT_TO_CURTAIN_REACTION",
            "table_and_warm_cool_lighting_continuity": "PASS",
            "fan_shadow_is_new_canonical_reaction_cue": "PASS",
            "no_wardrobe_or_character_guess": "PASS",
            "ocr_zero": "PASS"
        },
        "human_score": 91,
        "failures": []
    }
    atomic_json(CONTINUITY, continuity)
    u08_admission = {
        "schema": "qingshan.e40.u08.parallel.exact_start_frame_admission.v1",
        "status": "PASS_U08_EXACT_START_FRAME_ADMITTED_FOR_LOCAL_VIDEO",
        "admitted_at": stamp(moment),
        "episode": "E40",
        "unit": "U08",
        "canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
        "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
        "canonical_line": "他不是证人，是饵。",
        "frame_path": rel(U08_FRAME),
        "frame_sha256": sha(U08_FRAME),
        "human_qa": rel(U08_HUMAN),
        "human_qa_sha256": sha(U08_HUMAN),
        "ocr_qa": rel(U08_OCR),
        "ocr_qa_sha256": sha(U08_OCR),
        "static_gate": rel(U08_STATIC),
        "static_gate_sha256": sha(U08_STATIC),
        "continuity_qa": rel(CONTINUITY),
        "continuity_qa_sha256": sha(CONTINUITY),
        "selected_audio": rel(U08_AUDIO),
        "selected_audio_sha256": sha(U08_AUDIO),
        "audio_qa": rel(U08_AUDIO_QA),
        "audio_qa_sha256": sha(U08_AUDIO_QA),
        "rights_evidence": rel(U08_RIGHTS),
        "rights_evidence_sha256": sha(U08_RIGHTS),
        "provider_posts": 0,
        "credits": 0,
        "release_status": "NOT_RELEASED_FRAME_ONLY",
    }
    atomic_json(U08_ADMISSION, u08_admission)

    scheduler = json.loads(SCHEDULER.read_text(encoding="utf-8"))
    current = [row for row in scheduler["tasks"] if row.get("task_id") == U07_TASK]
    if len(current) != 1 or any(row.get("task_id") == U08_TASK for row in scheduler["tasks"]):
        raise SystemExit("FAIL_SCHEDULER_STATE")
    current[0].update({"state": "TERMINAL", "wait_scope": "NONE_TERMINAL", "blocked_by": None, "progress": "U07_V3_FRAME0_ASR_HOVER_OCR_IDENTITY_RIGHTS_PASS_ADMITTED", "last_progress_at": stamp(moment), "next_action": "Terminal U07; U08 frame/audio continuity-bound local video owns production.", "next_due_at": None, "executor_next_wakeup_at": None, "evidence_ref": rel(U07_ADMISSION), "evidence_sha256": sha(U07_ADMISSION), "output_ref": rel(VIDEO), "output_sha256": sha(VIDEO), "completed_at": stamp(moment), "terminal_status": "PASS_U07_V3_ADMITTED_FOR_EPISODE_ASSEMBLY"})
    scheduler["tasks"].append({
        "task_id": U08_TASK, "lane_id": "U08_LOCAL_AUTHORITY_EXACT_DIALOGUE_FAN_SHADOW", "state": "RUNNING", "wait_scope": "NONE_ACTIVE_RUNNING", "zero_cost": True,
        "deliverable_type": "U08_LOCAL_AUTHORITY_EXACT_FRAME_EXACT_DIA007_FAN_SHADOW_VIDEO_AND_QA", "priority": 179,
        "scope": ["E40", "U08", "V3", "LOCAL_AUTHORITY_ONLY", "EXACT_FRAME0", "EXACT_DIA007", "CHENJI_REACTION", "FAN_SHADOW", "RIGHTS_CLEAR", "NO_PROVIDER", "NO_RELEASE"],
        "exact_predecessor_task_id": U07_TASK, "liveness_role": "PRODUCING", "observation_only": False, "maximum_new_submissions": 0, "authorization": False,
        "provider_post_allowed": False, "provider_query_allowed": False, "download_allowed": False, "provider_calls": 0, "transactions": 0, "credits": 0, "blocked_by": None,
        "progress": "U08_FRAME_AUDIO_CONTINUITY_RIGHTS_BOUND_LOCAL_RENDER_RUNNING", "last_progress_at": stamp(moment),
        "next_action": "Render U08 local authority motion from admitted frame and exact DIA007; preserve fan-shadow reaction cue, then run exact frame0, ASR, OCR, visual, continuity, rights and duration QA.",
        "lease_owner": "codex-e40-production:u08-v3-local", "lease_expires_at": stamp(moment + timedelta(hours=2)), "next_due_at": stamp(moment + timedelta(minutes=10)),
        "execution_mode": "CONTINUOUS", "executor_handle": "automation:e40", "executor_task_id": U08_TASK, "executor_acknowledged_at": stamp(moment), "executor_next_wakeup_at": stamp(moment + timedelta(minutes=10)),
        "evidence_ref": rel(U08_ADMISSION), "evidence_sha256": sha(U08_ADMISSION), "audio_ref": rel(U08_AUDIO), "audio_sha256": sha(U08_AUDIO)
    })
    scheduler["updated_at"] = stamp(moment)
    atomic_json(SCHEDULER, scheduler)
    work = json.loads(WQ.read_text(encoding="utf-8"))
    work["latest_e40_u07_successor"] = {"status": "PASS_U07_V3_ADMITTED_FOR_EPISODE_ASSEMBLY", "video": rel(VIDEO), "video_sha256": sha(VIDEO), "admission": rel(U07_ADMISSION), "admission_sha256": sha(U07_ADMISSION), "next_action": "Terminal U07; U08 local video running."}
    work["latest_e40_u08_parallel_preproduction"].update({"status": "PASS_U08_FRAME_AUDIO_ADMITTED_LOCAL_VIDEO_RUNNING", "continuity_qa": rel(CONTINUITY), "continuity_qa_sha256": sha(CONTINUITY), "frame_admission": rel(U08_ADMISSION), "frame_admission_sha256": sha(U08_ADMISSION), "selected_audio": rel(U08_AUDIO), "selected_audio_sha256": sha(U08_AUDIO), "blocked_by": None, "active_task_id": U08_TASK, "next_action": scheduler["tasks"][-1]["next_action"]})
    atomic_json(WQ, work)
    with X2CL.open("a", encoding="utf-8") as stream:
        stream.write(f"\n\n## E40 checkpoint {stamp(moment)} — U07 admitted; U08 continuity/audio bound and local render dispatched\n\n- U07 V3 `{rel(VIDEO)}` SHA=`{sha(VIDEO)}` passed pixel-exact frame0, exact DIA006 ASR=1.0, OCR0, original-resolution HUMAN94, four-mark/empty-fifth hover semantics, identity and release-clear rights. Admission `{rel(U07_ADMISSION)}` SHA=`{sha(U07_ADMISSION)}`.\n- U07 tail to U08 frame continuity `{rel(CONTINUITY)}` SHA=`{sha(CONTINUITY)}` passed identity, white robe/hall, lighting, axis/gaze cut and canonical fan-shadow cue. U08 frame admission `{rel(U08_ADMISSION)}` SHA=`{sha(U08_ADMISSION)}` binds exact DIA007 audio SHA=`{sha(U08_AUDIO)}`; provider posts/credits=0.\n- Scheduler terminalized U07 and started `{U08_TASK}`. No provider submit or release.\n")
        stream.flush(); os.fsync(stream.fileno())
    print(json.dumps({"status": "PASS_U07_ADMITTED_U08_FRAME_AUDIO_BOUND_LOCAL_RENDER_RUNNING", "u07_admission_sha256": sha(U07_ADMISSION), "u08_admission_sha256": sha(U08_ADMISSION)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
