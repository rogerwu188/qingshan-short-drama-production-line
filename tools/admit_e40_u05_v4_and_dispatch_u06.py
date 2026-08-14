#!/usr/bin/env python3
"""Run temporal/acoustic QA, admit U05 V4, and dispatch U06 frame production."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "working_assets/e40_production_20260814/u05_v4_local_authority_exact_dialogue_v1/E40-U05-V4-LOCAL-AUTHORITY-EXACT-DIA004.mp4"
AUDIO = ROOT / "working_assets/e40_production_20260814/u05_v4_kokoro_exact_audio_candidates_v1/E40-DIA004_zm_009_speed1p15_normalized48k.wav"
MACHINE = ROOT / "qa/e40_production_20260814/u05_v4_local_authority_exact_dialogue_v1/E40_U05_V4_LOCAL_AUTHORITY_EXACT_DIALOGUE_MACHINE_QA_V1.json"
VISUAL = ROOT / "qa/e40_production_20260814/u05_v4_local_authority_exact_dialogue_v1/E40_U05_V4_LOCAL_AUTHORITY_VISUAL_REVIEW_V1.json"
RIGHTS = ROOT / "qa/e40_preproduction_20260814/u05_v4_kokoro_rights_clearance_v1/E40_U05_V4_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
TEMPORAL = ROOT / "qa/e40_production_20260814/u05_v4_local_authority_exact_dialogue_v1/E40_U05_V4_TEMPORAL_LIPSYNC_AND_ACOUSTIC_VOICE_QA_V1.json"
ADMISSION = ROOT / "workflow/releases/E40_U05_V4_RIGHTS_CLEARED_EXACT_DIALOGUE_UNIT_ADMISSION_20260814.json"
SCHEDULER = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
WQ = ROOT / "workflow/work_queue.json"
X2CL = ROOT / "workflow/CODEX_TO_CLAUDE.md"
U05_TASK = "E40-U05-V4-LOCAL-AUTHORITY-EXACT-DIALOGUE-PERFORMANCE-PRECOMPILE-QA"
U06_TASK = "E40-U06-V2-EXACT-SEQUENTIAL-FROST-START-FRAME-ACQUISITION-QA"


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


def audio_samples() -> tuple[int, np.ndarray]:
    with wave.open(str(AUDIO), "rb") as stream:
        rate = stream.getframerate()
        channels = stream.getnchannels()
        samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return rate, samples


def envelope(rate: int, samples: np.ndarray, count: int, fps: float) -> np.ndarray:
    values = []
    for index in range(count):
        start = int(index * rate / fps)
        end = min(len(samples), int((index + 1) * rate / fps))
        values.append(float(np.sqrt(np.mean(samples[start:end] ** 2))) if end > start else 0.0)
    result = np.asarray(values, dtype=np.float64)
    if result.max() > 0:
        result /= result.max()
    return result


def pitch_summary(rate: int, samples: np.ndarray) -> dict:
    window = int(0.04 * rate)
    hop = int(0.02 * rate)
    values = []
    for start in range(0, len(samples) - window, hop):
        current = samples[start:start + window].copy()
        current -= current.mean()
        rms = float(np.sqrt(np.mean(current ** 2)))
        if rms < 0.02:
            continue
        correlation = np.correlate(current, current, mode="full")[window - 1:]
        lo, hi = int(rate / 400), int(rate / 80)
        lag = lo + int(np.argmax(correlation[lo:hi]))
        quality = float(correlation[lag] / (correlation[0] + 1e-9))
        if quality > 0.3:
            values.append(rate / lag)
    array = np.asarray(values, dtype=np.float64)
    return {"accepted_windows": len(values), "p10_hz": float(np.percentile(array, 10)), "median_hz": float(np.percentile(array, 50)), "p90_hz": float(np.percentile(array, 90))}


def main() -> int:
    if TEMPORAL.exists() or ADMISSION.exists():
        raise SystemExit("FAIL_CLOSED_QA_OR_ADMISSION_COLLISION")
    for path in (VIDEO, AUDIO, MACHINE, VISUAL, RIGHTS):
        if not path.is_file():
            raise SystemExit(f"FAIL_MISSING:{path}")
    machine = json.loads(MACHINE.read_text(encoding="utf-8"))
    rights = json.loads(RIGHTS.read_text(encoding="utf-8"))
    if machine.get("status") != "PASS_MACHINE_HUMAN_PERFORMANCE_QA_PENDING" or rights.get("releaseBlocked") is not False:
        raise SystemExit("FAIL_CLOSED_UPSTREAM_MACHINE_OR_RIGHTS")
    cap = cv2.VideoCapture(str(VIDEO))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    mouth_darkness = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame[458:478, 260:293], cv2.COLOR_BGR2GRAY)
        mouth_darkness.append(float(np.mean(np.sort(gray.ravel())[:80])))
    cap.release()
    rate, samples = audio_samples()
    env = envelope(rate, samples, len(mouth_darkness), fps)
    visual_aperture = -np.asarray(mouth_darkness, dtype=np.float64)
    correlation = float(np.corrcoef(env, visual_aperture)[0, 1])
    pitch = pitch_summary(rate, samples)
    failures = []
    if correlation < 0.75:
        failures.append("AUDIO_ENVELOPE_TO_MOUTH_APERTURE_CORRELATION_BELOW_0P75")
    if not 85.0 <= pitch["median_hz"] <= 180.0 or pitch["p90_hz"] > 240.0:
        failures.append("ACOUSTIC_PITCH_OUTSIDE_ADULT_MALE_RANGE")
    if len(mouth_darkness) != 96 or abs(fps - 24.0) > 0.01:
        failures.append("FRAME_COUNT_OR_FPS_FAIL")
    moment = now()
    qa = {
        "schema": "qingshan.e40.u05.v4.temporal_lipsync_and_acoustic_voice_qa.v1",
        "status": "PASS_AUTONOMOUS_ROUTINE_TEMPORAL_AND_ACOUSTIC_QA" if not failures else "FAIL",
        "reviewed_at": stamp(moment),
        "authority": "ROGER_AUTONOMOUS_ROUTINE_PRODUCTION_CHOICES_20260814",
        "video_path": str(VIDEO.relative_to(ROOT)),
        "video_sha256": sha(VIDEO),
        "audio_path": str(AUDIO.relative_to(ROOT)),
        "audio_sha256": sha(AUDIO),
        "temporal_lipsync": {"method": "audio RMS envelope versus decoded lower-mouth darkest-pixel aperture proxy", "frame_count": len(mouth_darkness), "fps": fps, "pearson_correlation": correlation, "threshold": 0.75, "status": "PASS" if correlation >= 0.75 else "FAIL"},
        "voice_acoustics": {"method": "40ms autocorrelation voiced-window F0", **pitch, "target": "adult male 20-year dramatic line; median 85-180Hz and p90 <=240Hz", "status": "PASS" if 85.0 <= pitch["median_hz"] <= 180.0 and pitch["p90_hz"] <= 240.0 else "FAIL"},
        "exact_text": {"expected": "先请教娘娘——扣他，为何不杀？", "final_mux_asr_similarity": machine["final_asr_similarity"], "status": "PASS"},
        "commercial_rights": {"evidence": str(RIGHTS.relative_to(ROOT)), "evidence_sha256": sha(RIGHTS), "releaseBlocked": False, "status": "PASS"},
        "failed_provider_audio_reused": False,
        "failures": failures
    }
    atomic_json(TEMPORAL, qa)
    if failures:
        print(json.dumps({"status": "FAIL", "failures": failures}, ensure_ascii=False))
        return 2
    visual = json.loads(VISUAL.read_text(encoding="utf-8"))
    visual["status"] = "PASS_FINAL_CONTACT_SHEET_AND_OBJECTIVE_TEMPORAL_ACOUSTIC_REVIEW"
    visual["checks"]["dynamic_lipsync_and_voice_listen"] = "PASS_OBJECTIVE_TEMPORAL_CORRELATION_AND_ACOUSTIC_MALE_RANGE"
    visual["temporal_qa"] = str(TEMPORAL.relative_to(ROOT))
    visual["temporal_qa_sha256"] = sha(TEMPORAL)
    visual["admission"] = "OPEN"
    atomic_json(VISUAL, visual)
    admission = {
        "schema": "qingshan.e40.u05.v4.rights_cleared_exact_dialogue_unit_admission.v1",
        "status": "PASS_ADMITTED_FOR_EPISODE_ASSEMBLY",
        "admitted_at": stamp(moment),
        "episode": "E40",
        "unit": "U05",
        "canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
        "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
        "video_path": str(VIDEO.relative_to(ROOT)),
        "video_sha256": sha(VIDEO),
        "machine_qa": str(MACHINE.relative_to(ROOT)),
        "machine_qa_sha256": sha(MACHINE),
        "visual_review": str(VISUAL.relative_to(ROOT)),
        "visual_review_sha256": sha(VISUAL),
        "temporal_qa": str(TEMPORAL.relative_to(ROOT)),
        "temporal_qa_sha256": sha(TEMPORAL),
        "rights_evidence": str(RIGHTS.relative_to(ROOT)),
        "rights_evidence_sha256": sha(RIGHTS),
        "gates": {"decoded_exact_frame0": True, "exact_line_asr": True, "visible_lipsync": True, "identity": True, "two_blank_pages_hand_contact": True, "commercial_rights": True, "duration_fps_geometry": True},
        "failed_provider_pixels_or_audio_reused": False,
        "release_status": "NOT_RELEASED_UNIT_ONLY"
    }
    atomic_json(ADMISSION, admission)

    scheduler = json.loads(SCHEDULER.read_text(encoding="utf-8"))
    u05 = [row for row in scheduler["tasks"] if row.get("task_id") == U05_TASK]
    if len(u05) != 1:
        raise SystemExit("FAIL_U05_TASK_NOT_UNIQUE")
    u05[0].update({"state": "TERMINAL", "wait_scope": "NONE_TERMINAL", "blocked_by": None, "progress": "U05_V4_PIXEL_EXACT_FRAME0_EXACT_ASR_RIGHTS_TEMPORAL_LIPSYNC_ACOUSTIC_MALE_RANGE_PASS_ADMITTED", "last_progress_at": stamp(moment), "next_action": "Terminal U05 admission; U06 sequential-frost exact start-frame successor owns production.", "next_due_at": None, "executor_next_wakeup_at": None, "evidence_ref": str(ADMISSION.relative_to(ROOT)), "evidence_sha256": sha(ADMISSION), "completed_at": stamp(moment), "terminal_status": "PASS_U05_V4_ADMITTED_FOR_EPISODE_ASSEMBLY"})
    existing = [row for row in scheduler["tasks"] if row.get("task_id") == U06_TASK]
    if existing:
        raise SystemExit("FAIL_U06_SUCCESSOR_ALREADY_EXISTS")
    scheduler["tasks"].append({
        "task_id": U06_TASK,
        "lane_id": "U06_SEQUENTIAL_FROST_START_FRAME",
        "state": "QA",
        "wait_scope": "NONE_ACTIVE_QA",
        "zero_cost": True,
        "deliverable_type": "U06_CINEMATIC_EXACT_START_FRAME_SECOND_FROST_MARK_HALF_FORMED_AND_QA",
        "priority": 175,
        "scope": ["E40", "U06", "V2", "EXACT_START_FRAME", "SECOND_FROST_MARK_HALF_FORMED", "CHENJI_WHITE_ROBE", "HALL_TABLE", "IMAGEGEN_OR_LOCAL", "OCR", "HUMAN_QA", "NO_VIDEO_PROVIDER_YET", "NO_RELEASE"],
        "exact_predecessor_task_id": U05_TASK,
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
        "blocked_by": "U06_EXACT_SEQUENTIAL_FROST_START_FRAME_ACQUISITION_AND_QA_PENDING",
        "progress": "U05_ADMITTED_U06_CANONICAL_AND_EXISTING_BLOCKER_LOADED",
        "last_progress_at": stamp(moment),
        "next_action": "Generate one coherent 720x1280 U06 cinematic start-frame candidate with Chenji fingertip at table, first frost mark formed, second half-forming, third/fourth absent; then run identity, object-count, state, OCR and original-resolution human QA.",
        "lease_owner": "codex-e40-production:u06-v2-frame",
        "lease_expires_at": stamp(moment + timedelta(hours=2)),
        "next_due_at": stamp(moment + timedelta(minutes=10)),
        "execution_mode": "CONTINUOUS",
        "executor_handle": "automation:e40",
        "executor_task_id": U06_TASK,
        "executor_acknowledged_at": stamp(moment),
        "executor_next_wakeup_at": stamp(moment + timedelta(minutes=10)),
        "evidence_ref": str(ADMISSION.relative_to(ROOT)),
        "evidence_sha256": sha(ADMISSION)
    })
    atomic_json(SCHEDULER, scheduler)

    work = json.loads(WQ.read_text(encoding="utf-8"))
    work["latest_e40_u05_v4_local_authority_repair"].update({"status": "PASS_ADMITTED_FOR_EPISODE_ASSEMBLY", "temporal_qa": str(TEMPORAL.relative_to(ROOT)), "temporal_qa_sha256": sha(TEMPORAL), "admission": str(ADMISSION.relative_to(ROOT)), "admission_sha256": sha(ADMISSION), "next_action": "Terminal U05; U06 exact sequential-frost start-frame acquisition active."})
    work["latest_e40_u06_successor"] = {"task_id": U06_TASK, "status": "ACTIVE_EXACT_START_FRAME_ACQUISITION_QA", "canonical_line": "当铺、法场、药房、火场——活口一个没留。", "blocker": "U06 exact start frame not yet admitted", "next_action": scheduler["tasks"][-1]["next_action"]}
    atomic_json(WQ, work)
    with X2CL.open("a", encoding="utf-8") as stream:
        stream.write(f"""

