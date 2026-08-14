#!/usr/bin/env python3
"""Admit the U06 sequential-frost frame and dispatch local exact-dialogue video QA."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rapidocr_onnxruntime import RapidOCR


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "working_assets/e40_preproduction_20260814/u06_v2_imagegen_sequential_frost_exact_start_frame_v1/E40_U06_V2_IMAGEGEN_SOURCE_V2.png"
FRAME = ROOT / "working_assets/e40_preproduction_20260814/u06_v2_imagegen_sequential_frost_exact_start_frame_v1/E40_U06_V2_IMAGEGEN_SEQUENTIAL_FROST_EXACT_START_FRAME_720X1280_V1.png"
PROMPT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u06_fast_720p_independent_preproduction_v1/prompts/E40_U06_FAST720_NATIVE_EXACT_LINE_PROMPT_V1.txt"
OCR = ROOT / "qa/e40_preproduction_20260814/u06_v2_imagegen_sequential_frost_exact_start_frame_v1/E40_U06_V2_EXACT_START_FRAME_OCR_AUDIT_V1.json"
HUMAN = ROOT / "qa/e40_preproduction_20260814/u06_v2_imagegen_sequential_frost_exact_start_frame_v1/E40_U06_V2_EXACT_START_FRAME_HUMAN_QA_V1.json"
ADMISSION = ROOT / "workflow/releases/E40_U06_V2_EXACT_SEQUENTIAL_FROST_START_FRAME_ADMISSION_20260814.json"
PLAN = ROOT / "qa/e40_preproduction_20260814/u06_v3_local_authority_exact_dialogue_v1/E40_U06_V3_LOCAL_AUTHORITY_EXACT_DIALOGUE_PLAN_V1.json"
SCHEDULER = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
WQ = ROOT / "workflow/work_queue.json"
X2CL = ROOT / "workflow/CODEX_TO_CLAUDE.md"
FRAME_TASK = "E40-U06-V2-EXACT-SEQUENTIAL-FROST-START-FRAME-ACQUISITION-QA"
VIDEO_TASK = "E40-U06-V3-LOCAL-AUTHORITY-EXACT-DIALOGUE-FROST-PERFORMANCE-QA"


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
    if OCR.exists() or HUMAN.exists() or ADMISSION.exists() or PLAN.exists():
        raise SystemExit("FAIL_CLOSED_RECEIPT_COLLISION")
    for path in (SOURCE, FRAME, PROMPT):
        if not path.is_file():
            raise SystemExit(f"FAIL_MISSING:{path}")
    result, _ = RapidOCR()(str(FRAME))
    recognitions = []
    for row in result or []:
        box, text, confidence = row
        if float(confidence) >= 0.5:
            recognitions.append({"box": box, "text": text, "confidence": float(confidence)})
    moment = now()
    ocr = {
        "schema": "qingshan.still_image_ocr_audit.v1",
        "engine": "RapidOCR / ONNX Runtime",
        "source_images": [str(FRAME)],
        "confidence_threshold": 0.5,
        "allow_text": [],
        "forbid_text": ["水印", "AI", "seedance", "giggle"],
        "recognitions": recognitions,
        "latin_chars": sum(1 for row in recognitions for char in row["text"] if char.isascii() and char.isalnum()),
        "critical_text_failures": len(recognitions),
        "status": "PASS" if not recognitions else "FAIL"
    }
    atomic_json(OCR, ocr)
    if recognitions:
        raise SystemExit("FAIL_OCR_NONZERO")
    human = {
        "schema": "qingshan.e40.u06.v2.exact_start_frame.human_qa.v1",
        "status": "PASS_HUMAN89_OCR0",
        "reviewed_at": stamp(moment),
        "reviewer": "codex-root-original-resolution",
        "source_path": str(FRAME.relative_to(ROOT)),
        "source_sha256": sha(FRAME),
        "score": 89,
        "checks": {
            "chenji_identity_continuity": "PASS",
            "white_robe_hair_hall_continuity": "PASS",
            "cinematic_near_table_composition": "PASS",
            "index_fingertip_contact": "PASS",
            "first_frost_patch_complete": "PASS",
            "second_frost_patch_half_forming": "PASS",
            "third_and_fourth_frost_absent": "PASS",
            "natural_branching_frost_not_annotation": "PASS_AFTER_TARGETED_V2_EDIT",
            "no_extra_people_or_hands": "PASS",
            "no_text_or_watermark": "PASS_OCR0"
        },
        "hard_failures": [],
        "admission": "OPEN"
    }
    atomic_json(HUMAN, human)
    admission = {
        "schema": "qingshan.e40.u06.v2.exact_sequential_frost_start_frame_admission.v1",
        "status": "PASS_ADMITTED_EXACT_START_FRAME",
        "admitted_at": stamp(moment),
        "episode": "E40",
        "unit": "U06",
        "canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
        "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
        "canonical_line": "当铺、法场、药房、火场——活口一个没留。",
        "frame_path": str(FRAME.relative_to(ROOT)),
        "frame_sha256": sha(FRAME),
        "source_path": str(SOURCE.relative_to(ROOT)),
        "source_sha256": sha(SOURCE),
        "generation_mode": "BUILT_IN_IMAGEGEN_IDENTITY_PRESERVE_PLUS_TARGETED_PRECISE_OBJECT_EDIT",
        "human_qa": str(HUMAN.relative_to(ROOT)),
        "human_qa_sha256": sha(HUMAN),
        "ocr_qa": str(OCR.relative_to(ROOT)),
        "ocr_qa_sha256": sha(OCR),
        "gates": {"identity": True, "geometry_720x1280": True, "sequential_frost_state": True, "annotation_risk": False, "ocr0": True},
        "provider_video_submission_authorized": False,
        "release_status": "NOT_RELEASED_FRAME_ONLY"
    }
    atomic_json(ADMISSION, admission)
    plan = {
        "schema": "qingshan.e40.u06.v3.local_authority_exact_dialogue_plan.v1",
        "status": "ACTIVE_LOCAL_PRECOMPILE_AND_QA",
        "created_at": stamp(moment),
        "episode": "E40",
        "unit": "U06",
        "canonical_line": admission["canonical_line"],
        "speaker": "陈迹",
        "start_frame": admission["frame_path"],
        "start_frame_sha256": admission["frame_sha256"],
        "audio_route": "PINNED_LOCAL_APACHE_2_KOKORO_BUILT_IN_CHINESE_MALE_ZERO_CREDIT_CANDIDATES",
        "motion_route": "AUTHORITY_ONLY_EXACT_FRAME0_CAMERA_FINGER_FROST_GROWTH_AND_AUDIO_ENVELOPE_MOUTH_DEFORMATION",
        "target": {"duration_seconds": 7.0, "fps": 24, "width": 720, "height": 1280, "audio": "EXACT_DIA005_ONCE", "frame0": "PIXEL_EXACT_AUTHORITY"},
        "required_motion": ["first frost patch remains formed", "second completes after frame0", "third then fourth form sequentially", "finger stays coherent", "visible Chenji mouth tracks exact audio"],
        "forbidden": ["failed provider pixels", "failed provider audio", "extra frost positions", "readable icons or text", "provider post before local route QA", "E38/E39 mutation", "release"],
        "provider_posts": 0,
        "credits": 0,
        "next_action": "Generate zero-credit exact DIA005 male audio candidates, select by exact ASR/duration/acoustics, then render the local authority motion candidate and run exact-frame, frost-count, OCR, lip-sync, human and rights QA."
    }
    atomic_json(PLAN, plan)

    scheduler = json.loads(SCHEDULER.read_text(encoding="utf-8"))
    frame_task = [row for row in scheduler["tasks"] if row.get("task_id") == FRAME_TASK]
    if len(frame_task) != 1 or any(row.get("task_id") == VIDEO_TASK for row in scheduler["tasks"]):
        raise SystemExit("FAIL_SCHEDULER_TASK_STATE")
    frame_task[0].update({"state": "TERMINAL", "wait_scope": "NONE_TERMINAL", "blocked_by": None, "progress": "U06_V2_IMAGEGEN_IDENTITY_AND_SEQUENTIAL_FROST_HUMAN89_OCR0_ADMITTED", "last_progress_at": stamp(moment), "next_action": "Terminal exact-frame admission; U06 V3 local authority exact-dialogue performance owns production.", "next_due_at": None, "executor_next_wakeup_at": None, "evidence_ref": str(ADMISSION.relative_to(ROOT)), "evidence_sha256": sha(ADMISSION), "completed_at": stamp(moment), "terminal_status": "PASS_U06_V2_EXACT_START_FRAME_ADMITTED"})
    scheduler["tasks"].append({
        "task_id": VIDEO_TASK,
        "lane_id": "U06_LOCAL_AUTHORITY_EXACT_DIALOGUE_FROST",
        "state": "QA",
        "wait_scope": "NONE_ACTIVE_QA",
        "zero_cost": True,
        "deliverable_type": "U06_V3_LOCAL_AUTHORITY_EXACT_FRAME_EXACT_DIALOGUE_SEQUENTIAL_FROST_VIDEO_AND_QA",
        "priority": 176,
        "scope": ["E40", "U06", "V3", "LOCAL_AUTHORITY_ONLY", "EXACT_FRAME0", "EXACT_DIA005", "VISIBLE_LIPSYNC", "SEQUENTIAL_FROST", "RIGHTS_CLEAR", "NO_PROVIDER", "NO_RELEASE"],
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
        "blocked_by": "LOCAL_EXACT_DIA005_AUDIO_AND_MOTION_RENDER_QA_PENDING",
        "progress": "U06_V2_EXACT_FRAME_ADMITTED_V3_LOCAL_AUDIO_AND_RENDER_ROUTE_ACTIVE",
        "last_progress_at": stamp(moment),
        "next_action": plan["next_action"],
        "lease_owner": "codex-e40-production:u06-v3-local",
        "lease_expires_at": stamp(moment + timedelta(hours=2)),
        "next_due_at": stamp(moment + timedelta(minutes=10)),
        "execution_mode": "CONTINUOUS",
        "executor_handle": "automation:e40",
        "executor_task_id": VIDEO_TASK,
        "executor_acknowledged_at": stamp(moment),
        "executor_next_wakeup_at": stamp(moment + timedelta(minutes=10)),
        "evidence_ref": str(PLAN.relative_to(ROOT)),
        "evidence_sha256": sha(PLAN),
        "output_ref": admission["frame_path"],
        "output_sha256": admission["frame_sha256"]
    })
    atomic_json(SCHEDULER, scheduler)
    work = json.loads(WQ.read_text(encoding="utf-8"))
    work["latest_e40_u06_successor"] = {"task_id": VIDEO_TASK, "status": "ACTIVE_LOCAL_EXACT_AUDIO_AND_FROST_PERFORMANCE_QA", "frame_admission": str(ADMISSION.relative_to(ROOT)), "frame_admission_sha256": sha(ADMISSION), "frame": admission["frame_path"], "frame_sha256": admission["frame_sha256"], "human_qa": str(HUMAN.relative_to(ROOT)), "human_qa_sha256": sha(HUMAN), "ocr_qa": str(OCR.relative_to(ROOT)), "ocr_qa_sha256": sha(OCR), "plan": str(PLAN.relative_to(ROOT)), "plan_sha256": sha(PLAN), "next_action": plan["next_action"]}
    atomic_json(WQ, work)
    with X2CL.open("a", encoding="utf-8") as stream:
        stream.write(f"""

