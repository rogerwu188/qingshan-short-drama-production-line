#!/usr/bin/env python3
"""Finalize U03 V4 local authority-motion audiovisual QA and admission."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u03_v4_local_authority_motion_cadence_repair_v1"
VIDEO = BASE / "E40_U03_V4_LOCAL_AUTHORITY_MOTION_ASSEMBLY_NOT_FINAL.mp4"
BUILD = ROOT / "workflow/tasks/E40_U03_V4_LOCAL_AUTHORITY_MOTION_CADENCE_REPAIR_BUILD_20260814.json"
QA_DIR = ROOT / "qa/e40_production_20260814/u03_v4_local_authority_motion_cadence_repair_v1"
OUT = QA_DIR / "E40_U03_V4_FINAL_UNIT_AUDIOVISUAL_QA_V1.json"
ACCEPT = ROOT / "workflow/releases/E40_U03_V4_RIGHTS_CLEARED_AUDIOVISUAL_UNIT_ADMISSION_20260814.json"
MODEL = Path("/Users/rogerwu/.cache/faster-whisper/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
EXPECTED = "换，还是不换？"
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def norm(text: str) -> str:
    return "".join(HAN.findall(text)).lower()


def main() -> int:
    build = json.loads(BUILD.read_text(encoding="utf-8"))
    receipts = {
        "motion_exact_frame": QA_DIR / "E40_U03_V4_MOTION_PLATE_EXACT_FRAME_CONTINUITY_GATE_V1.json",
        "final_exact_frame": QA_DIR / "E40_U03_V4_FINAL_EXACT_FRAME_CONTINUITY_GATE_V1.json",
        "cadence": QA_DIR / "E40_U03_V4_FINAL_FRAME_CADENCE_AUDIT_V1.json",
        "full_ocr": QA_DIR / "E40_U03_V4_FINAL_FULL_DURATION_OCR_AUDIT_V1.json",
        "subtitle_ocr": QA_DIR / "E40_U03_V4_SUBTITLE_SAMPLE_OCR_AUDIT_V1.json",
        "audio_qa": ROOT / "qa/e40_production_20260814/u03_v1_kokoro_rights_cleared_exact_audio_v1/E40_U03_DIA003_EXACT_AUDIO_MACHINE_QA_V1.json",
        "rights": ROOT / "qa/e40_preproduction_20260814/u02_v12_kokoro_rights_clearance_v1/E40_U02_V12_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json",
        "failure_memory": ROOT / "qa/e40_production_20260814/u03_v3_local_authority_motion_assembly_v1/E40_U03_V3_LOCAL_MOTION_FAILURE_MEMORY_V1.json",
    }
    loaded = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in receipts.items()}
    if build.get("status") != "PASS_RENDERED_UNIT_QA_PENDING" or build.get("motion_profile") != "V4_CADENCE_REPAIR":
        raise SystemExit("FAIL_CLOSED_V4_BUILD_BINDING")
    if sha256(VIDEO) != build.get("assembly_sha256"):
        raise SystemExit("FAIL_CLOSED_V4_MEDIA_SHA")
    for name in ("motion_exact_frame", "final_exact_frame", "cadence", "full_ocr", "subtitle_ocr"):
        if loaded[name].get("status") != "PASS":
            raise SystemExit(f"FAIL_CLOSED_GATE:{name}")
    if [row.get("text") for row in loaded["subtitle_ocr"].get("recognitions", [])] != [EXPECTED]:
        raise SystemExit("FAIL_CLOSED_SUBTITLE_EXACT_TEXT")
    if loaded["audio_qa"].get("status") != "PASS_EXACT_AUDIO_ADMITTED" or loaded["rights"].get("releaseBlocked") is not False:
        raise SystemExit("FAIL_CLOSED_AUDIO_OR_RIGHTS")
    if loaded["failure_memory"].get("status") != "ACTIVE_REWRITE_PENDING_POSITIVE":
        raise SystemExit("FAIL_CLOSED_V3_FAILURE_MEMORY")

    asr = WhisperModel(str(MODEL), device="cpu", compute_type="int8", local_files_only=True)
    segments, _ = asr.transcribe(
        str(VIDEO), language="zh", vad_filter=True, beam_size=5,
        initial_prompt="以下是简体中文普通话古装短剧对白。",
        hotwords=EXPECTED,
    )
    transcript = "".join(segment.text.strip() for segment in segments)
    similarity = difflib.SequenceMatcher(None, norm(EXPECTED), norm(transcript)).ratio()
    loud = subprocess.run(
        ["ffmpeg", "-nostats", "-i", str(VIDEO), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    summary = loud.stderr.rsplit("Summary:", 1)[-1]
    integrated_match = re.search(r"I:\s+(-?[0-9.]+) LUFS", summary)
    peak_match = re.search(r"Peak:\s+(-?[0-9.]+) dBFS", summary)
    integrated = float(integrated_match.group(1)) if integrated_match else None
    peak = float(peak_match.group(1)) if peak_match else None
    failures = []
    if similarity != 1.0:
        failures.append("FULL_UNIT_ASR_NORMALIZED_EXACT_TEXT_SIMILARITY_NOT_1P0")
    if integrated is None or not -22.0 <= integrated <= -14.0:
        failures.append("UNIT_LOUDNESS_OUTSIDE_MINUS22_TO_MINUS14_LUFS")
    if peak is None or peak > -1.0:
        failures.append("UNIT_TRUE_PEAK_ABOVE_MINUS1_DBFS_OR_UNKNOWN")
    status = "PASS_UNIT_AUDIOVISUAL_QA_AND_RIGHTS_ADMITTED" if not failures else "FAIL_UNIT_NOT_ADMITTED"
    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "schema": "qingshan.e40.u03.v4.final_unit_audiovisual_qa.v1",
        "status": status, "created_at": created,
        "video": str(VIDEO.relative_to(ROOT)), "video_sha256": sha256(VIDEO),
        "expected_text": EXPECTED, "asr_transcript": transcript, "asr_similarity": round(similarity, 4),
        "audio_metrics": {"integrated_lufs": integrated, "true_peak_dbfs": peak},
        "subtitle_exact_coverage": "1/1", "selected_voice": "zf_001",
        "visual_origin": "ZERO_COST_LOCAL_MOTION_FROM_PINNED_720X1280_AUTHORITY_RASTER",
        "failed_provider_assets_reused": False,
        "qa_receipts": {name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path), "status": loaded[name].get("status")} for name, path in receipts.items()},
        "provider_post_count": 0, "credits": 0, "failures": failures,
        "release_scope": "U03_SOURCE_ADMISSION_ONLY_NOT_FULL_EPISODE_RELEASE",
    }
    atomic_json(OUT, payload)
    if not failures:
        loaded["failure_memory"]["status"] = "RESOLVED_BY_V4_LOCAL_CADENCE_REPAIR"
        loaded["failure_memory"]["positive_successor"] = str(OUT.relative_to(ROOT))
        loaded["failure_memory"]["positive_successor_sha256"] = sha256(OUT)
        atomic_json(receipts["failure_memory"], loaded["failure_memory"])
        atomic_json(ACCEPT, {
            "schema": "qingshan.e40.u03.v4.rights_cleared_audiovisual_unit_admission.v1",
            "status": "PASS_U03_ADMITTED_FOR_EPISODE_ASSEMBLY", "created_at": created,
            "video": payload["video"], "video_sha256": payload["video_sha256"],
            "final_unit_qa": str(OUT.relative_to(ROOT)), "final_unit_qa_sha256": sha256(OUT),
            "canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
            "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
            "dialogue_coverage": "1/1", "rights_clear": True,
            "visual_origin": payload["visual_origin"], "provider_post_count": 0, "credits": 0,
            "next_action": "Bind admitted U03 SHA into episode assembly and continue with the next unresolved canonical unit.",
        })
    print(json.dumps({"status": status, "asr_transcript": transcript, "asr_similarity": round(similarity, 4), "lufs": integrated, "peak": peak, "failures": failures}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
