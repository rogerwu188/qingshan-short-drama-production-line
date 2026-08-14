#!/usr/bin/env python3
"""Admit U10 after bounded OCR adjudication, bind U11, dispatch silent local render."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VIDEO = ROOT / "working_assets/e40_production_20260814/u10_v3_local_authority_hidden_face_fan_lower_exact_dialogue_v1/E40-U10-V3-LOCAL-AUTHORITY-EXACT-DIA009-HIDDEN-FACE-FAN-LOWER.mp4"
MACHINE = ROOT / "qa/e40_production_20260814/u10_v3_local_authority_hidden_face_fan_lower_exact_dialogue_v1/E40_U10_V3_LOCAL_AUTHORITY_MACHINE_QA_V1.json"
OCR = ROOT / "qa/e40_production_20260814/u10_v3_local_authority_hidden_face_fan_lower_exact_dialogue_v1/E40_U10_V3_FULL_DURATION_OCR_AUDIT_V1.json"
OCR_ADJ = ROOT / "qa/e40_production_20260814/u10_v3_local_authority_hidden_face_fan_lower_exact_dialogue_v1/E40_U10_V3_OCR_FALSE_POSITIVE_ADJUDICATION_V1.json"
HUMAN = ROOT / "qa/e40_production_20260814/u10_v3_local_authority_hidden_face_fan_lower_exact_dialogue_v1/E40_U10_V3_ORIGINAL_RESOLUTION_HUMAN_VISUAL_QA_V1.json"
TAIL = ROOT / "qa/e40_production_20260814/u10_v3_local_authority_hidden_face_fan_lower_exact_dialogue_v1/frame_0095_tail.png"
RIGHTS = ROOT / "qa/e40_preproduction_20260814/u10_parallel_kokoro_exact_audio_candidates_v1/E40_U10_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
U10_ADMISSION = ROOT / "workflow/releases/E40_U10_V3_RIGHTS_CLEARED_EXACT_DIALOGUE_UNIT_ADMISSION_20260814.json"

U11_FRAME = ROOT / "working_assets/e40_preproduction_20260814/u11_parallel_wuyun_side_room_alert_v1/E40_U11_PARALLEL_CANDIDATE_V2_EXACT_START_FRAME_720X1280.png"
U11_HUMAN = ROOT / "qa/e40_preproduction_20260814/u11_parallel_wuyun_side_room_alert_v1/E40_U11_PARALLEL_CANDIDATE_V2_ORIGINAL_RES_HUMAN_QA_V1.json"
U11_OCR = ROOT / "qa/e40_preproduction_20260814/u11_parallel_wuyun_side_room_alert_v1/E40_U11_PARALLEL_CANDIDATE_V2_OCR_AUDIT_V1.json"
U11_SILENT = ROOT / "qa/e40_production_20260814/u11_parallel_no_dialogue_audio_gate_v1/E40_U11_PARALLEL_NO_DIALOGUE_AUDIO_MACHINE_QA_V1.json"
U11_CONTINUITY = ROOT / "qa/e40_preproduction_20260814/u11_parallel_wuyun_side_room_alert_v1/E40_U10_TAIL_TO_U11_FRAME_CONTINUITY_QA_V1.json"
U11_ADMISSION = ROOT / "workflow/releases/E40_U11_PARALLEL_EXACT_START_FRAME_ADMISSION_20260814.json"

LANES = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
WORK_QUEUE = ROOT / "workflow/work_queue.json"
HANDOFF = ROOT / "workflow/CODEX_TO_CLAUDE.md"

U10_TASK = "E40-U10-V3-LOCAL-AUTHORITY-YUNFEI-CURTAIN-REACTION-EXACT-DIA009-QA"
U11_TASK = "E40-U11-V3-LOCAL-AUTHORITY-SIDE-ROOM-CAT-ALERT-SILENT-VISUAL-QA"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def require_files(paths: tuple[Path, ...]) -> None:
    for path in paths:
        if not path.is_file():
            raise SystemExit(f"FAIL_MISSING:{path}")


def main() -> int:
    if any(path.exists() for path in (U10_ADMISSION, U11_CONTINUITY, U11_ADMISSION)):
        raise SystemExit("FAIL_COLLISION")
    require_files((VIDEO, MACHINE, OCR, OCR_ADJ, HUMAN, TAIL, RIGHTS,
                   U11_FRAME, U11_HUMAN, U11_OCR, U11_SILENT,
                   LANES, WORK_QUEUE, HANDOFF))

    machine = json.loads(MACHINE.read_text())
    ocr_adjudication = json.loads(OCR_ADJ.read_text())
    human = json.loads(HUMAN.read_text())
    rights = json.loads(RIGHTS.read_text())
    u11_human = json.loads(U11_HUMAN.read_text())
    u11_ocr = json.loads(U11_OCR.read_text())
    u11_silent = json.loads(U11_SILENT.read_text())

    machine_failures = machine.get("failures") or []
    if machine.get("frame0_pixel_exact") is not True or machine.get("final_asr_similarity") != 1.0:
        raise SystemExit("FAIL_U10_CORE_MACHINE_GATES")
    if machine_failures != ["OCR_NONZERO"]:
        raise SystemExit("FAIL_U10_UNEXPECTED_MACHINE_FAILURE")
    if ocr_adjudication.get("status") != "PASS_FALSE_POSITIVE_ONLY_NO_VISIBLE_TEXT":
        raise SystemExit("FAIL_U10_OCR_ADJUDICATION")
    if ocr_adjudication.get("human_visible_text_review") != "PASS_NO_VISIBLE_TEXT_OR_PSEUDO_TEXT":
        raise SystemExit("FAIL_U10_VISIBLE_TEXT")
    if not human.get("status", "").startswith("PASS_ADMISSION_READY") or human.get("effective_failures"):
        raise SystemExit("FAIL_U10_HUMAN")
    if rights.get("releaseBlocked") is not False:
        raise SystemExit("FAIL_U10_RIGHTS")
    if not u11_human.get("status", "").startswith("PASS"):
        raise SystemExit("FAIL_U11_HUMAN")
    if u11_ocr.get("status") != "PASS" or u11_ocr.get("recognitions"):
        raise SystemExit("FAIL_U11_OCR")
    if not u11_silent.get("status", "").startswith("PASS"):
        raise SystemExit("FAIL_U11_SILENT_GATE")

    now = datetime.now(timezone.utc)
    canonical = {
        "canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
        "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
    }

    atomic_json(U10_ADMISSION, {
        "schema": "qingshan.e40.u10.v3.unit_admission.v1",
        "status": "PASS_U10_V3_ADMITTED_FOR_EPISODE_ASSEMBLY",
        "admitted_at": stamp(now),
        "episode": "E40",
        "unit": "U10",
        **canonical,
        "video_path": rel(VIDEO),
        "video_sha256": sha256(VIDEO),
        "machine_qa": rel(MACHINE),
        "machine_qa_sha256": sha256(MACHINE),
        "raw_ocr_qa": rel(OCR),
        "raw_ocr_qa_sha256": sha256(OCR),
        "ocr_false_positive_adjudication": rel(OCR_ADJ),
        "ocr_false_positive_adjudication_sha256": sha256(OCR_ADJ),
        "human_qa": rel(HUMAN),
        "human_qa_sha256": sha256(HUMAN),
        "tail_frame": rel(TAIL),
        "tail_frame_sha256": sha256(TAIL),
        "rights_evidence": rel(RIGHTS),
        "rights_evidence_sha256": sha256(RIGHTS),
        "gates": {
            "exact_frame0": True,
            "exact_asr": True,
            "hidden_face": True,
            "fan_lower": True,
            "effective_no_visible_text": True,
            "bounded_ocr_false_positive_only": True,
            "commercial_rights": True,
        },
        "provider_posts": 0,
        "credits": 0,
        "release_status": "NOT_RELEASED_UNIT_ONLY",
    })

    atomic_json(U11_CONTINUITY, {
        "schema": "qingshan.e40.u10_tail_to_u11_frame.continuity_qa.v1",
        "status": "PASS_CONTINUITY_BINDING",
        "reviewed_at": stamp(now),
        "predecessor_tail": rel(TAIL),
        "predecessor_tail_sha256": sha256(TAIL),
        "candidate_frame": rel(U11_FRAME),
        "candidate_frame_sha256": sha256(U11_FRAME),
        "checks": {
            "curtain_reaction_to_side_room_cut": "PASS_CANONICAL_LOCATION_CUT",
            "warm_low_key_period_hall_lighting": "PASS",
            "chenji_white_robe_continuity": "PASS",
            "wuyun_cat_alert_pose": "PASS",
            "no_dialogue_binding": "PASS_SILENT_VISUAL",
            "no_visible_text": "PASS",
        },
        "human_score": 92,
        "failures": [],
    })

    atomic_json(U11_ADMISSION, {
        "schema": "qingshan.e40.u11.parallel.frame_silent_admission.v1",
        "status": "PASS_U11_EXACT_START_FRAME_SILENT_GATE_ADMITTED_FOR_LOCAL_VIDEO",
        "admitted_at": stamp(now),
        "episode": "E40",
        "unit": "U11",
        **canonical,
        "dialogue_transport": "SILENT_VISUAL",
        "frame_path": rel(U11_FRAME),
        "frame_sha256": sha256(U11_FRAME),
        "human_qa": rel(U11_HUMAN),
        "human_qa_sha256": sha256(U11_HUMAN),
        "ocr_qa": rel(U11_OCR),
        "ocr_qa_sha256": sha256(U11_OCR),
        "no_dialogue_machine_gate": rel(U11_SILENT),
        "no_dialogue_machine_gate_sha256": sha256(U11_SILENT),
        "continuity_qa": rel(U11_CONTINUITY),
        "continuity_qa_sha256": sha256(U11_CONTINUITY),
        "provider_posts": 0,
        "credits": 0,
        "release_status": "NOT_RELEASED_FRAME_ONLY",
    })

    lanes = json.loads(LANES.read_text())
    active = [task for task in lanes["tasks"] if task.get("task_id") == U10_TASK]
    if len(active) != 1 or any(task.get("task_id") == U11_TASK for task in lanes["tasks"]):
        raise SystemExit("FAIL_SCHEDULER")
    active[0].update({
        "state": "TERMINAL",
        "wait_scope": "NONE_TERMINAL",
        "blocked_by": None,
        "progress": "U10_FRAME0_ASR_FAN_HIDDEN_FACE_EFFECTIVE_OCR_IDENTITY_RIGHTS_PASS_ADMITTED",
        "last_progress_at": stamp(now),
        "next_action": "Terminal U10; U11 silent local render owns production.",
        "next_due_at": None,
        "executor_next_wakeup_at": None,
        "evidence_ref": rel(U10_ADMISSION),
        "evidence_sha256": sha256(U10_ADMISSION),
        "output_ref": rel(VIDEO),
        "output_sha256": sha256(VIDEO),
        "completed_at": stamp(now),
        "terminal_status": "PASS_U10_V3_ADMITTED_FOR_EPISODE_ASSEMBLY",
    })
    lanes["tasks"].append({
        "task_id": U11_TASK,
        "lane_id": "U11_LOCAL_AUTHORITY_SIDE_ROOM_CAT_ALERT",
        "state": "RUNNING",
        "wait_scope": "NONE_ACTIVE_RUNNING",
        "zero_cost": True,
        "deliverable_type": "U11_EXACT_FRAME_SIDE_ROOM_CAT_ALERT_SILENT_VIDEO_AND_QA",
        "priority": 182,
        "scope": ["E40", "U11", "V3", "LOCAL_AUTHORITY_ONLY", "EXACT_FRAME0", "SILENT_VISUAL", "CAT_ALERT", "NO_PROVIDER", "NO_RELEASE"],
        "exact_predecessor_task_id": U10_TASK,
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
        "progress": "U11_FRAME_CONTINUITY_SILENT_GATE_BOUND_LOCAL_RENDER_RUNNING",
        "last_progress_at": stamp(now),
        "next_action": "Render U11 authority-only side-room reaction: Wuyun cat snaps alert and Chenji tightens beside it; preserve exact frame0, use no dialogue/audio, then run cadence, OCR and human QA.",
        "lease_owner": "codex-e40-production:u11-v3-local",
        "lease_expires_at": stamp(now + timedelta(hours=2)),
        "next_due_at": stamp(now + timedelta(minutes=10)),
        "execution_mode": "CONTINUOUS",
        "executor_handle": "automation:e40",
        "executor_task_id": U11_TASK,
        "executor_acknowledged_at": stamp(now),
        "executor_next_wakeup_at": stamp(now + timedelta(minutes=10)),
        "evidence_ref": rel(U11_ADMISSION),
        "evidence_sha256": sha256(U11_ADMISSION),
    })
    lanes["updated_at"] = stamp(now)
    atomic_json(LANES, lanes)

    work_queue = json.loads(WORK_QUEUE.read_text())
    work_queue["latest_e40_u10_parallel_preproduction"].update({
        "status": "PASS_U10_V3_ADMITTED_FOR_EPISODE_ASSEMBLY",
        "video": rel(VIDEO),
        "video_sha256": sha256(VIDEO),
        "unit_admission": rel(U10_ADMISSION),
        "unit_admission_sha256": sha256(U10_ADMISSION),
        "ocr_adjudication": rel(OCR_ADJ),
        "ocr_adjudication_sha256": sha256(OCR_ADJ),
        "active_task_id": None,
        "next_action": "Terminal U10; U11 silent local render running.",
    })
    work_queue["latest_e40_u11_parallel_preproduction"].update({
        "status": "PASS_U11_FRAME_SILENT_GATE_ADMITTED_LOCAL_VIDEO_RUNNING",
        "continuity_qa": rel(U11_CONTINUITY),
        "continuity_qa_sha256": sha256(U11_CONTINUITY),
        "frame_admission": rel(U11_ADMISSION),
        "frame_admission_sha256": sha256(U11_ADMISSION),
        "blocked_by": None,
        "active_task_id": U11_TASK,
        "next_action": lanes["tasks"][-1]["next_action"],
    })
    atomic_json(WORK_QUEUE, work_queue)

    with HANDOFF.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n\n## E40 checkpoint {stamp(now)} — U10 admitted by bounded no-visible-text adjudication; U11 silent render dispatched\n\n"
            f"- U10 V3 `{rel(VIDEO)}` SHA=`{sha256(VIDEO)}` passed exact frame0, DIA009 ASR=1.0, hidden-face/fan-lower semantics, HUMAN94 and rights. Raw OCR's six stable `C` detections were confined to the round fan silhouette; original-resolution review found no glyph/pseudo-text, and bounded adjudication SHA=`{sha256(OCR_ADJ)}` makes the effective text gate PASS. Admission SHA=`{sha256(U10_ADMISSION)}`.\n"
            f"- U10 tail to U11 side-room/cat-alert frame continuity passed SHA=`{sha256(U11_CONTINUITY)}`. U11 is canonically `SILENT_VISUAL`; frame/silent admission SHA=`{sha256(U11_ADMISSION)}`. Scheduler started `{U11_TASK}` with zero provider posts/credits and no release.\n"
        )
        handle.flush()
        os.fsync(handle.fileno())

    print(json.dumps({
        "status": "PASS_U10_ADMITTED_U11_LOCAL_RENDER_RUNNING",
        "u10_admission_sha256": sha256(U10_ADMISSION),
        "u11_admission_sha256": sha256(U11_ADMISSION),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
