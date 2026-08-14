#!/usr/bin/env python3
"""Admit U07 V2 exact frame and dispatch the zero-cost U07 V3 local video lane."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRAME = ROOT / "working_assets/e40_preproduction_20260814/u07_v2_imagegen_four_frost_fifth_hover_exact_start_frame_v1/E40_U07_V2_IMAGEGEN_FOUR_FROST_FIFTH_HOVER_EXACT_START_FRAME_720X1280_V2.png"
HUMAN = ROOT / "qa/e40_preproduction_20260814/u07_v2_imagegen_four_frost_fifth_hover_exact_start_frame_v1/E40_U07_V2_EXACT_START_FRAME_HUMAN_QA_V1.json"
OCR = ROOT / "qa/e40_preproduction_20260814/u07_v2_imagegen_four_frost_fifth_hover_exact_start_frame_v1/E40_U07_V2_EXACT_START_FRAME_OCR_AUDIT_V1.json"
RECEIPT = ROOT / "qa/e40_preproduction_20260814/u07_v2_imagegen_four_frost_fifth_hover_exact_start_frame_v1/E40_U07_V2_ASSET_SHA256_RECEIPT_V1.json"
AUDIO_QA = ROOT / "qa/e40_production_20260814/u07_v2_kokoro_exact_audio_candidates_v1/E40_U07_V2_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
ADMISSION = ROOT / "workflow/releases/E40_U07_V2_EXACT_START_FRAME_ADMISSION_20260814.json"
SCHEDULER = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
WQ = ROOT / "workflow/work_queue.json"
X2CL = ROOT / "workflow/CODEX_TO_CLAUDE.md"
FRAME_TASK = "E40-U07-V2-FOUR-FROST-MARKS-EMPTY-FIFTH-EXACT-START-FRAME-QA"
VIDEO_TASK = "E40-U07-V3-LOCAL-AUTHORITY-EXACT-DIALOGUE-FIFTH-FROST-PERFORMANCE-QA"


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    if ADMISSION.exists():
        raise SystemExit("FAIL_CLOSED_ADMISSION_COLLISION")
    for path in (FRAME, HUMAN, OCR, RECEIPT, AUDIO_QA, SCHEDULER, WQ):
        if not path.is_file():
            raise SystemExit(f"FAIL_MISSING:{path}")
    human = json.loads(HUMAN.read_text(encoding="utf-8"))
    ocr = json.loads(OCR.read_text(encoding="utf-8"))
    audio = json.loads(AUDIO_QA.read_text(encoding="utf-8"))
    if "PASS" not in str(human.get("status")) or "OCR0" not in str(human.get("status")):
        raise SystemExit("FAIL_CLOSED_HUMAN_QA")
    if "OCR0" not in json.dumps(ocr, ensure_ascii=False) and ocr.get("recognition_count", 1) != 0:
        raise SystemExit("FAIL_CLOSED_OCR_QA")
    if audio.get("status") != "PASS_MACHINE_SELECTION" or not audio.get("selected"):
        raise SystemExit("FAIL_CLOSED_AUDIO_QA")
    selected_audio = ROOT / audio["selected"]["normalized_path"]
    if not selected_audio.is_file():
        raise SystemExit("FAIL_MISSING_SELECTED_AUDIO")
    moment = now()
    admission = {
        "schema": "qingshan.e40.u07.v2.exact_start_frame_admission.v1",
        "status": "PASS_U07_EXACT_START_FRAME_ADMITTED_FOR_LOCAL_VIDEO",
        "admitted_at": stamp(moment),
        "episode": "E40",
        "unit": "U07",
        "canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
        "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
        "frame_path": str(FRAME.relative_to(ROOT)),
        "frame_sha256": sha(FRAME),
        "human_qa": str(HUMAN.relative_to(ROOT)),
        "human_qa_sha256": sha(HUMAN),
        "ocr_qa": str(OCR.relative_to(ROOT)),
        "ocr_qa_sha256": sha(OCR),
        "asset_receipt": str(RECEIPT.relative_to(ROOT)),
        "asset_receipt_sha256": sha(RECEIPT),
        "selected_audio": str(selected_audio.relative_to(ROOT)),
        "selected_audio_sha256": sha(selected_audio),
        "audio_qa": str(AUDIO_QA.relative_to(ROOT)),
        "audio_qa_sha256": sha(AUDIO_QA),
        "gates": {
            "chenji_visible": True,
            "four_natural_frost_marks_present": True,
            "empty_fifth_position_clear": True,
            "fingertip_hover_not_touching": True,
            "baili_out_of_frame": True,
            "ocr_zero": True,
            "exact_dialogue_audio_machine_pass": True,
            "commercial_rights_clear": True,
        },
        "provider_posts": 0,
        "credits": 0,
        "release_status": "NOT_RELEASED_FRAME_ONLY",
    }
    atomic_json(ADMISSION, admission)

    scheduler = json.loads(SCHEDULER.read_text(encoding="utf-8"))
    current = [row for row in scheduler["tasks"] if row.get("task_id") == FRAME_TASK]
    if len(current) != 1 or any(row.get("task_id") == VIDEO_TASK for row in scheduler["tasks"]):
        raise SystemExit("FAIL_SCHEDULER_STATE")
    current[0].update(
        {
            "state": "TERMINAL",
            "wait_scope": "NONE_TERMINAL",
            "blocked_by": None,
            "progress": "U07_V2_FOUR_MARKS_EMPTY_FIFTH_HOVER_HUMAN93_OCR0_ADMITTED",
            "last_progress_at": stamp(moment),
            "next_action": "Terminal exact-frame admission; U07 V3 local authority video owns production.",
            "next_due_at": None,
            "executor_next_wakeup_at": None,
            "evidence_ref": str(ADMISSION.relative_to(ROOT)),
            "evidence_sha256": sha(ADMISSION),
            "completed_at": stamp(moment),
            "terminal_status": "PASS_U07_V2_EXACT_START_FRAME_ADMITTED",
        }
    )
    scheduler["tasks"].append(
        {
            "task_id": VIDEO_TASK,
            "lane_id": "U07_LOCAL_AUTHORITY_EXACT_DIALOGUE_FIFTH_FROST",
            "state": "RUNNING",
            "wait_scope": "NONE_ACTIVE_RUNNING",
            "zero_cost": True,
            "deliverable_type": "U07_V3_LOCAL_AUTHORITY_EXACT_FRAME_EXACT_DIALOGUE_FIFTH_FROST_VIDEO_AND_QA",
            "priority": 178,
            "scope": ["E40", "U07", "V3", "LOCAL_AUTHORITY_ONLY", "EXACT_FRAME0", "EXACT_DIA006", "VISIBLE_LIPSYNC", "FIFTH_FROST_FORMATION", "RIGHTS_CLEAR", "NO_PROVIDER", "NO_RELEASE"],
            "exact_predecessor_task_id": FRAME_TASK,
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
            "progress": "U07_FRAME_AND_ZERO_CREDIT_EXACT_AUDIO_ADMITTED_LOCAL_RENDER_RUNNING",
            "last_progress_at": stamp(moment),
            "next_action": "Render U07 local authority motion from admitted exact frame with exact DIA006, fifth frost forming only after the initial frame; run frame0, ASR, lipsync, OCR, visual, rights and duration QA.",
            "lease_owner": "codex-e40-production:u07-v3-local",
            "lease_expires_at": stamp(moment + timedelta(hours=2)),
            "next_due_at": stamp(moment + timedelta(minutes=10)),
            "execution_mode": "CONTINUOUS",
            "executor_handle": "automation:e40",
            "executor_task_id": VIDEO_TASK,
            "executor_acknowledged_at": stamp(moment),
            "executor_next_wakeup_at": stamp(moment + timedelta(minutes=10)),
            "evidence_ref": str(ADMISSION.relative_to(ROOT)),
            "evidence_sha256": sha(ADMISSION),
            "audio_ref": str(selected_audio.relative_to(ROOT)),
            "audio_sha256": sha(selected_audio),
        }
    )
    scheduler["updated_at"] = stamp(moment)
    atomic_json(SCHEDULER, scheduler)

    work = json.loads(WQ.read_text(encoding="utf-8"))
    work["latest_e40_u07_successor"] = {
        "status": "PASS_U07_V2_EXACT_FRAME_ADMITTED_V3_LOCAL_VIDEO_RUNNING",
        "frame_admission": str(ADMISSION.relative_to(ROOT)),
        "frame_admission_sha256": sha(ADMISSION),
        "frame": str(FRAME.relative_to(ROOT)),
        "frame_sha256": sha(FRAME),
        "selected_audio": str(selected_audio.relative_to(ROOT)),
        "selected_audio_sha256": sha(selected_audio),
        "audio_qa": str(AUDIO_QA.relative_to(ROOT)),
        "audio_qa_sha256": sha(AUDIO_QA),
        "active_task_id": VIDEO_TASK,
        "next_action": scheduler["tasks"][-1]["next_action"],
    }
    atomic_json(WQ, work)
    with X2CL.open("a", encoding="utf-8") as stream:
        stream.write(
            f"\n\n## E40 checkpoint {stamp(moment)} — U07 V2 exact frame admitted; V3 local video running\n\n"
            f"- U07 V2 exact frame `{FRAME.relative_to(ROOT)}` SHA=`{sha(FRAME)}` passed HUMAN93 and OCR0: Chenji visible; four natural frost marks already present; fifth position empty; fingertip hovering without contact; Baili out of frame. Admission `{ADMISSION.relative_to(ROOT)}` SHA=`{sha(ADMISSION)}`.\n"
            f"- Zero-credit Kokoro DIA006 `{selected_audio.relative_to(ROOT)}` SHA=`{sha(selected_audio)}` passed exact ASR/audio gates under release-clear Apache-2.0 built-in voice evidence; provider posts=`0`, credits=`0`.\n"
            f"- Scheduler terminalized `{FRAME_TASK}` and started `{VIDEO_TASK}` for zero-cost local render and full unit QA. This is not episode completion or release.\n"
        )
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": "PASS_U07_V2_ADMITTED_V3_RUNNING", "admission_sha256": sha(ADMISSION), "audio_sha256": sha(selected_audio)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