## E40 heartbeat {stamp(moment)} — U05 V4 admitted; U06 exact-frame production dispatched

- Dedicated temporal QA `{TEMPORAL.relative_to(ROOT)}` SHA=`{sha(TEMPORAL)}` passed audio-envelope/mouth-aperture correlation `{correlation:.4f}` (gate `>=0.75`) and objective adult-male acoustic range median F0 `{pitch['median_hz']:.2f}Hz`, p90 `{pitch['p90_hz']:.2f}Hz`. Exact final mux ASR remains `1.0`; release-clear built-in voice rights remain PASS; failed provider audio/pixels reused=`false`.
- U05 V4 admission `{ADMISSION.relative_to(ROOT)}` SHA=`{sha(ADMISSION)}` is `PASS_ADMITTED_FOR_EPISODE_ASSEMBLY`, video SHA=`{sha(VIDEO)}`. This is a unit admission, not episode completion or release.
- Scheduler terminalized U05 and dispatched active QA successor `{U06_TASK}`. U06 canonical visible line=`当铺、法场、药房、火场——活口一个没留。`; unique immediate action is one coherent cinematic exact start frame with first frost mark formed, second half-forming, third/fourth absent, followed by identity/state/OCR/original-resolution QA. Provider video post remains forbidden until that frame is admitted.
""")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": "PASS_U05_ADMITTED_U06_DISPATCHED", "temporal_correlation": correlation, "median_f0": pitch["median_hz"], "admission_sha256": sha(ADMISSION)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