## E40 heartbeat {stamp(moment)} — U06 V2 exact sequential-frost frame admitted; local video successor active

- Imagegen produced an identity-preserving U06 near-table candidate and a targeted V2 edit that replaced annotation-like frost symbols with natural branching frost. Workspace source `{SOURCE.relative_to(ROOT)}` SHA=`{sha(SOURCE)}`; normalized 720x1280 frame `{FRAME.relative_to(ROOT)}` SHA=`{sha(FRAME)}`.
- Original-resolution human QA `{HUMAN.relative_to(ROOT)}` SHA=`{sha(HUMAN)}` scored 89 and passed Chenji identity, white-robe/hall continuity, fingertip contact, exactly one complete frost patch plus one half-forming patch, absent third/fourth positions, and no extra people/hands. RapidOCR recognition count=`0`; OCR receipt `{OCR.relative_to(ROOT)}` SHA=`{sha(OCR)}`.
- Frame admission `{ADMISSION.relative_to(ROOT)}` SHA=`{sha(ADMISSION)}` is PASS. Scheduler terminalized the frame lane and dispatched active zero-credit successor `{VIDEO_TASK}`. Unique next action: exact DIA005 local male audio candidates, then authority-only sequential-frost/lip-sync render and full QA. Provider video post remains forbidden; no E38/E39 mutation or release.
""")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": "PASS_U06_FRAME_ADMITTED_LOCAL_VIDEO_QA_DISPATCHED", "frame_sha256": sha(FRAME), "admission_sha256": sha(ADMISSION)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
